# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the Workflow Orchestrator Environment.

This module creates an HTTP server that exposes the WorkflowOrchestratorEnvironment
over HTTP and WebSocket endpoints, compatible with EnvClient.

Endpoints:
    - POST /reset: Reset the environment
    - POST /step: Execute an action
    - GET /state: Get current environment state
    - GET /schema: Get action/observation schemas
    - WS /ws: WebSocket endpoint for persistent sessions

Usage:
    # Development (with auto-reload):
    uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

    # Production:
    uvicorn server.app:app --host 0.0.0.0 --port 8000 --workers 4

    # Or run directly:
    python -m server.app
"""

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required for the web interface. Install dependencies with '\n    uv sync\n'"
    ) from e

try:
    from ..models import OrchestratorAction, OrchestratorObservation
    from .environment import OrchestratorEnvironment
except ImportError:
    from models import OrchestratorAction, OrchestratorObservation
    from server.environment import OrchestratorEnvironment


app = create_app(
    OrchestratorEnvironment,
    OrchestratorAction,
    OrchestratorObservation,
    env_name="workflow_orchestrator",
)


# ── Custom endpoints (required by hackathon) ──


@app.get("/tasks")
def list_task_metadata():
    """Return metadata for all available tasks."""
    try:
        from .task_registry import list_tasks
    except ImportError:
        from server.task_registry import list_tasks

    return [
        {
            "task_id": t.task_id,
            "name": t.name,
            "difficulty": t.difficulty,
            "description": t.description,
            "subtask_count": len(t.subtask_definitions),
            "agent_count": len(t.agent_definitions),
        }
        for t in list_tasks()
    ]


@app.post("/grader")
def grade_episode(request: dict):
    """Grade the most recent episode for a given task."""
    from fastapi import HTTPException

    try:
        from .environment import _episode_store
        from .graders import grade
    except ImportError:
        from server.environment import _episode_store
        from server.graders import grade

    task_id = request.get("task_id", "easy")
    if task_id not in _episode_store:
        raise HTTPException(
            status_code=404,
            detail=f"No episode log for task '{task_id}'. Run an episode first.",
        )
    return grade(task_id, _episode_store[task_id]).model_dump()


@app.post("/baseline")
def get_baseline():
    """Return pre-computed baseline scores."""
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "baseline_scores.json"
    if not path.exists():
        return {"easy": None, "medium": None, "hard": None}
    return json.loads(path.read_text())


def main(host: str = "0.0.0.0", port: int = 8000):
    """
    Entry point for direct execution via uv run or python -m.

    This function enables running the server without Docker:
        uv run --project . server
        uv run --project . server --port 8001
        python -m workflow_orchestrator.server.app

    Args:
        host: Host address to bind to (default: "0.0.0.0")
        port: Port number to listen on (default: 8000)

    For production deployments, consider using uvicorn directly with
    multiple workers:
        uvicorn workflow_orchestrator.server.app:app --workers 4
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
