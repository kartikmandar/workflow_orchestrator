# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Workflow Orchestrator Environment — full implementation.

Wires together DAGExecutor, AgentPool, and RewardCalculator into the OpenEnv
Environment interface. Each step: validate action → execute → tick agents →
apply events → update DAG → calculate reward → check termination.
"""

from typing import Any, Optional, Union
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment

try:
    from ..models import (
        EpisodeLog,
        OrchestratorAction,
        OrchestratorObservation,
        OrchestratorState,
    )
except ImportError:
    from models import (
        EpisodeLog,
        OrchestratorAction,
        OrchestratorObservation,
        OrchestratorState,
    )

try:
    from .agent_pool import AgentPool
    from .dag_executor import DAGExecutor
    from .reward_calculator import RewardCalculator
    from .task_registry import TaskConfig, get_task
except ImportError:
    from server.agent_pool import AgentPool
    from server.dag_executor import DAGExecutor
    from server.reward_calculator import RewardCalculator
    from server.task_registry import TaskConfig, get_task


# Module-level store: latest episode log per task_id AND by episode_id.
# Shared between environment instances and the /grader endpoint.
# _episode_store keyed by task_id stores the most recent episode for that task
# (used by /grader when only task_id is provided).
# _episode_store_by_id keyed by episode_id for concurrent session safety.
_episode_store: dict[str, EpisodeLog] = {}
_episode_store_by_id: dict[str, EpisodeLog] = {}


class OrchestratorEnvironment(
    Environment[OrchestratorAction, OrchestratorObservation, OrchestratorState]
):
    """Workflow Orchestrator Environment.

    An LLM agent acts as a project coordinator, managing DAG-based workflows
    of subtasks across simulated specialist agents with varying capabilities,
    failure rates, and cost profiles.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self) -> None:
        super().__init__()
        self._config: Optional[TaskConfig] = None
        self._dag: Optional[DAGExecutor] = None
        self._pool: Optional[AgentPool] = None
        self._rc: Optional[RewardCalculator] = None
        self._log: Optional[EpisodeLog] = None

        self._step_count: int = 0
        self._time_elapsed: int = 0
        self._time_remaining: int = 0
        self._total_reward: float = 0.0
        self._done: bool = False
        self._synthesized: bool = False

        self._failures_occurred: int = 0
        self._failures_recovered: int = 0
        self._parallelism_events: int = 0
        self._capacity_violations: int = 0

        self._output_templates: dict[str, str] = {}
        self._agent_speeds: dict[str, int] = {}

        self._state_obj: OrchestratorState = OrchestratorState(
            task_id="", task_name="", difficulty="",
            subtask_statuses={}, agent_statuses={}, completed_outputs={},
            total_reward=0.0, failures_occurred=0, failures_recovered=0,
            parallelism_events=0, capacity_violations=0,
            episode_id=str(uuid4()), step_count=0,
        )

    # ── Reset ──

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> OrchestratorObservation:
        """Reset the environment and return initial observation."""
        task_id = kwargs.get("task_id", "easy")
        config = get_task(task_id)
        self._config = config

        self._dag = DAGExecutor(config.subtask_definitions)
        self._pool = AgentPool(
            config.agent_definitions, config.reliability_overrides, config.seed
        )
        self._rc = RewardCalculator(config)
        self._log = EpisodeLog(
            task_id=task_id,
            budget_total=config.constraints.get("cost_budget"),
        )

        self._output_templates = {
            s["id"]: s.get("output_template", "")
            for s in config.subtask_definitions
        }
        self._agent_speeds = {
            a["name"]: a["speed"] for a in config.agent_definitions
        }

        self._step_count = 0
        self._time_elapsed = 0
        self._time_remaining = config.constraints["time_budget"]
        self._total_reward = 0.0
        self._done = False
        self._synthesized = False

        self._failures_occurred = 0
        self._failures_recovered = 0
        self._parallelism_events = 0
        self._capacity_violations = 0

        self._state_obj = OrchestratorState(
            task_id=config.task_id,
            task_name=config.name,
            difficulty=config.difficulty,
            subtask_statuses={
                s.id: s.status for s in self._dag.get_subtask_infos()
            },
            agent_statuses={
                a.name: a.status for a in self._pool.get_agent_infos()
            },
            completed_outputs={},
            total_reward=0.0,
            failures_occurred=0,
            failures_recovered=0,
            parallelism_events=0,
            capacity_violations=0,
            budget_total=config.constraints.get("cost_budget"),
            budget_used=0.0,
            episode_id=episode_id or str(uuid4()),
            step_count=0,
        )

        return self._build_observation(reward=0.0, errors=[])

    # ── Step ──

    def step(
        self,
        action: OrchestratorAction,
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> OrchestratorObservation:
        """Take a step in the environment."""
        # Guard: reject steps after episode is done
        if self._done:
            return self._build_observation(
                reward=0.0,
                errors=["Episode is already done. Call reset() to start a new episode."],
            )

        errors_this_step: list[str] = []
        events_this_step: list[dict[str, Any]] = []

        # Step 1: Validate action
        valid, error = self._validate_action(action)

        # Step 2 & 3: Execute action + log
        if valid:
            self._execute_action(action)
            self._log.append(self._step_count, "action_taken", {
                "action_type": action.action_type,
                "subtask_id": action.subtask_id,
                "agent_name": action.agent_name,
            })
        else:
            errors_this_step.append(error)
            self._log.append(self._step_count, "action_invalid", {
                "action_type": action.action_type,
                "subtask_id": action.subtask_id,
                "agent_name": action.agent_name,
                "error": error,
            })
            if "capacity" in (error or "").lower():
                self._capacity_violations += 1

        # Step 4: Detect parallelism BEFORE tick (captures concurrent assignments)
        in_progress = self._dag.get_in_progress_subtasks()
        if len(in_progress) >= 2:
            events_this_step.append({
                "event_type": "parallelism",
                "concurrent_tasks": list(in_progress),
            })
            self._log.append(self._step_count, "parallelism", {
                "concurrent_tasks": list(in_progress),
            })
            self._parallelism_events += 1

        # Step 5: Tick agent pool
        tick_results = self._pool.tick(self._step_count)
        for result in tick_results:
            if result.succeeded:
                output = self._output_templates.get(result.subtask_id, "")
                self._dag.complete(result.subtask_id, output)
                self._pool.release_agent(result.agent_name)
                attempt = self._dag.get_subtask_attempt_count(result.subtask_id)
                if attempt > 0:
                    self._failures_recovered += 1
                events_this_step.append({
                    "event_type": "subtask_completed",
                    "subtask_id": result.subtask_id,
                })
                self._log.append(self._step_count, "subtask_completed", {
                    "subtask_id": result.subtask_id,
                    "agent_name": result.agent_name,
                    "attempt_count": attempt,
                })
            else:
                self._dag.fail(result.subtask_id, result.output_or_error)
                self._pool.release_agent(result.agent_name)
                self._failures_occurred += 1
                events_this_step.append({
                    "event_type": "subtask_failed",
                    "subtask_id": result.subtask_id,
                    "is_permanent": result.is_permanent_failure,
                })
                self._log.append(self._step_count, "subtask_failed", {
                    "subtask_id": result.subtask_id,
                    "agent_name": result.agent_name,
                    "error": result.output_or_error,
                    "is_permanent": result.is_permanent_failure,
                })

        # Step 6: Apply scheduled events
        fired = self._pool.apply_scheduled_events(
            self._step_count, self._config.scheduled_events
        )
        for event in fired:
            if event["event_type"] == "agent_dropout":
                self._log.append(self._step_count, "agent_dropout", event)
                released_task = event.get("released_task")
                if event.get("was_working") and released_task:
                    self._dag.fail(released_task, "agent went offline")
                    self._failures_occurred += 1
            elif event["event_type"] == "agent_degraded":
                self._log.append(self._step_count, "agent_degraded", event)

        # Step 7: Update DAG ready statuses
        self._dag.update_ready_statuses()

        # Step 8: Calculate step reward
        step_reward = self._rc.calculate_step_reward(
            action, valid, error, self._dag, self._pool,
            self._log, self._step_count, events_this_step,
        )
        self._total_reward += step_reward

        # Step 9: Advance time
        self._step_count += 1
        self._time_elapsed += 1
        self._time_remaining -= 1

        # Step 10: Check termination
        if self._time_remaining <= 0 or self._synthesized:
            self._done = True
            end_bonus = self._rc.calculate_end_bonus(
                self._dag, self._pool,
                max(0, self._time_remaining),
                self._config.constraints["time_budget"],
                self._synthesized,
            )
            self._total_reward += end_bonus
            step_reward += end_bonus

            # Sync log metadata
            self._log.total_steps = self._step_count
            self._log.time_remaining = self._time_remaining
            self._log.budget_used = self._pool.get_budget_used()

            self._log.append(self._step_count, "episode_end", {
                "all_completed": self._dag.is_all_completed(),
                "synthesized": self._synthesized,
                "total_reward": self._total_reward,
            })

            # Store for grader access (both by task_id and episode_id)
            _episode_store[self._config.task_id] = self._log
            _episode_store_by_id[self._state_obj.episode_id] = self._log

        # Step 11: Update internal state + build observation
        self._state_obj = OrchestratorState(
            task_id=self._config.task_id,
            task_name=self._config.name,
            difficulty=self._config.difficulty,
            subtask_statuses={
                s.id: s.status for s in self._dag.get_subtask_infos()
            },
            agent_statuses={
                a.name: a.status for a in self._pool.get_agent_infos()
            },
            completed_outputs=self._dag.get_completed_outputs(),
            total_reward=self._total_reward,
            failures_occurred=self._failures_occurred,
            failures_recovered=self._failures_recovered,
            parallelism_events=self._parallelism_events,
            capacity_violations=self._capacity_violations,
            budget_total=self._config.constraints.get("cost_budget"),
            budget_used=self._pool.get_budget_used(),
            episode_id=self._state_obj.episode_id,
            step_count=self._step_count,
        )

        return self._build_observation(reward=step_reward, errors=errors_this_step)

    # ── State property ──

    @property
    def state(self) -> OrchestratorState:
        return self._state_obj

    # ── Private: validation ──

    def _validate_action(
        self, action: OrchestratorAction
    ) -> tuple[bool, Optional[str]]:
        """Validate an action against current state. Returns (is_valid, error)."""
        action_type = action.action_type

        if action_type == "delegate":
            return self._validate_delegate(action)
        elif action_type == "retry":
            return self._validate_retry(action)
        elif action_type == "wait":
            return (True, None)
        elif action_type == "synthesize":
            if not self._dag.is_all_completed():
                return (False, "Cannot synthesize: not all subtasks completed")
            return (True, None)
        elif action_type == "abort":
            return self._validate_abort(action)
        else:
            return (False, f"Unknown action type: {action_type}")

    def _validate_delegate(
        self, action: OrchestratorAction
    ) -> tuple[bool, Optional[str]]:
        sid = action.subtask_id
        agent = action.agent_name

        if not sid or not self._dag.is_valid_subtask(sid):
            return (False, f"Unknown subtask_id: '{sid}'")
        status = self._dag.get_subtask_status(sid)
        if status != "ready":
            return (False, f"Subtask '{sid}' is not ready (status: {status})")
        if not agent or not self._pool.is_online(agent):
            return (False, f"Unknown or offline agent: '{agent}'")
        if not self._pool.is_idle(agent):
            return (False, f"Agent '{agent}' is not idle")
        subtask_type = self._dag.get_subtask_type(sid)
        if not self._pool.has_capability(agent, subtask_type):
            return (False, f"Agent '{agent}' lacks capability '{subtask_type}'")
        capacity_limit = self._config.constraints["capacity_limit"]
        if self._pool.get_active_count() >= capacity_limit:
            return (False, f"capacity limit exceeded ({capacity_limit})")
        return (True, None)

    def _validate_retry(
        self, action: OrchestratorAction
    ) -> tuple[bool, Optional[str]]:
        sid = action.subtask_id
        agent = action.agent_name

        if not sid or not self._dag.is_valid_subtask(sid):
            return (False, f"Unknown subtask_id: '{sid}'")
        status = self._dag.get_subtask_status(sid)
        if status != "failed":
            return (False, f"Subtask '{sid}' is not failed (status: {status})")
        if not agent or not self._pool.is_online(agent):
            return (False, f"Unknown or offline agent: '{agent}'")
        if not self._pool.is_idle(agent):
            return (False, f"Agent '{agent}' is not idle")
        subtask_type = self._dag.get_subtask_type(sid)
        if not self._pool.has_capability(agent, subtask_type):
            return (False, f"Agent '{agent}' lacks capability '{subtask_type}'")
        capacity_limit = self._config.constraints["capacity_limit"]
        if self._pool.get_active_count() >= capacity_limit:
            return (False, f"capacity limit exceeded ({capacity_limit})")

        # Check for permanent failure
        attempt_count = self._dag.get_subtask_attempt_count(sid)
        reliability = self._get_effective_reliability(agent, subtask_type, attempt_count)
        if reliability == 0.0:
            return (False, f"permanent failure: Agent '{agent}' cannot complete '{subtask_type}'")

        return (True, None)

    def _validate_abort(
        self, action: OrchestratorAction
    ) -> tuple[bool, Optional[str]]:
        sid = action.subtask_id
        if not sid or not self._dag.is_valid_subtask(sid):
            return (False, f"Unknown subtask_id: '{sid}'")
        status = self._dag.get_subtask_status(sid)
        if status == "completed":
            return (False, f"Cannot abort '{sid}': already completed")
        return (True, None)

    # ── Private: execution ──

    def _execute_action(self, action: OrchestratorAction) -> None:
        """Execute a validated action, mutating DAG and pool state."""
        action_type = action.action_type

        if action_type == "delegate":
            sid = action.subtask_id
            agent = action.agent_name
            subtask_type = self._dag.get_subtask_type(sid)
            attempt_count = self._dag.get_subtask_attempt_count(sid)
            self._dag.delegate(sid, agent)
            self._pool.assign(agent, sid, subtask_type, attempt_count)
            self._dag.set_steps_remaining(sid, self._agent_speeds[agent])
            self._log.append(self._step_count, "subtask_delegated", {
                "subtask_id": sid, "agent_name": agent,
                "subtask_type": subtask_type,
            })

        elif action_type == "retry":
            sid = action.subtask_id
            agent = action.agent_name
            subtask_type = self._dag.get_subtask_type(sid)
            attempt_count = self._dag.get_subtask_attempt_count(sid)
            self._dag.retry(sid, agent)
            self._pool.assign(agent, sid, subtask_type, attempt_count)
            self._dag.set_steps_remaining(sid, self._agent_speeds[agent])

        elif action_type == "wait":
            pass  # Time advances regardless

        elif action_type == "synthesize":
            self._synthesized = True
            self._done = True

        elif action_type == "abort":
            self._dag.abort(action.subtask_id)

    # ── Private: observation building ──

    def _build_observation(
        self, reward: float, errors: list[str]
    ) -> OrchestratorObservation:
        """Build the full observation from current state."""
        cost_budget = self._config.constraints.get("cost_budget")
        budget_used = self._pool.get_budget_used()

        # Clamp reward to [0, 1] for OpenEnv evaluation compliance.
        # Internal _total_reward still uses unclamped values for accurate tracking;
        # graders use episode logs, not observation rewards, so they're unaffected.
        clamped_reward = max(0.0, min(1.0, reward))

        return OrchestratorObservation(
            task_description=self._config.description,
            subtasks=self._dag.get_subtask_infos(),
            agents=self._pool.get_agent_infos(),
            completed_outputs=self._dag.get_completed_outputs(),
            errors=errors,
            time_remaining=self._time_remaining,
            time_elapsed=self._time_elapsed,
            capacity_limit=self._config.constraints["capacity_limit"],
            active_task_count=self._pool.get_active_count(),
            budget_remaining=(cost_budget - budget_used) if cost_budget is not None else None,
            budget_used=budget_used,
            available_actions=self._compute_available_actions(),
            hint=self._compute_hint(),
            done=self._done,
            reward=clamped_reward,
        )

    def _compute_available_actions(self) -> list[str]:
        """Determine which actions are currently valid."""
        if self._done:
            return []

        actions = ["wait"]
        ready = self._dag.get_ready_subtasks()
        failed = self._dag.get_failed_subtasks()
        capacity_limit = self._config.constraints["capacity_limit"]
        active_count = self._pool.get_active_count()

        # delegate: ready subtasks + idle capable agents + under capacity
        if ready and active_count < capacity_limit:
            for r in ready:
                st_type = self._dag.get_subtask_type(r)
                if self._pool.get_capable_agents(st_type):
                    actions.append("delegate")
                    break

        # retry: failed subtasks + idle capable agents
        if failed:
            for f in failed:
                st_type = self._dag.get_subtask_type(f)
                if self._pool.get_capable_agents(st_type):
                    actions.append("retry")
                    break

        # synthesize: all done
        if self._dag.is_all_completed():
            actions.append("synthesize")

        # abort: any non-completed subtask
        infos = self._dag.get_subtask_infos()
        if any(s.status != "completed" for s in infos):
            actions.append("abort")

        return actions

    def _compute_hint(self) -> Optional[str]:
        """Generate a one-line hint based on current state."""
        if self._done:
            return None

        # Priority 1: Failed subtask + idle capable agent (excluding permanently failing agents)
        failed = self._dag.get_failed_subtasks()
        for f in failed:
            st_type = self._dag.get_subtask_type(f)
            attempt_count = self._dag.get_subtask_attempt_count(f)
            capable = self._pool.get_capable_agents(st_type)
            # Filter out agents that will permanently fail on this subtask type
            viable = [
                a for a in capable
                if self._pool.get_effective_reliability(a, st_type, attempt_count) > 0.0
            ]
            if viable:
                return f"Retry '{f}' with '{viable[0]}'"
            elif capable:
                return f"'{f}' failed — all capable agents have permanent failures, try a different agent"

        # Priority 2: Ready subtasks + idle agents
        ready = self._dag.get_ready_subtasks()
        idle = self._pool.get_idle_agents()
        if ready and idle:
            return f"{len(ready)} subtask(s) ready, {len(idle)} agent(s) idle"

        # Priority 3: All complete
        if self._dag.is_all_completed():
            return "All subtasks complete — synthesize to finish"

        # Priority 4: Time pressure
        if self._time_remaining <= 3:
            return f"Only {self._time_remaining} step(s) remaining"

        return None

    # ── Private: helpers ──

    def _get_effective_reliability(
        self, agent_name: str, subtask_type: str, attempt_count: int
    ) -> float:
        """Check reliability for permanent failure detection.

        Delegates to AgentPool.get_effective_reliability() to avoid
        duplicating reliability override logic.
        """
        return self._pool.get_effective_reliability(
            agent_name, subtask_type, attempt_count
        )
