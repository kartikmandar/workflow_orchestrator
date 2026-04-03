"""Tests for task registry — config validity and DAG structure."""

import pytest

from server.dag_executor import DAGExecutor
from server.task_registry import TaskConfig, get_task, list_tasks


class TestTaskRegistry:
    def test_get_easy(self) -> None:
        t = get_task("easy")
        assert t.task_id == "easy"
        assert t.name == "Feature Development Sprint"
        assert len(t.subtask_definitions) == 6
        assert len(t.agent_definitions) == 4
        assert t.constraints["cost_budget"] is None

    def test_get_medium(self) -> None:
        t = get_task("medium")
        assert t.task_id == "medium"
        assert len(t.subtask_definitions) == 9
        assert len(t.agent_definitions) == 5
        assert t.constraints["cost_budget"] == 35.0
        assert ("security_scanner", "security_scan") in t.reliability_overrides

    def test_get_hard(self) -> None:
        t = get_task("hard")
        assert t.task_id == "hard"
        assert len(t.subtask_definitions) == 10
        assert len(t.agent_definitions) == 7
        assert t.constraints["cost_budget"] == 40.0
        assert t.sla_milestones is not None
        assert "root_cause_analysis" in t.sla_milestones
        assert len(t.scheduled_events) == 1

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            get_task("nonexistent")

    def test_list_tasks(self) -> None:
        tasks = list_tasks()
        assert len(tasks) == 3
        ids = {t.task_id for t in tasks}
        assert ids == {"easy", "medium", "hard"}

    @pytest.mark.parametrize("task_id", ["easy", "medium", "hard"])
    def test_dag_is_valid(self, task_id: str) -> None:
        """Every task's subtask definitions form a valid DAG (no cycles)."""
        config = get_task(task_id)
        dag = DAGExecutor(config.subtask_definitions)
        assert dag is not None

    @pytest.mark.parametrize("task_id", ["easy", "medium", "hard"])
    def test_all_subtask_types_have_capable_agent(self, task_id: str) -> None:
        """Every subtask type has at least one agent that can handle it."""
        config = get_task(task_id)
        all_capabilities: set[str] = set()
        for agent in config.agent_definitions:
            all_capabilities.update(agent["capabilities"])
        for subtask in config.subtask_definitions:
            assert subtask["type"] in all_capabilities, (
                f"No agent can handle subtask type '{subtask['type']}' in {task_id}"
            )
