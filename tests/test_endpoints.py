"""Tests for custom HTTP endpoints — /tasks, /grader, /baseline."""

import pytest
from fastapi.testclient import TestClient

from server.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestTasksEndpoint:
    def test_get_tasks_returns_three(self, client) -> None:
        resp = client.get("/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    def test_get_tasks_structure(self, client) -> None:
        resp = client.get("/tasks")
        data = resp.json()
        for task in data:
            assert "task_id" in task
            assert "name" in task
            assert "difficulty" in task
            assert "description" in task
            assert "subtask_count" in task
            assert "agent_count" in task

    def test_get_tasks_ids(self, client) -> None:
        resp = client.get("/tasks")
        ids = {t["task_id"] for t in resp.json()}
        assert ids == {"easy", "medium", "hard"}


class TestGraderEndpoint:
    def test_no_episode_returns_404(self, client) -> None:
        # Clear any prior state
        from server.environment import _episode_store
        _episode_store.pop("easy", None)
        resp = client.post("/grader", json={"task_id": "easy"})
        assert resp.status_code == 404

    def test_grader_after_episode(self, client) -> None:
        """Run an episode via the environment directly, then grade via HTTP."""
        from server.environment import OrchestratorEnvironment
        from models import OrchestratorAction

        env = OrchestratorEnvironment()
        env.reset(task_id="easy")
        for _ in range(15):
            env.step(OrchestratorAction(action_type="wait"))
        # Episode ended → log stored in _episode_store
        resp = client.post("/grader", json={"task_id": "easy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert "breakdown" in data
        assert 0.0 <= data["score"] <= 1.0


class TestBaselineEndpoint:
    def test_returns_three_keys(self, client) -> None:
        resp = client.post("/baseline")
        assert resp.status_code == 200
        data = resp.json()
        assert "easy" in data
        assert "medium" in data
        assert "hard" in data


class TestBuiltInEndpoints:
    def test_health(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
