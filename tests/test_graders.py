"""Tests for graders — helper functions and grader formulas."""

import pytest

from models import EpisodeLog, GradeResult
from server.graders import (
    both_findings_aggregated,
    compute_parallel_efficiency,
    count_completed_subtasks,
    count_invalid_actions,
    count_retries_on_permanent_failure,
    episode_completed,
    failure_recovered,
    fan_out_parallelism_detected,
    grade,
    grade_easy,
    grade_expert,
    grade_hard,
    grade_medium,
    monitoring_completed,
    zero_capacity_violations,
)


# ── Fixtures ──


def _make_log(task_id: str = "easy") -> EpisodeLog:
    return EpisodeLog(task_id=task_id)


def _add_completed(log: EpisodeLog, subtask_id: str, step: int, attempt: int = 0) -> None:
    log.append(step, "subtask_completed", {
        "subtask_id": subtask_id, "agent_name": "agent", "attempt_count": attempt,
    })


def _add_failed(log: EpisodeLog, subtask_id: str, step: int) -> None:
    log.append(step, "subtask_failed", {
        "subtask_id": subtask_id, "agent_name": "agent", "error": "failed",
    })


def _add_invalid(log: EpisodeLog, step: int, error: str = "generic", action_type: str = "delegate") -> None:
    log.append(step, "action_invalid", {
        "action_type": action_type, "error": error,
    })


def _add_parallelism(log: EpisodeLog, step: int, tasks: list[str]) -> None:
    log.append(step, "parallelism", {"concurrent_tasks": tasks})


def _add_action(log: EpisodeLog, step: int, action_type: str) -> None:
    log.append(step, "action_taken", {"action_type": action_type})


def _add_episode_end(log: EpisodeLog, step: int, all_completed: bool = True) -> None:
    log.append(step, "episode_end", {
        "all_completed": all_completed, "synthesized": all_completed, "total_reward": 1.0,
    })
    log.total_steps = step


# ── Helper function tests ──


class TestHelperFunctions:
    def test_count_completed_subtasks(self) -> None:
        log = _make_log()
        _add_completed(log, "t1", 1)
        _add_completed(log, "t2", 2)
        _add_completed(log, "t1", 3)  # duplicate
        assert count_completed_subtasks(log) == 2

    def test_count_invalid_actions(self) -> None:
        log = _make_log()
        _add_invalid(log, 1)
        _add_invalid(log, 2)
        assert count_invalid_actions(log) == 2

    def test_fan_out_detected(self) -> None:
        log = _make_log()
        _add_parallelism(log, 3, ["implement_frontend", "write_tests", "extra"])
        assert fan_out_parallelism_detected(log, ["implement_frontend", "write_tests"])

    def test_fan_out_not_detected(self) -> None:
        log = _make_log()
        _add_parallelism(log, 3, ["implement_frontend"])
        assert not fan_out_parallelism_detected(log, ["implement_frontend", "write_tests"])

    def test_failure_recovered_true(self) -> None:
        log = _make_log()
        _add_failed(log, "scan", 1)
        _add_completed(log, "scan", 3)
        assert failure_recovered(log, "scan")

    def test_failure_recovered_false(self) -> None:
        log = _make_log()
        _add_failed(log, "scan", 1)
        assert not failure_recovered(log, "scan")

    def test_count_retries_on_permanent_failure(self) -> None:
        log = _make_log()
        _add_invalid(log, 1, error="permanent failure: agent cannot do X", action_type="retry")
        _add_invalid(log, 2, error="generic error", action_type="retry")
        assert count_retries_on_permanent_failure(log) == 1

    def test_both_findings_aggregated(self) -> None:
        log = _make_log("hard")
        _add_completed(log, "enrich_logs", 3)
        _add_completed(log, "check_dashboards", 4)
        _add_completed(log, "root_cause_analysis", 6)
        assert both_findings_aggregated(log)

    def test_both_findings_not_aggregated_missing_one(self) -> None:
        log = _make_log("hard")
        _add_completed(log, "enrich_logs", 3)
        _add_completed(log, "root_cause_analysis", 6)
        assert not both_findings_aggregated(log)

    def test_monitoring_completed_true(self) -> None:
        log = _make_log("hard")
        _add_completed(log, "validate_fix", 8)
        _add_action(log, 9, "wait")
        _add_action(log, 10, "wait")
        _add_action(log, 11, "synthesize")
        assert monitoring_completed(log)

    def test_monitoring_completed_false(self) -> None:
        log = _make_log("hard")
        _add_completed(log, "validate_fix", 8)
        _add_action(log, 9, "wait")
        _add_action(log, 10, "synthesize")
        assert not monitoring_completed(log)

    def test_episode_completed_true(self) -> None:
        log = _make_log()
        _add_episode_end(log, 10, all_completed=True)
        assert episode_completed(log)

    def test_episode_completed_false(self) -> None:
        log = _make_log()
        _add_episode_end(log, 10, all_completed=False)
        assert not episode_completed(log)

    def test_zero_capacity_violations_true(self) -> None:
        log = _make_log()
        _add_invalid(log, 1, error="agent lacks capability")
        assert zero_capacity_violations(log)

    def test_zero_capacity_violations_false(self) -> None:
        log = _make_log()
        _add_invalid(log, 1, error="capacity limit exceeded")
        assert not zero_capacity_violations(log)


# ── Grader tests ──


class TestEasyGrader:
    def test_perfect_score(self) -> None:
        log = _make_log("easy")
        for i, sid in enumerate([
            "technical_design", "implement_backend", "implement_frontend",
            "write_tests", "run_tests", "review_and_merge",
        ]):
            _add_completed(log, sid, i + 1)
        _add_parallelism(log, 4, ["implement_frontend", "write_tests"])
        _add_episode_end(log, 12)
        result = grade_easy(log)
        assert result.score == pytest.approx(1.0, abs=0.01)

    def test_no_completion(self) -> None:
        log = _make_log("easy")
        log.total_steps = 15
        result = grade_easy(log)
        assert result.score == 0.0  # Direct grade_easy() call; clamping is in grade() dispatcher

    def test_partial_with_invalids(self) -> None:
        log = _make_log("easy")
        _add_completed(log, "technical_design", 1)
        _add_completed(log, "implement_backend", 3)
        _add_invalid(log, 2, "error1")
        _add_invalid(log, 4, "error2")
        log.total_steps = 10
        result = grade_easy(log)
        # 2/6 * 0.85 = 0.2833, no parallelism, no base, -0.10 penalty
        assert 0.0 < result.score < 0.5


class TestMediumGrader:
    def test_with_recovery(self) -> None:
        log = _make_log("medium")
        log.budget_total = 35.0
        log.budget_used = 20.0
        # Complete all 9 subtasks
        for i, sid in enumerate([
            "checkout_code", "run_linter", "run_unit_tests", "run_security_scan",
            "build_image", "push_registry", "deploy_staging",
            "run_smoke_tests", "deploy_production",
        ]):
            _add_completed(log, sid, i + 1)
        # Security scan failed first
        _add_failed(log, "run_security_scan", 2)
        _add_completed(log, "run_security_scan", 4)
        _add_parallelism(log, 2, ["run_linter", "run_unit_tests", "run_security_scan"])
        _add_episode_end(log, 12)
        log.time_remaining = 4
        result = grade_medium(log)
        # Should get good score: completion + parallelism + recovery + time + cost
        assert result.score > 0.7


class TestHardGrader:
    def test_sla_milestones_met(self) -> None:
        log = _make_log("hard")
        log.budget_total = 40.0
        log.budget_used = 30.0
        _add_completed(log, "root_cause_analysis", 9)  # before deadline 10
        _add_completed(log, "deploy_hotfix", 14)  # before deadline 16
        log.total_steps = 20
        result = grade_hard(log)
        assert result.breakdown["sla_compliance"] == pytest.approx(0.10, abs=0.01)


class TestGradeDispatcher:
    def test_dispatches_to_correct_grader(self) -> None:
        log = _make_log("easy")
        result = grade("easy", log)
        assert isinstance(result, GradeResult)

    def test_unknown_task_raises(self) -> None:
        log = _make_log("unknown")
        with pytest.raises(KeyError):
            grade("unknown", log)


# ── Degenerate policy tests ──
# Prove that graders are well-calibrated: doing nothing scores near 0,
# and known-good walkthroughs always outscore degenerate policies.


class TestDegeneratePolicies:
    """Verify that a do-nothing policy (all waits) scores near 0 on every task.

    This validates the activity gate mechanism: dimensions that reward "no harm"
    (error classification, capacity discipline, cost efficiency) scale with
    actual task completion, preventing free points for inaction.
    """

    @staticmethod
    def _run_do_nothing(task_id: str) -> GradeResult:
        """Run a do-nothing policy (all waits) and return grader result."""
        from server.environment import OrchestratorEnvironment, _episode_store
        from models import OrchestratorAction

        time_budgets = {"easy": 15, "medium": 16, "hard": 22, "expert": 25}
        env = OrchestratorEnvironment()
        env.reset(task_id=task_id)
        for _ in range(time_budgets[task_id]):
            env.step(OrchestratorAction(action_type="wait"))
        return grade(task_id, _episode_store[task_id])

    def test_do_nothing_easy_scores_zero(self) -> None:
        result = self._run_do_nothing("easy")
        assert result.score == 0.0001

    def test_do_nothing_medium_scores_near_zero(self) -> None:
        result = self._run_do_nothing("medium")
        assert result.score <= 0.05

    def test_do_nothing_hard_scores_near_zero(self) -> None:
        result = self._run_do_nothing("hard")
        assert result.score <= 0.05

    def test_do_nothing_expert_scores_near_zero(self) -> None:
        result = self._run_do_nothing("expert")
        assert result.score <= 0.05

    def test_known_good_easy_outscores_degenerate(self) -> None:
        """Known-good easy walkthrough must score higher than do-nothing."""
        from server.environment import OrchestratorEnvironment, _episode_store
        from models import OrchestratorAction

        degenerate = self._run_do_nothing("easy")

        # Run known-good easy walkthrough
        env = OrchestratorEnvironment()
        env.reset(task_id="easy")
        seq = [
            ("delegate", "technical_design", "tech_lead"),
            ("delegate", "implement_backend", "backend_dev"),
            ("delegate", "implement_frontend", "frontend_dev"),
            ("delegate", "write_tests", "qa_engineer"),
            ("delegate", "run_tests", "backend_dev"),
            ("delegate", "review_and_merge", "tech_lead"),
            ("synthesize", None, None),
        ]
        for action_type, sid, agent in seq:
            env.step(OrchestratorAction(
                action_type=action_type, subtask_id=sid, agent_name=agent,
            ))
        good = grade("easy", _episode_store["easy"])
        assert good.score > degenerate.score + 0.5

    def test_known_good_hard_outscores_degenerate(self) -> None:
        """Known-good hard walkthrough must score higher than do-nothing."""
        from server.environment import OrchestratorEnvironment, _episode_store
        from models import OrchestratorAction

        degenerate = self._run_do_nothing("hard")

        # Run known-good hard walkthrough (14 steps)
        env = OrchestratorEnvironment()
        env.reset(task_id="hard")
        steps = [
            ("delegate", "alert_triage", "triage_analyst"),
            ("delegate", "enrich_logs", "investigator_alpha"),
            ("delegate", "check_dashboards", "monitor"),
            ("retry", "enrich_logs", "investigator_beta"),
            ("delegate", "check_dependencies", "investigator_alpha"),
            ("delegate", "notify_stakeholders", "communicator"),
            ("delegate", "root_cause_analysis", "senior_engineer"),
            ("delegate", "deploy_hotfix", "deployer"),
            ("delegate", "update_status_page", "communicator"),
            ("delegate", "validate_fix", "senior_engineer"),
            ("delegate", "monitor_recovery", "monitor"),
            ("wait", None, None),
            ("wait", None, None),
            ("synthesize", None, None),
        ]
        for action_type, sid, agent in steps:
            env.step(OrchestratorAction(
                action_type=action_type, subtask_id=sid, agent_name=agent,
            ))
        good = grade("hard", _episode_store["hard"])
        assert good.score > degenerate.score + 0.5
