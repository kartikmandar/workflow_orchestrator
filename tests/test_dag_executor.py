"""Tests for DAG executor — dependency resolution, status transitions, validation."""

import pytest

from server.dag_executor import DAGExecutor
from server.task_registry import get_task


class TestDAGExecutorBasic:
    def test_initial_ready_easy(self) -> None:
        """Easy task: only technical_design has no dependencies, so it's ready."""
        config = get_task("easy")
        dag = DAGExecutor(config.subtask_definitions)
        ready = dag.get_ready_subtasks()
        assert ready == ["technical_design"]

    def test_initial_ready_medium(self) -> None:
        """Medium task: only checkout_code has no dependencies."""
        config = get_task("medium")
        dag = DAGExecutor(config.subtask_definitions)
        assert dag.get_ready_subtasks() == ["checkout_code"]

    def test_initial_ready_hard(self) -> None:
        """Hard task: only alert_triage has no dependencies."""
        config = get_task("hard")
        dag = DAGExecutor(config.subtask_definitions)
        assert dag.get_ready_subtasks() == ["alert_triage"]


class TestDAGExecutorTransitions:
    def _make_easy_dag(self) -> DAGExecutor:
        return DAGExecutor(get_task("easy").subtask_definitions)

    def test_delegate_and_complete(self) -> None:
        dag = self._make_easy_dag()
        dag.delegate("technical_design", "tech_lead")
        assert dag.get_subtask_status("technical_design") == "in_progress"
        assert "technical_design" in dag.get_in_progress_subtasks()

        dag.complete("technical_design", "Design done")
        assert dag.get_subtask_status("technical_design") == "completed"
        assert dag.get_completed_outputs()["technical_design"] == "Design done"

    def test_dependency_cascade(self) -> None:
        """Completing technical_design makes implement_backend ready."""
        dag = self._make_easy_dag()
        dag.delegate("technical_design", "tech_lead")
        dag.complete("technical_design", "done")
        dag.update_ready_statuses()
        assert "implement_backend" in dag.get_ready_subtasks()

    def test_parallelism_opportunity(self) -> None:
        """After implement_backend, both implement_frontend and write_tests become ready."""
        dag = self._make_easy_dag()
        dag.delegate("technical_design", "tech_lead")
        dag.complete("technical_design", "done")
        dag.update_ready_statuses()

        dag.delegate("implement_backend", "backend_dev")
        dag.complete("implement_backend", "done")
        dag.update_ready_statuses()

        ready = dag.get_ready_subtasks()
        assert "implement_frontend" in ready
        assert "write_tests" in ready

    def test_fan_in(self) -> None:
        """run_tests needs BOTH implement_frontend and write_tests completed."""
        dag = self._make_easy_dag()
        # Walk through to fan-in point
        for sid, agent in [
            ("technical_design", "tech_lead"),
            ("implement_backend", "backend_dev"),
        ]:
            dag.delegate(sid, agent)
            dag.complete(sid, "done")
            dag.update_ready_statuses()

        # Complete only one of the parallel tasks
        dag.delegate("implement_frontend", "frontend_dev")
        dag.complete("implement_frontend", "done")
        dag.update_ready_statuses()
        assert "run_tests" not in dag.get_ready_subtasks()

        # Complete the other
        dag.delegate("write_tests", "backend_dev")
        dag.complete("write_tests", "done")
        dag.update_ready_statuses()
        assert "run_tests" in dag.get_ready_subtasks()

    def test_fail_and_retry(self) -> None:
        dag = self._make_easy_dag()
        dag.delegate("technical_design", "tech_lead")
        dag.fail("technical_design", "Something went wrong")
        assert dag.get_subtask_status("technical_design") == "failed"
        assert dag.get_subtask_attempt_count("technical_design") == 1

        dag.retry("technical_design", "tech_lead")
        assert dag.get_subtask_status("technical_design") == "in_progress"

    def test_abort(self) -> None:
        dag = self._make_easy_dag()
        dag.abort("technical_design")
        assert dag.get_subtask_status("technical_design") == "failed"

    def test_cannot_delegate_pending(self) -> None:
        dag = self._make_easy_dag()
        with pytest.raises(ValueError, match="not.*ready"):
            dag.delegate("implement_backend", "backend_dev")

    def test_cannot_retry_completed(self) -> None:
        dag = self._make_easy_dag()
        dag.delegate("technical_design", "tech_lead")
        dag.complete("technical_design", "done")
        with pytest.raises(ValueError, match="not.*failed"):
            dag.retry("technical_design", "tech_lead")

    def test_cannot_abort_completed(self) -> None:
        dag = self._make_easy_dag()
        dag.delegate("technical_design", "tech_lead")
        dag.complete("technical_design", "done")
        with pytest.raises(ValueError, match="already completed"):
            dag.abort("technical_design")

    def test_unknown_subtask_raises(self) -> None:
        dag = self._make_easy_dag()
        with pytest.raises(KeyError):
            dag.delegate("nonexistent", "tech_lead")


class TestDAGExecutorFullWalkthrough:
    def test_easy_task_sequential(self) -> None:
        """Walk through the entire easy task sequentially and verify completion."""
        dag = DAGExecutor(get_task("easy").subtask_definitions)
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
            assert sid in dag.get_ready_subtasks(), f"{sid} should be ready"
            dag.delegate(sid, agent)
            dag.complete(sid, f"{sid} done")

        assert dag.is_all_completed()
        assert len(dag.get_completed_outputs()) == 6


class TestDAGValidation:
    def test_cycle_detection(self) -> None:
        """DAG with a cycle should raise ValueError."""
        cyclic = [
            {"id": "a", "type": "x", "dependencies": ["b"]},
            {"id": "b", "type": "x", "dependencies": ["a"]},
        ]
        with pytest.raises(ValueError, match="cycle"):
            DAGExecutor(cyclic)

    def test_unknown_dependency_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown subtask"):
            DAGExecutor([
                {"id": "a", "type": "x", "dependencies": ["nonexistent"]},
            ])

    def test_subtask_infos_export(self) -> None:
        dag = DAGExecutor(get_task("easy").subtask_definitions)
        infos = dag.get_subtask_infos()
        assert len(infos) == 6
        assert all(hasattr(info, "id") for info in infos)
        ready_count = sum(1 for info in infos if info.status == "ready")
        assert ready_count == 1  # Only technical_design
