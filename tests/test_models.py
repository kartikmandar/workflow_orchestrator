"""Tests for Pydantic models — serialization, validation, extra field rejection."""

import pytest
from pydantic import ValidationError

from models import (
    AgentInfo,
    EpisodeEvent,
    EpisodeLog,
    GradeResult,
    OrchestratorAction,
    OrchestratorObservation,
    OrchestratorState,
    SubtaskInfo,
)


class TestSubtaskInfo:
    def test_valid_construction(self) -> None:
        st = SubtaskInfo(
            id="t1", type="build", status="ready",
            dependencies=["t0"], dependencies_met=True,
        )
        assert st.id == "t1"
        assert st.attempt_count == 0

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            SubtaskInfo(
                id="t1", type="build", status="unknown",
                dependencies=[], dependencies_met=False,
            )

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            SubtaskInfo(
                id="t1", type="build", status="pending",
                dependencies=[], dependencies_met=False, foo="bar",
            )


class TestAgentInfo:
    def test_valid_construction(self) -> None:
        a = AgentInfo(
            name="a1", capabilities=["build"], status="idle",
            reliability=0.9, speed=2, cost_per_step=3.0,
        )
        assert a.name == "a1"
        assert a.current_task is None

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            AgentInfo(
                name="a1", capabilities=[], status="sleeping",
                reliability=1.0, speed=1, cost_per_step=1.0,
            )


class TestOrchestratorAction:
    def test_valid_actions(self) -> None:
        for at in ["delegate", "retry", "wait", "synthesize", "abort"]:
            a = OrchestratorAction(action_type=at)
            assert a.action_type == at

    def test_rejects_invalid_action_type(self) -> None:
        with pytest.raises(ValidationError):
            OrchestratorAction(action_type="fly")

    def test_metadata_inherited(self) -> None:
        a = OrchestratorAction(action_type="wait", metadata={"key": "val"})
        assert a.metadata["key"] == "val"


class TestOrchestratorObservation:
    def test_valid_construction(self) -> None:
        obs = OrchestratorObservation(
            task_description="test", subtasks=[], agents=[],
            completed_outputs={}, errors=[], time_remaining=10,
            time_elapsed=0, capacity_limit=3, active_task_count=0,
            available_actions=["delegate", "wait"],
        )
        assert obs.done is False
        assert obs.reward is None
        assert obs.budget_remaining is None
        assert obs.critical_path_length is None
        assert obs.reward_breakdown is None

    def test_inherits_done_and_reward(self) -> None:
        obs = OrchestratorObservation(
            task_description="t", subtasks=[], agents=[],
            completed_outputs={}, errors=[], time_remaining=0,
            time_elapsed=10, capacity_limit=3, active_task_count=0,
            available_actions=[], done=True, reward=1.5,
        )
        assert obs.done is True
        assert obs.reward == 1.5


class TestOrchestratorState:
    def test_valid_construction(self) -> None:
        s = OrchestratorState(
            task_id="easy", task_name="test", difficulty="easy",
            subtask_statuses={}, agent_statuses={}, completed_outputs={},
            total_reward=0.0, failures_occurred=0, failures_recovered=0,
            parallelism_events=0, capacity_violations=0,
        )
        assert s.episode_id is None
        assert s.step_count == 0

    def test_allows_extra_fields(self) -> None:
        s = OrchestratorState(
            task_id="easy", task_name="test", difficulty="easy",
            subtask_statuses={}, agent_statuses={}, completed_outputs={},
            total_reward=0.0, failures_occurred=0, failures_recovered=0,
            parallelism_events=0, capacity_violations=0,
            extra_field="allowed",
        )
        assert s.extra_field == "allowed"  # type: ignore[attr-defined]


class TestGradeResult:
    def test_valid(self) -> None:
        g = GradeResult(score=0.85, breakdown={"completion": 0.7, "bonus": 0.15})
        assert g.score == 0.85


class TestEpisodeLog:
    def test_append(self) -> None:
        log = EpisodeLog(task_id="test")
        log.append(1, "action_taken", {"action_type": "delegate"})
        log.append(2, "subtask_completed", {"subtask_id": "t1"})
        assert len(log.events) == 2
        assert log.events[0].step == 1
        assert log.events[1].event_type == "subtask_completed"

    def test_rejects_invalid_event_type(self) -> None:
        log = EpisodeLog(task_id="test")
        with pytest.raises(ValidationError):
            log.append(1, "invalid_type", {})
