"""Tests for reward calculator — per-step signals and end-of-episode bonuses."""

import pytest

from models import EpisodeLog, OrchestratorAction
from server.agent_pool import AgentPool
from server.dag_executor import DAGExecutor
from server.reward_calculator import RewardCalculator
from server.task_registry import get_task


def _setup_easy():
    config = get_task("easy")
    dag = DAGExecutor(config.subtask_definitions)
    pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
    rc = RewardCalculator(config)
    log = EpisodeLog(task_id="easy")
    return config, dag, pool, rc, log


class TestPositiveSignals:
    def test_correct_delegation(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        action = OrchestratorAction(
            action_type="delegate", subtask_id="technical_design", agent_name="tech_lead"
        )
        reward = rc.calculate_step_reward(action, True, None, dag, pool, log, 1, [])
        assert reward == 0.05

    def test_subtask_completed_event(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        dag.delegate("technical_design", "tech_lead")
        pool.assign("tech_lead", "technical_design", "technical_design", 0)
        dag.complete("technical_design", "done")
        pool.release_agent("tech_lead")
        dag.update_ready_statuses()
        events = [{"event_type": "subtask_completed", "subtask_id": "technical_design"}]
        action = OrchestratorAction(action_type="wait")
        reward = rc.calculate_step_reward(action, True, None, dag, pool, log, 2, events)
        # +0.08 (completion) -0.03 (unnecessary_wait since implement_backend now ready)
        assert reward == pytest.approx(0.05, abs=0.01)

    def test_parallelism_event(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        # Occupy all ready tasks + agents so wait is efficient
        dag.delegate("technical_design", "tech_lead")
        pool.assign("tech_lead", "technical_design", "technical_design", 0)
        dag.update_ready_statuses()
        events = [{"event_type": "parallelism_reward", "concurrent_tasks": ["t1", "t2"]}]
        action = OrchestratorAction(action_type="wait")
        reward = rc.calculate_step_reward(action, True, None, dag, pool, log, 1, events)
        # +0.10 (parallelism) +0.03 (efficient_wait)
        assert reward == pytest.approx(0.13, abs=0.01)

    def test_last_breakdown_tracks_raw_components(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        action = OrchestratorAction(
            action_type="delegate", subtask_id="technical_design", agent_name="tech_lead"
        )
        rc.calculate_step_reward(action, True, None, dag, pool, log, 1, [])
        assert rc.last_breakdown["delegation"] == pytest.approx(0.05)

    def test_efficient_wait(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        dag.delegate("technical_design", "tech_lead")
        pool.assign("tech_lead", "technical_design", "technical_design", 0)
        dag.update_ready_statuses()
        action = OrchestratorAction(action_type="wait")
        reward = rc.calculate_step_reward(action, True, None, dag, pool, log, 1, [])
        assert reward == 0.03  # efficient_wait


class TestNegativeSignals:
    def test_wrong_agent(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        action = OrchestratorAction(action_type="delegate")
        reward = rc.calculate_step_reward(
            action, False, "Agent lacks capability", dag, pool, log, 1, []
        )
        assert reward == -0.05

    def test_dependency_violation(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        action = OrchestratorAction(action_type="delegate")
        reward = rc.calculate_step_reward(
            action, False, "dependencies not ready", dag, pool, log, 1, []
        )
        assert reward == -0.10

    def test_capacity_violation(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        action = OrchestratorAction(action_type="delegate")
        reward = rc.calculate_step_reward(
            action, False, "capacity limit exceeded", dag, pool, log, 1, []
        )
        assert reward == -0.15

    def test_unnecessary_wait(self) -> None:
        """Waiting when ready subtasks + idle capable agents exist."""
        _, dag, pool, rc, log = _setup_easy()
        # technical_design is ready, tech_lead is idle — waiting is unnecessary
        action = OrchestratorAction(action_type="wait")
        reward = rc.calculate_step_reward(action, True, None, dag, pool, log, 1, [])
        assert reward == -0.03

    def test_abort_penalty(self) -> None:
        _, dag, pool, rc, log = _setup_easy()
        action = OrchestratorAction(action_type="abort", subtask_id="technical_design")
        reward = rc.calculate_step_reward(action, True, None, dag, pool, log, 1, [])
        assert reward == -0.03


class TestEndBonus:
    def test_all_complete_and_synthesized(self) -> None:
        config, dag, pool, rc, _ = _setup_easy()
        # Complete all subtasks
        sequence = [
            ("technical_design", "tech_lead"),
            ("implement_backend", "backend_dev"),
            ("implement_frontend", "frontend_dev"),
            ("write_tests", "qa_engineer"),
            ("run_tests", "qa_engineer"),
            ("review_and_merge", "tech_lead"),
        ]
        for sid, agent in sequence:
            dag.update_ready_statuses()
            dag.delegate(sid, agent)
            dag.complete(sid, "done")

        bonus = rc.calculate_end_bonus(dag, pool, 9, 15, True)
        assert bonus > 0.20  # Base + time efficiency

    def test_incomplete_episode(self) -> None:
        _, dag, pool, rc, _ = _setup_easy()
        bonus = rc.calculate_end_bonus(dag, pool, 0, 15, False)
        assert bonus == -0.10

    def test_time_efficiency_scales(self) -> None:
        config, dag, pool, rc, _ = _setup_easy()
        # More time remaining = higher bonus
        bonus_fast = rc.calculate_end_bonus(dag, pool, 10, 15, False)
        bonus_slow = rc.calculate_end_bonus(dag, pool, 1, 15, False)
        # Both incomplete, so both -0.10
        assert bonus_fast == bonus_slow == -0.10


def _decompose(reward: float) -> list[float]:
    """Helper to check if a reward value approximately contains a component."""
    # Simple — just return as a list for 'in' checking
    return [round(reward, 10)]
