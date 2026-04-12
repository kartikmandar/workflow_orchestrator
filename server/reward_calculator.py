"""Dense per-step reward calculation and end-of-episode bonuses.

7 positive signals, 9 negative signals, SLA penalties, and end-of-episode bonuses.

Design note: Per-step rewards are RL training signals — they reward/penalize
individual decisions to shape behavior. Grader scores (in graders.py) are
episode-level evaluation metrics — they assess the overall trajectory outcome.
These intentionally diverge: rewards encourage action discovery (e.g., +0.10 per
parallelism event), while graders evaluate efficiency (e.g., parallelism ratio =
events / total_steps). This separation ensures dense per-step learning signal
without distorting the final evaluation metric.
"""

from typing import Any

from models import EpisodeLog, OrchestratorAction

from .agent_pool import AgentPool
from .dag_executor import DAGExecutor
from .task_registry import TaskConfig


class RewardCalculator:
    """Computes step rewards and end-of-episode bonuses for the orchestrator."""

    # ── Positive signals ──
    CORRECT_DELEGATION: float = 0.05
    COMMUNICATION_SENT: float = 0.05
    COST_EFFICIENT_CHOICE: float = 0.04
    CORRECT_RETRY: float = 0.05
    EFFICIENT_WAIT: float = 0.03
    SUBTASK_COMPLETED: float = 0.08
    FAILURE_RECOVERED: float = 0.10
    PARALLELISM_EXPLOITED: float = 0.10

    # ── Negative signals ──
    WASTEFUL_ASSIGNMENT: float = -0.04
    UNNECESSARY_WAIT: float = -0.03
    ABORT_PENALTY: float = -0.03
    WRONG_AGENT: float = -0.05
    DEPENDENCY_VIOLATION: float = -0.10
    REDUNDANT_ACTION: float = -0.05
    CAPACITY_VIOLATION: float = -0.15
    PERMANENT_RETRY: float = -0.06
    GENERIC_INVALID: float = -0.05
    UNRECOVERED_FAILURE: float = -0.08

    # ── SLA penalties ──
    SLA_PER_STEP: float = 0.05
    SLA_MAX_PENALTY_PER_MILESTONE: float = 0.15

    # ── End-of-episode ──
    ALL_COMPLETE_BONUS: float = 0.20
    TIME_EFFICIENCY_WEIGHT: float = 0.10
    COST_EFFICIENCY_WEIGHT: float = 0.05
    INCOMPLETE_PENALTY: float = -0.10

    def __init__(self, task_config: TaskConfig) -> None:
        self._config = task_config
        self._sla_milestones = task_config.sla_milestones or {}
        self._cost_budget = task_config.constraints.get("cost_budget")
        self._communication_subtasks = task_config.communication_subtasks
        self._steps_since_failure: dict[str, int] = {}
        self._sla_penalty_accrued: dict[str, float] = {}
        self._last_breakdown: dict[str, float] = {}

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
        breakdown: dict[str, float] = {}

        if not action_valid:
            invalid_penalty = self._penalty_for_invalid_action(action, action_error)
            self._add_breakdown_component(
                breakdown,
                self._breakdown_key_for_invalid_action(action_error),
                invalid_penalty,
            )
            reward += invalid_penalty

            sla_penalty = self._check_sla_penalties(dag, step)
            if sla_penalty != 0.0:
                self._add_breakdown_component(breakdown, "sla_penalty", sla_penalty)
            reward += sla_penalty

            unrecovered_penalty = self._check_unrecovered_failures(dag, action)
            if unrecovered_penalty != 0.0:
                self._add_breakdown_component(
                    breakdown, "unrecovered_failure", unrecovered_penalty
                )
            reward += unrecovered_penalty
            self._last_breakdown = breakdown
            return reward

        action_type = action.action_type

        # ── Positive signals ──

        if action_type == "delegate":
            reward += self.CORRECT_DELEGATION
            self._add_breakdown_component(
                breakdown, "delegation", self.CORRECT_DELEGATION
            )

            if action.subtask_id in self._communication_subtasks:
                reward += self.COMMUNICATION_SENT
                self._add_breakdown_component(
                    breakdown, "communication", self.COMMUNICATION_SENT
                )

            # Cost-efficient choice: cheaper agent chosen when others available
            if self._cost_budget is not None and action.subtask_id and action.agent_name:
                subtask_type = dag.get_subtask_type(action.subtask_id)
                capable = agent_pool.get_capable_agents(subtask_type)
                if len(capable) > 1:
                    chosen_cost = agent_pool.get_agent_cost(action.agent_name)
                    min_cost = min(agent_pool.get_agent_cost(a) for a in capable)
                    if chosen_cost <= min_cost:
                        reward += self.COST_EFFICIENT_CHOICE
                        self._add_breakdown_component(
                            breakdown,
                            "cost_efficient_choice",
                            self.COST_EFFICIENT_CHOICE,
                        )
                    elif chosen_cost > min_cost:
                        reward += self.WASTEFUL_ASSIGNMENT
                        self._add_breakdown_component(
                            breakdown,
                            "wasteful_assignment",
                            self.WASTEFUL_ASSIGNMENT,
                        )

        elif action_type == "retry":
            reward += self.CORRECT_RETRY
            self._add_breakdown_component(breakdown, "retry", self.CORRECT_RETRY)

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
                reward += self.UNNECESSARY_WAIT
                self._add_breakdown_component(
                    breakdown, "unnecessary_wait", self.UNNECESSARY_WAIT
                )
            else:
                reward += self.EFFICIENT_WAIT
                self._add_breakdown_component(
                    breakdown, "efficient_wait", self.EFFICIENT_WAIT
                )

        elif action_type == "abort":
            reward += self.ABORT_PENALTY
            self._add_breakdown_component(breakdown, "abort", self.ABORT_PENALTY)

        # ── Events this step ──

        for event in events_this_step:
            et = event.get("event_type")
            if et == "subtask_completed":
                reward += self.SUBTASK_COMPLETED
                self._add_breakdown_component(
                    breakdown, "subtask_completed", self.SUBTASK_COMPLETED
                )

                subtask_id = event.get("subtask_id", "")
                attempt = dag.get_subtask_attempt_count(subtask_id)
                if attempt > 0:
                    reward += self.FAILURE_RECOVERED
                    self._add_breakdown_component(
                        breakdown, "failure_recovered", self.FAILURE_RECOVERED
                    )

            elif et in {"parallelism", "parallelism_reward"}:
                reward += self.PARALLELISM_EXPLOITED
                self._add_breakdown_component(
                    breakdown, "parallelism", self.PARALLELISM_EXPLOITED
                )

        # ── SLA penalties ──
        sla_penalty = self._check_sla_penalties(dag, step)
        if sla_penalty != 0.0:
            self._add_breakdown_component(breakdown, "sla_penalty", sla_penalty)
        reward += sla_penalty

        # ── Unrecovered failure check ──
        unrecovered_penalty = self._check_unrecovered_failures(dag, action)
        if unrecovered_penalty != 0.0:
            self._add_breakdown_component(
                breakdown, "unrecovered_failure", unrecovered_penalty
            )
        reward += unrecovered_penalty
        self._last_breakdown = breakdown

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
            bonus += self.ALL_COMPLETE_BONUS

            if time_budget > 0:
                bonus += self.TIME_EFFICIENCY_WEIGHT * (time_remaining / time_budget)

            if self._cost_budget is not None and self._cost_budget > 0:
                cost_ratio = agent_pool.get_budget_used() / self._cost_budget
                bonus += self.COST_EFFICIENCY_WEIGHT * max(0.0, 1.0 - cost_ratio)
        else:
            bonus += self.INCOMPLETE_PENALTY

        return bonus

    # ── Private helpers ──

    def _penalty_for_invalid_action(
        self, action: OrchestratorAction, error: str | None
    ) -> float:
        """Determine the penalty for an invalid action based on error type."""
        error = error or ""

        if "lacks capability" in error or "lacks required tooling" in error:
            return self.WRONG_AGENT

        if "dependencies" in error.lower() or "not ready" in error.lower():
            return self.DEPENDENCY_VIOLATION

        if "already completed" in error or "already in_progress" in error:
            return self.REDUNDANT_ACTION

        if "capacity" in error.lower():
            return self.CAPACITY_VIOLATION

        if "permanent" in error.lower():
            return self.PERMANENT_RETRY

        return self.GENERIC_INVALID

    @property
    def last_breakdown(self) -> dict[str, float]:
        """Return the most recent raw step reward breakdown."""
        return dict(self._last_breakdown)

    def _add_breakdown_component(
        self, breakdown: dict[str, float], key: str, value: float
    ) -> None:
        """Accumulate a raw reward component for the current step."""
        breakdown[key] = breakdown.get(key, 0.0) + value

    def _breakdown_key_for_invalid_action(self, error: str | None) -> str:
        """Map an invalid action error to a stable breakdown key."""
        error = (error or "").lower()

        if "lacks capability" in error or "lacks required tooling" in error:
            return "wrong_agent"
        if "dependencies" in error or "not ready" in error:
            return "dependency_violation"
        if "already completed" in error or "already in_progress" in error:
            return "redundant_action"
        if "capacity" in error:
            return "capacity_violation"
        if "permanent" in error:
            return "permanent_retry"
        return "invalid_action"

    def _check_sla_penalties(self, dag: DAGExecutor, step: int) -> float:
        """Check for SLA milestone violations and return penalty.

        Applies -0.05 per step past deadline, capped at SLA_MAX_PENALTY_PER_MILESTONE
        per milestone. This prevents runaway penalties that dwarf other signals.
        """
        penalty = 0.0
        for subtask_id, deadline_step in self._sla_milestones.items():
            if step > deadline_step:
                status = dag.get_subtask_status(subtask_id)
                if status != "completed":
                    accrued = self._sla_penalty_accrued.get(subtask_id, 0.0)
                    if accrued < self.SLA_MAX_PENALTY_PER_MILESTONE:
                        step_penalty = min(
                            self.SLA_PER_STEP,
                            self.SLA_MAX_PENALTY_PER_MILESTONE - accrued,
                        )
                        penalty -= step_penalty
                        self._sla_penalty_accrued[subtask_id] = accrued + step_penalty
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
                penalty += self.UNRECOVERED_FAILURE

        # If this action retries a failed subtask, reset its counter
        if action.action_type == "retry" and action.subtask_id:
            self._steps_since_failure.pop(action.subtask_id, None)

        # Clean up recovered failures
        for sid in list(self._steps_since_failure.keys()):
            if sid not in failed:
                del self._steps_since_failure[sid]

        return penalty
