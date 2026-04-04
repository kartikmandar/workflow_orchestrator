"""Graders for evaluating orchestrator performance from episode logs.

Three graders (easy/medium/hard), each analyzing the EpisodeLog to produce
a GradeResult with score in [0.0, 1.0] and a breakdown dict.
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
    """Check if both enrich_logs and check_dashboards completed before root_cause_analysis.

    This indicates the agent properly gathered conflicting findings before
    synthesizing the root cause.
    """
    enrich_done = False
    dashboards_done = False
    for event in log.events:
        if event.event_type == "subtask_completed":
            sid = event.data.get("subtask_id", "")
            if sid == "enrich_logs":
                enrich_done = True
            elif sid == "check_dashboards":
                dashboards_done = True
            elif sid == "root_cause_analysis":
                return enrich_done and dashboards_done
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


# ── Graders ──


def grade_easy(log: EpisodeLog) -> GradeResult:
    """Grade an easy task episode (Feature Development Sprint).

    Weights: completion(0.85), parallelism(0.10), base(0.05), -invalid_penalty.
    """
    completed = count_completed_subtasks(log)
    completion = (completed / 6) * 0.85

    parallelism = 0.10 if fan_out_parallelism_detected(
        log, ["implement_frontend", "write_tests"]
    ) else 0.0

    base = 0.05 if episode_completed(log) else 0.0

    invalid_count = count_invalid_actions(log)
    penalty = min(0.20, invalid_count * 0.05)

    score = max(0.0, min(1.0, completion + parallelism + base - penalty))

    return GradeResult(
        score=round(score, 4),
        breakdown={
            "completion": round(completion, 4),
            "parallelism": round(parallelism, 4),
            "base": round(base, 4),
            "invalid_penalty": round(-penalty, 4),
        },
    )


def grade_medium(log: EpisodeLog) -> GradeResult:
    """Grade a medium task episode (Microservice Deployment Pipeline).

    Weights: completion(0.40), parallelism(0.20), recovery(0.20),
    time_eff(0.10), cost_eff(0.10).
    """
    completed = count_completed_subtasks(log)
    completion = (completed / 9) * 0.40

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
        cost_eff = 0.10 * max(0.0, 1.0 - budget_used / budget_total)

    score = max(0.0, min(1.0, completion + parallelism + recovery + time_eff + cost_eff))

    return GradeResult(
        score=round(score, 4),
        breakdown={
            "completion": round(completion, 4),
            "parallelism": round(parallelism, 4),
            "recovery": round(recovery, 4),
            "time_efficiency": round(time_eff, 4),
            "cost_efficiency": round(cost_eff, 4),
        },
    )


def grade_hard(log: EpisodeLog) -> GradeResult:
    """Grade a hard task episode (Production Incident Response).

    Weights: completion(0.20), recovery(0.15), error_class(0.10),
    capacity(0.10), parallelism(0.10), cost(0.10), conflict(0.10),
    sla(0.10), patience(0.05).
    """
    completed = count_completed_subtasks(log)
    completion = (completed / 10) * 0.20

    recovery = 0.15 if failure_recovered(log, "enrich_logs") else 0.0

    perm_retries = count_retries_on_permanent_failure(log)
    error_class = 0.10 * max(0.0, 1.0 - 0.5 * perm_retries)

    capacity = 0.10 if zero_capacity_violations(log) else 0.0

    parallelism = 0.10 * compute_parallel_efficiency(log)

    budget_used = get_total_budget_used(log)
    budget_total = get_total_budget(log)
    cost_eff = 0.0
    if budget_total and budget_total > 0:
        cost_eff = 0.10 * max(0.0, 1.0 - budget_used / budget_total)

    conflict = 0.10 if both_findings_aggregated(log) else 0.0

    sla_milestones = {"root_cause_analysis": 10, "deploy_hotfix": 16}
    milestones_met = count_sla_milestones_met(log, sla_milestones)
    sla = 0.10 * (milestones_met / 2)

    patience = 0.05 if monitoring_completed(log) else 0.0

    score = max(0.0, min(1.0,
        completion + recovery + error_class + capacity + parallelism
        + cost_eff + conflict + sla + patience
    ))

    return GradeResult(
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
        },
    )


# ── Dispatcher ──


_GRADERS = {
    "easy": grade_easy,
    "medium": grade_medium,
    "hard": grade_hard,
}


def grade(task_id: str, log: EpisodeLog) -> GradeResult:
    """Grade an episode log using the appropriate task-specific grader."""
    if task_id not in _GRADERS:
        raise KeyError(f"No grader for task_id '{task_id}'. Available: {list(_GRADERS.keys())}")
    return _GRADERS[task_id](log)
