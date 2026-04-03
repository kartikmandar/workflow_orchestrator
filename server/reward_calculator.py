"""Dense per-step reward calculation and end-of-episode bonuses.

7 positive signals, 9 negative signals, SLA penalties, and end-of-episode bonuses.
"""

from typing import Any

from models import EpisodeLog, OrchestratorAction

from .agent_pool import AgentPool
from .dag_executor import DAGExecutor
from .task_registry import TaskConfig


class RewardCalculator:
    """Computes step rewards and end-of-episode bonuses for the orchestrator."""

    def __init__(self, task_config: TaskConfig) -> None:
        self._config = task_config
        self._sla_milestones = task_config.sla_milestones or {}
        self._cost_budget = task_config.constraints.get("cost_budget")
        self._communication_subtasks = task_config.communication_subtasks
        self._steps_since_failure: dict[str, int] = {}

    def calculate_step_reward(
        self,
        action: OrchestratorAction,
        action_valid: bool,
        action_error: str | None,
        dag: DAGExecutor,
        agent_pool: AgentPool,
        episode_log: EpisodeLog,
        step: int,
        events_this_step: list[dict[str, Any]],
    ) -> float:
        """Calculate the reward for a single step.

        Args:
            action: The action taken this step
            action_valid: Whether the action passed validation
            action_error: Error message if invalid, None otherwise
            dag: Current DAG state
            agent_pool: Current agent pool state
            episode_log: Episode event log
            step: Current step number
            events_this_step: List of events that occurred this step
                (completions, failures, parallelism, etc.)

        Returns:
            Net reward for this step (can be negative)
        """
        reward = 0.0

        if not action_valid:
            reward += self._penalty_for_invalid_action(action, action_error)
            reward += self._check_sla_penalties(dag, step)
            reward += self._check_unrecovered_failures(dag, action)
            return reward

        action_type = action.action_type

        # ── Positive signals ──

        if action_type == "delegate":
            reward += 0.05  # correct_delegation

            # Communication sent bonus
            if action.subtask_id in self._communication_subtasks:
                reward += 0.05  # communication_sent

            # Cost-efficient choice: cheaper agent chosen when others available
            if self._cost_budget is not None and action.subtask_id and action.agent_name:
                subtask_type = dag.get_subtask_type(action.subtask_id)
                capable = agent_pool.get_capable_agents(subtask_type)
                if len(capable) > 1:
                    chosen_cost = agent_pool.get_agent_cost(action.agent_name)
                    min_cost = min(agent_pool.get_agent_cost(a) for a in capable)
                    if chosen_cost <= min_cost:
                        reward += 0.04  # cost_efficient_choice
                    elif chosen_cost > min_cost:
                        reward -= 0.04  # wasteful_assignment

        elif action_type == "retry":
            reward += 0.05  # correct_delegation (retry is a form of delegation)

        elif action_type == "wait":
            ready = dag.get_ready_subtasks()
            idle = agent_pool.get_idle_agents()
            has_assignable = False
            for r in ready:
                st_type = dag.get_subtask_type(r)
                for a in idle:
                    if agent_pool.has_capability(a, st_type):
                        has_assignable = True
                        break
                if has_assignable:
                    break

            if has_assignable:
                reward -= 0.03  # unnecessary_wait
            else:
                reward += 0.03  # efficient_wait

        elif action_type == "abort":
            reward -= 0.03  # abort_penalty

        # ── Events this step ──

        for event in events_this_step:
            et = event.get("event_type")
            if et == "subtask_completed":
                reward += 0.08  # subtask_completed

                # Check if this was a failure recovery
                subtask_id = event.get("subtask_id", "")
                attempt = dag.get_subtask_attempt_count(subtask_id)
                if attempt > 0:
                    reward += 0.10  # failure_recovered

            elif et == "parallelism":
                reward += 0.10  # parallelism_exploited

        # ── SLA penalties ──
        reward += self._check_sla_penalties(dag, step)

        # ── Unrecovered failure check ──
        reward += self._check_unrecovered_failures(dag, action)

        return reward

    def calculate_end_bonus(
        self,
        dag: DAGExecutor,
        agent_pool: AgentPool,
        time_remaining: int,
        time_budget: int,
        synthesized: bool,
    ) -> float:
        """Calculate the end-of-episode bonus/penalty.

        Returns:
            Bonus amount (positive) or penalty (negative)
        """
        bonus = 0.0

        if dag.is_all_completed() and synthesized:
            bonus += 0.20  # all completed + synthesized

            # Time efficiency bonus
            if time_budget > 0:
                bonus += 0.10 * (time_remaining / time_budget)

            # Cost efficiency bonus
            if self._cost_budget is not None and self._cost_budget > 0:
                cost_ratio = agent_pool.get_budget_used() / self._cost_budget
                bonus += 0.05 * max(0.0, 1.0 - cost_ratio)
        else:
            bonus -= 0.10  # incomplete episode

        return bonus

    # ── Private helpers ──

    def _penalty_for_invalid_action(
        self, action: OrchestratorAction, error: str | None
    ) -> float:
        """Determine the penalty for an invalid action based on error type."""
        error = error or ""

        if "lacks capability" in error or "lacks required tooling" in error:
            return -0.05  # wrong_agent

        if "dependencies" in error.lower() or "not ready" in error.lower():
            return -0.10  # dependency_violation

        if "already completed" in error or "already in_progress" in error:
            return -0.05  # redundant_action

        if "capacity" in error.lower():
            return -0.15  # capacity_violation

        if "permanent" in error.lower():
            return -0.06  # permanent_retry

        return -0.05  # generic invalid action penalty

    def _check_sla_penalties(self, dag: DAGExecutor, step: int) -> float:
        """Check for SLA milestone violations and return penalty."""
        penalty = 0.0
        for subtask_id, deadline_step in self._sla_milestones.items():
            if step > deadline_step:
                status = dag.get_subtask_status(subtask_id)
                if status != "completed":
                    penalty -= 0.05  # per step beyond deadline
        return penalty

    def _check_unrecovered_failures(
        self, dag: DAGExecutor, action: OrchestratorAction
    ) -> float:
        """Track failed subtasks and penalize if unrecovered for 2+ steps."""
        penalty = 0.0
        failed = dag.get_failed_subtasks()

        for sid in failed:
            if sid not in self._steps_since_failure:
                self._steps_since_failure[sid] = 0
            self._steps_since_failure[sid] += 1

            if self._steps_since_failure[sid] >= 2:
                penalty -= 0.08  # unrecovered_failure

        # If this action retries a failed subtask, reset its counter
        if action.action_type == "retry" and action.subtask_id:
            self._steps_since_failure.pop(action.subtask_id, None)

        # Clean up recovered failures
        for sid in list(self._steps_since_failure.keys()):
            if sid not in failed:
                del self._steps_since_failure[sid]

        return penalty
