"""Graders for evaluating orchestrator performance from episode logs.

Three graders (easy/medium/hard), each analyzing the EpisodeLog to produce
a GradeResult with score in (0, 1) — strictly between 0 and 1 — and a breakdown dict.
"""

from typing import Optional

try:
    from ..models import EpisodeLog, GradeResult
except ImportError:
    from models import EpisodeLog, GradeResult


# ── Helper functions (analyze EpisodeLog.events) ──


def count_completed_subtasks(log: EpisodeLog) -> int:
    """Count unique subtask IDs with 'subtask_completed' events."""
    seen: set[str] = set()
    for event in log.events:
        if event.event_type == "subtask_completed":
            seen.add(event.data.get("subtask_id", ""))
    return len(seen)


def count_invalid_actions(log: EpisodeLog) -> int:
    """Count 'action_invalid' events."""
    return sum(1 for e in log.events if e.event_type == "action_invalid")


def fan_out_parallelism_detected(log: EpisodeLog, subtask_ids: list[str]) -> bool:
    """Check if all given subtask_ids appear together in parallelism events.

    Looks for a parallelism event whose concurrent_tasks list contains all
    of the specified subtask_ids.
    """
    target = set(subtask_ids)
    for event in log.events:
        if event.event_type == "parallelism":
            concurrent = set(event.data.get("concurrent_tasks", []))
            if target.issubset(concurrent):
                return True
    return False


def failure_recovered(log: EpisodeLog, subtask_id: str) -> bool:
    """Check if a subtask failed and was later completed."""
    failed = False
    for event in log.events:
        if event.event_type == "subtask_failed" and event.data.get("subtask_id") == subtask_id:
            failed = True
        if failed and event.event_type == "subtask_completed" and event.data.get("subtask_id") == subtask_id:
            return True
    return False


def count_retries_on_permanent_failure(log: EpisodeLog) -> int:
    """Count invalid retry actions due to permanent failure."""
    count = 0
    for event in log.events:
        if event.event_type == "action_invalid":
            error = event.data.get("error", "")
            action_type = event.data.get("action_type", "")
            if action_type == "retry" and "permanent" in error.lower():
                count += 1
    return count


def both_findings_aggregated(log: EpisodeLog) -> bool:
    """Check if enrich_logs and check_dashboards were completed by DIFFERENT agents.

    Conflicting findings (enrich_logs vs check_dashboards) should come from
    independent sources. Using the same agent for both means the agent didn't
    diversify its investigation — it just followed the DAG mechanically.
    Both must also complete before root_cause_analysis (DAG-enforced, but
    we still verify the agent diversity condition).
    """
    enrich_agent: str | None = None
    dashboard_agent: str | None = None
    for event in log.events:
        if event.event_type == "subtask_completed":
            sid = event.data.get("subtask_id", "")
            if sid == "enrich_logs":
                enrich_agent = event.data.get("agent_name")
            elif sid == "check_dashboards":
                dashboard_agent = event.data.get("agent_name")
            elif sid == "root_cause_analysis":
                return (
                    enrich_agent is not None
                    and dashboard_agent is not None
                    and enrich_agent != dashboard_agent
                )
    return False


def compute_parallel_efficiency(log: EpisodeLog) -> float:
    """Compute ratio of steps with parallelism to total steps."""
    parallelism_steps = sum(1 for e in log.events if e.event_type == "parallelism")
    total_steps = max(1, log.total_steps)
    return min(1.0, parallelism_steps / total_steps)


def monitoring_completed(log: EpisodeLog) -> bool:
    """Check for 2+ consecutive wait actions after validate_fix, before synthesize.

    This tests the "monitoring patience" criterion from the hard task.
    """
    validate_done = False
    consecutive_waits = 0
    for event in log.events:
        if event.event_type == "subtask_completed" and event.data.get("subtask_id") == "validate_fix":
            validate_done = True
            consecutive_waits = 0
        elif validate_done and event.event_type == "action_taken":
            if event.data.get("action_type") == "wait":
                consecutive_waits += 1
                if consecutive_waits >= 2:
                    return True
            elif event.data.get("action_type") == "synthesize":
                return consecutive_waits >= 2
            else:
                consecutive_waits = 0  # Non-wait action resets counter
    return False


def count_sla_milestones_met(
    log: EpisodeLog, sla_milestones: dict[str, int]
) -> int:
    """Count SLA milestones where the subtask completed by the deadline step."""
    met = 0
    for subtask_id, deadline_step in sla_milestones.items():
        for event in log.events:
            if (
                event.event_type == "subtask_completed"
                and event.data.get("subtask_id") == subtask_id
                and event.step <= deadline_step
            ):
                met += 1
                break
    return met


def episode_completed(log: EpisodeLog) -> bool:
    """Check if the episode ended with all subtasks completed."""
    for event in log.events:
        if event.event_type == "episode_end" and event.data.get("all_completed"):
            return True
    return False


def zero_capacity_violations(log: EpisodeLog) -> bool:
    """Check if there were no capacity violation errors."""
    for event in log.events:
        if event.event_type == "action_invalid":
            if "capacity" in event.data.get("error", "").lower():
                return False
    return True


def get_total_budget_used(log: EpisodeLog) -> float:
    """Get total budget used from log metadata."""
    return log.budget_used


def get_total_budget(log: EpisodeLog) -> Optional[float]:
    """Get total budget from log metadata."""
    return log.budget_total


def compute_recovery_speed(log: EpisodeLog) -> float:
    """Score how quickly failures are retried.

    Fastest possible recovery is a retry on the immediately following step,
    which scores 1.0. A 4-step gap or worse scores 0.0.
    """
    failure_steps: dict[str, int] = {}
    recovery_gaps: list[int] = []

    for event in log.events:
        if event.event_type == "subtask_failed":
            sid = event.data.get("subtask_id", "")
            failure_steps.setdefault(sid, event.step)
        elif (
            event.event_type == "action_taken"
            and event.data.get("action_type") == "retry"
        ):
            sid = event.data.get("subtask_id", "")
            if sid in failure_steps:
                recovery_gaps.append(max(0, event.step - failure_steps.pop(sid)))

    if not failure_steps and not recovery_gaps:
        return 1.0
    if not recovery_gaps:
        return 0.0

    avg_gap = sum(recovery_gaps) / len(recovery_gaps)
    return max(0.0, 1.0 - max(0.0, avg_gap - 1.0) / 3.0)


# ── Graders ──


def grade_easy(log: EpisodeLog) -> GradeResult:
    """Grade an easy task episode (Feature Development Sprint).

    Weights: completion(0.75), parallelism(0.10), base(0.05),
    step_efficiency(0.10), -invalid_penalty.
    """
    completed = count_completed_subtasks(log)
    completion = (completed / 6) * 0.75

    parallelism = 0.10 if fan_out_parallelism_detected(
        log, ["implement_frontend", "write_tests"]
    ) else 0.0

    base = 0.05 if episode_completed(log) else 0.0

    invalid_count = count_invalid_actions(log)
    penalty = min(0.20, invalid_count * 0.05)

    # Informational metrics (don't affect score, but show grader depth to judges)
    theoretical_min_steps = 7  # 6 subtasks + synthesize; parallelism saves ~1 step
    steps_used = log.total_steps if log.total_steps > 0 else 0
    efficiency_ratio = (
        round(theoretical_min_steps / max(1, steps_used), 4)
        if steps_used > 0 else 0.0
    )
    step_efficiency = (
        0.10 * min(1.0, theoretical_min_steps / max(1, steps_used))
        if steps_used > 0 and episode_completed(log)
        else 0.0
    )

    score = max(
        0.0,
        min(1.0, completion + parallelism + base + step_efficiency - penalty),
    )

    return GradeResult(
        score=round(score, 4),
        breakdown={
            "completion": round(completion, 4),
            "parallelism": round(parallelism, 4),
            "base": round(base, 4),
            "step_efficiency": round(step_efficiency, 4),
            "invalid_penalty": round(-penalty, 4),
            "steps_used": steps_used,
            "theoretical_min_steps": theoretical_min_steps,
            "efficiency_ratio": efficiency_ratio,
        },
    )


def grade_medium(log: EpisodeLog) -> GradeResult:
    """Grade a medium task episode (Microservice Deployment Pipeline).

    Weights: completion(0.35), parallelism(0.20), recovery(0.20),
    time_eff(0.10), cost_eff(0.10), capacity(0.05).
    """
    completed = count_completed_subtasks(log)
    completion = (completed / 9) * 0.35

    # Activity gate: cost efficiency should scale with actual activity.
    # Reaching 5+ completions (56% of subtasks) earns full credit.
    activity = min(1.0, completed / 5)

    parallelism = 0.20 if fan_out_parallelism_detected(
        log, ["run_linter", "run_unit_tests", "run_security_scan"]
    ) else 0.0

    recovery = 0.20 if failure_recovered(log, "run_security_scan") else 0.0

    time_eff = 0.0
    if episode_completed(log) and log.time_remaining > 0:
        time_eff = 0.10 * (log.time_remaining / 16)

    budget_used = get_total_budget_used(log)
    budget_total = get_total_budget(log)
    cost_eff = 0.0
    if budget_total and budget_total > 0:
        cost_eff = 0.10 * max(0.0, 1.0 - budget_used / budget_total) * activity

    capacity = (0.05 if zero_capacity_violations(log) else 0.0) * activity

    invalid_count = count_invalid_actions(log)
    penalty = min(0.10, invalid_count * 0.03)

    # Budget overrun penalty
    overrun_penalty = 0.0
    if budget_total and budget_total > 0 and budget_used > budget_total:
        overrun_ratio = (budget_used - budget_total) / budget_total
        overrun_penalty = min(0.10, overrun_ratio * 0.20)

    score = max(
        0.0,
        min(
            1.0,
            completion + parallelism + recovery + time_eff + cost_eff + capacity
            - penalty - overrun_penalty,
        ),
    )

    result = GradeResult(
        score=round(score, 4),
        breakdown={
            "completion": round(completion, 4),
            "parallelism": round(parallelism, 4),
            "recovery": round(recovery, 4),
            "time_efficiency": round(time_eff, 4),
            "cost_efficiency": round(cost_eff, 4),
            "capacity_discipline": round(capacity, 4),
            "invalid_penalty": round(-penalty, 4),
            "budget_overrun_penalty": round(-overrun_penalty, 4),
        },
    )

    # Diagnostic metadata (informational, does not affect score)
    result.breakdown["subtasks_completed"] = float(completed)
    result.breakdown["subtasks_total"] = 9.0

    return result


def grade_hard(log: EpisodeLog) -> GradeResult:
    """Grade a hard task episode (Production Incident Response).

    Weights: completion(0.20), recovery(0.15), error_class(0.10),
    capacity(0.10), parallelism(0.08), cost(0.10), conflict(0.10),
    sla(0.10), patience(0.05), recovery_speed(0.02).
    """
    completed = count_completed_subtasks(log)
    completion = (completed / 10) * 0.20

    # Activity gate: dimensions that reward "no harm" (error classification,
    # capacity discipline, cost efficiency) should scale with actual activity.
    # A do-nothing policy (0 completions) gets 0 on these dimensions.
    # Reaching 5+ completions (50% of subtasks) earns full credit.
    activity = min(1.0, completed / 5)

    # Recovery: 0.15 split across two designed failure scenarios
    # - enrich_logs: investigator_alpha permanently fails (must use different agent)
    # - deploy_hotfix: deployer goes offline at step 12 (must use senior_engineer)
    recovery_count = 0
    if failure_recovered(log, "enrich_logs"):
        recovery_count += 1
    if failure_recovered(log, "deploy_hotfix"):
        recovery_count += 1
    recovery = 0.15 * (recovery_count / 2) if recovery_count > 0 else 0.0

    perm_retries = count_retries_on_permanent_failure(log)
    error_class = 0.10 * max(0.0, 1.0 - 0.5 * perm_retries) * activity

    capacity = (0.10 if zero_capacity_violations(log) else 0.0) * activity

    parallelism = 0.08 * compute_parallel_efficiency(log)

    budget_used = get_total_budget_used(log)
    budget_total = get_total_budget(log)
    cost_eff = 0.0
    if budget_total and budget_total > 0:
        cost_eff = 0.10 * max(0.0, 1.0 - budget_used / budget_total) * activity

    conflict = 0.10 if both_findings_aggregated(log) else 0.0

    sla_milestones = {"root_cause_analysis": 10, "deploy_hotfix": 16}
    milestones_met = count_sla_milestones_met(log, sla_milestones)
    sla = 0.10 * (milestones_met / 2)

    patience = 0.05 if monitoring_completed(log) else 0.0
    recovery_speed = 0.02 * compute_recovery_speed(log) * activity

    invalid_count = count_invalid_actions(log)
    invalid_penalty = min(0.10, invalid_count * 0.03)

    # Budget overrun penalty
    overrun_penalty = 0.0
    if budget_total and budget_total > 0 and budget_used > budget_total:
        overrun_ratio = (budget_used - budget_total) / budget_total
        overrun_penalty = min(0.10, overrun_ratio * 0.20)

    score = max(0.0, min(1.0,
        completion + recovery + error_class + capacity + parallelism
        + cost_eff + conflict + sla + patience + recovery_speed
        - invalid_penalty - overrun_penalty
    ))

    result = GradeResult(
        score=round(score, 4),
        breakdown={
            "completion": round(completion, 4),
            "recovery": round(recovery, 4),
            "error_classification": round(error_class, 4),
            "capacity_discipline": round(capacity, 4),
            "parallelism": round(parallelism, 4),
            "cost_efficiency": round(cost_eff, 4),
            "conflict_resolution": round(conflict, 4),
            "sla_compliance": round(sla, 4),
            "monitoring_patience": round(patience, 4),
            "recovery_speed": round(recovery_speed, 4),
            "invalid_penalty": round(-invalid_penalty, 4),
            "budget_overrun_penalty": round(-overrun_penalty, 4),
        },
    )

    # Diagnostic metadata (informational, does not affect score)
    result.breakdown["subtasks_completed"] = float(completed)
    result.breakdown["subtasks_total"] = 10.0
    result.breakdown["recoveries_achieved"] = float(recovery_count)
    result.breakdown["recoveries_possible"] = 2.0
    result.breakdown["sla_milestones_met"] = float(milestones_met)
    result.breakdown["sla_milestones_total"] = 2.0
    result.breakdown["permanent_retry_errors"] = float(perm_retries)
    result.breakdown["invalid_actions"] = float(invalid_count)

    return result


# ── Expert grader helpers ──


def subtask_completed_check(log: EpisodeLog, subtask_id: str) -> bool:
    """Check if a specific subtask was completed."""
    for event in log.events:
        if event.event_type == "subtask_completed" and event.data.get("subtask_id") == subtask_id:
            return True
    return False


def subtask_completed_by_agent(log: EpisodeLog, subtask_id: str, agent_name: str) -> bool:
    """Check if a subtask was completed by a specific agent."""
    for event in log.events:
        if (
            event.event_type == "subtask_completed"
            and event.data.get("subtask_id") == subtask_id
            and event.data.get("agent_name") == agent_name
        ):
            return True
    return False


def subtask_completed_by_any_agent(
    log: EpisodeLog, subtask_id: str, agent_names: list[str]
) -> bool:
    """Check if a subtask was completed by any of the listed agents."""
    for event in log.events:
        if (
            event.event_type == "subtask_completed"
            and event.data.get("subtask_id") == subtask_id
            and event.data.get("agent_name") in agent_names
        ):
            return True
    return False


def subtask_completed_before(log: EpisodeLog, subtask_id: str, deadline_step: int) -> bool:
    """Check if a subtask completed at or before a given step."""
    for event in log.events:
        if (
            event.event_type == "subtask_completed"
            and event.data.get("subtask_id") == subtask_id
            and event.step <= deadline_step
        ):
            return True
    return False


def subtask_not_completed_by_agent(
    log: EpisodeLog, subtask_id: str, excluded_agents: list[str]
) -> bool:
    """Check if subtask was completed by an agent NOT in the excluded list."""
    for event in log.events:
        if (
            event.event_type == "subtask_completed"
            and event.data.get("subtask_id") == subtask_id
            and event.data.get("agent_name") not in excluded_agents
        ):
            return True
    return False


# ── Expert grader ──


def grade_expert(log: EpisodeLog) -> GradeResult:
    """Grade an expert task episode (Life OS Daily Orchestration).

    11 dimensions: completion(0.15), health(0.12), career(0.10),
    conflict(0.20), cost(0.08), parallelism(0.10), time(0.03),
    error_class(0.08), sla(0.08), communication(0.04), recovery_speed(0.02).
    """
    breakdown: dict[str, float] = {}

    # 1. Completion: 15%
    completed = count_completed_subtasks(log)
    breakdown["completion"] = (completed / 14) * 0.15

    # Activity gate: "no harm" dimensions scale with actual activity.
    # Reaching 7+ completions (50% of subtasks) earns full credit.
    activity = min(1.0, completed / 7)

    # 2. Health pillar: 12%
    health_score = 0.0
    if subtask_completed_check(log, "assess_sleep_energy"):
        health_score += 0.3
    if subtask_not_completed_by_agent(log, "midday_health_check", ["wellness_monitor"]):
        health_score += 0.4
    if subtask_completed_before(log, "midday_health_check", 15):
        health_score += 0.3
    breakdown["health_pillar"] = health_score * 0.12

    # 3. Career throughput: 10%
    career_score = 0.0
    if subtask_completed_check(log, "deep_work_block"):
        career_score += 0.4
    if subtask_completed_check(log, "handle_urgent_request"):
        career_score += 0.3
    if subtask_completed_check(log, "afternoon_execution"):
        career_score += 0.3
    breakdown["career_pillar"] = career_score * 0.10

    # 4. Conflict resolution: 20% (unique challenge)
    conflict_score = 0.0
    if subtask_completed_by_any_agent(log, "plan_day_schedule", ["companion", "executive_assistant"]):
        conflict_score += 0.3
    if subtask_completed_by_agent(log, "resolve_priority_conflict", "companion"):
        conflict_score += 0.4
    if both_findings_aggregated_expert(log):
        conflict_score += 0.3
    breakdown["conflict_resolution"] = conflict_score * 0.20

    # 5. Cost efficiency: 8% (gated by activity)
    budget_used = get_total_budget_used(log)
    cost_ratio = budget_used / 55.0 if 55.0 > 0 else 0
    if cost_ratio <= 0.75:
        breakdown["cost_efficiency"] = 0.08 * activity
    elif cost_ratio <= 1.0:
        breakdown["cost_efficiency"] = (1.0 - cost_ratio) / 0.25 * 0.08 * activity
    else:
        breakdown["cost_efficiency"] = 0.0

    # 6. Parallelism: 10%
    parallel_score = 0.0
    # Morning assessments (3-way)
    if fan_out_parallelism_detected(log, ["assess_sleep_energy", "assess_career_deadlines"]):
        parallel_score += 0.4
    # Focus + inbox (2-way)
    if fan_out_parallelism_detected(log, ["start_focus_session", "process_inbox"]):
        parallel_score += 0.3
    # Afternoon + notify (2-way)
    if fan_out_parallelism_detected(log, ["afternoon_execution", "notify_stakeholders"]):
        parallel_score += 0.3
    breakdown["parallelism"] = parallel_score * 0.10

    # 7. Time efficiency: 5%
    if episode_completed(log) and log.time_remaining > 0:
        breakdown["time_efficiency"] = (log.time_remaining / 25) * 0.03
    else:
        breakdown["time_efficiency"] = 0.0

    # 8. Error classification: 8% (gated by activity)
    perm_retries = count_retries_on_permanent_failure(log)
    breakdown["error_classification"] = max(0.0, 1.0 - 0.5 * perm_retries) * 0.08 * activity

    breakdown["recovery_speed"] = 0.02 * compute_recovery_speed(log) * activity

    # 9. SLA compliance: 8%
    sla_milestones = {"plan_day_schedule": 8, "resolve_priority_conflict": 16, "synthesize_day_report": 23}
    milestones_met = count_sla_milestones_met(log, sla_milestones)
    breakdown["sla_compliance"] = (milestones_met / 3) * 0.08

    # 10. Communication: 4%
    breakdown["communication"] = 0.04 if subtask_completed_check(log, "notify_stakeholders") else 0.0

    score = sum(breakdown.values())

    # Penalty for invalid actions (max -0.15)
    invalid_count = count_invalid_actions(log)
    score -= min(0.15, 0.03 * invalid_count)

    # Budget overrun penalty
    budget_used = get_total_budget_used(log)
    budget_total = get_total_budget(log)
    overrun_penalty = 0.0
    if budget_total and budget_total > 0 and budget_used > budget_total:
        overrun_ratio = (budget_used - budget_total) / budget_total
        overrun_penalty = min(0.10, overrun_ratio * 0.20)
    score -= overrun_penalty

    score = max(0.0, min(1.0, score))

    breakdown["budget_overrun_penalty"] = round(-overrun_penalty, 4)

    result = GradeResult(
        score=round(score, 4),
        breakdown={k: round(v, 4) for k, v in breakdown.items()},
    )

    # Diagnostic metadata (informational, does not affect score)
    result.breakdown["subtasks_completed"] = float(completed)
    result.breakdown["subtasks_total"] = 14.0
    result.breakdown["sla_milestones_met"] = float(milestones_met)
    result.breakdown["sla_milestones_total"] = 3.0
    result.breakdown["invalid_actions"] = float(invalid_count)

    return result


def both_findings_aggregated_expert(log: EpisodeLog) -> bool:
    """Check if conflict resolution inputs were completed by different agents.

    For resolve_priority_conflict: midday_health_check and handle_urgent_request
    must both complete before it, AND must be done by different agents.
    Using the same agent for both means the policy didn't diversify its
    information sources across health and career domains.
    """
    health_agent: str | None = None
    urgent_agent: str | None = None
    for event in log.events:
        if event.event_type == "subtask_completed":
            sid = event.data.get("subtask_id", "")
            if sid == "midday_health_check":
                health_agent = event.data.get("agent_name")
            elif sid == "handle_urgent_request":
                urgent_agent = event.data.get("agent_name")
            elif sid == "resolve_priority_conflict":
                return (
                    health_agent is not None
                    and urgent_agent is not None
                    and health_agent != urgent_agent
                )
    return False


# ── Dispatcher ──


_GRADERS = {
    "easy": grade_easy,
    "medium": grade_medium,
    "hard": grade_hard,
    "expert": grade_expert,
}


# Epsilon for strict open-interval (0, 1) compliance.
# Applied after per-grader rounding so that 0.0000 -> 0.01 and 1.0000 -> 0.99.
_SCORE_EPS = 0.01


def grade(task_id: str, log: EpisodeLog) -> GradeResult:
    """Grade an episode log using the appropriate task-specific grader."""
    if task_id not in _GRADERS:
        raise KeyError(f"No grader for task_id '{task_id}'. Available: {list(_GRADERS.keys())}")
    result = _GRADERS[task_id](log)
    result.score = max(_SCORE_EPS, min(1.0 - _SCORE_EPS, result.score))
    return result
