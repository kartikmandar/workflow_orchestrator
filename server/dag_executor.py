"""DAG state tracking, dependency resolution, and topological sort.

Manages subtask status transitions:
  pending → ready → in_progress → completed/failed
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from models import SubtaskInfo


@dataclass
class _SubtaskState:
    """Internal mutable state for a subtask (not Pydantic — avoids validation overhead)."""

    id: str
    type: str
    status: str = "pending"
    dependencies: list[str] = field(default_factory=list)
    output_template: str = ""
    assigned_to: str | None = None
    output: str | None = None
    error: str | None = None
    steps_remaining: int | None = None
    attempt_count: int = 0


class DAGExecutor:
    """Tracks subtask states, dependencies, and status transitions for a workflow DAG."""

    def __init__(self, subtask_definitions: list[dict[str, Any]]) -> None:
        self._subtasks: dict[str, _SubtaskState] = {}
        for defn in subtask_definitions:
            sid = defn["id"]
            self._subtasks[sid] = _SubtaskState(
                id=sid,
                type=defn["type"],
                dependencies=list(defn.get("dependencies", [])),
                output_template=defn.get("output_template", ""),
            )
        self._validate_dag()
        self.update_ready_statuses()

    def _validate_dag(self) -> None:
        """Validate the DAG has no cycles via topological sort (Kahn's algorithm)."""
        self._topological_sort()

    def _topological_sort(self) -> list[str]:
        """Kahn's algorithm — returns topological order or raises ValueError if cyclic."""
        in_degree: dict[str, int] = {sid: 0 for sid in self._subtasks}
        adj: dict[str, list[str]] = {sid: [] for sid in self._subtasks}

        for sid, st in self._subtasks.items():
            for dep in st.dependencies:
                if dep not in self._subtasks:
                    raise ValueError(
                        f"Subtask '{sid}' depends on unknown subtask '{dep}'"
                    )
                adj[dep].append(sid)
                in_degree[sid] += 1

        queue: deque[str] = deque(
            sid for sid, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._subtasks):
            raise ValueError("DAG contains a cycle — topological sort failed")
        return order

    # ── Status transitions ──

    def update_ready_statuses(self) -> None:
        """Transition pending subtasks to ready when all dependencies are completed."""
        for st in self._subtasks.values():
            if st.status == "pending":
                if all(
                    self._subtasks[dep].status == "completed"
                    for dep in st.dependencies
                ):
                    st.status = "ready"

    def delegate(self, subtask_id: str, agent_name: str) -> None:
        """Transition a ready subtask to in_progress."""
        st = self._get(subtask_id)
        if st.status != "ready":
            raise ValueError(
                f"Cannot delegate '{subtask_id}': status is '{st.status}', expected 'ready'"
            )
        st.status = "in_progress"
        st.assigned_to = agent_name
        st.error = None

    def complete(self, subtask_id: str, output: str) -> None:
        """Transition an in_progress subtask to completed."""
        st = self._get(subtask_id)
        if st.status != "in_progress":
            raise ValueError(
                f"Cannot complete '{subtask_id}': status is '{st.status}', expected 'in_progress'"
            )
        st.status = "completed"
        st.output = output
        st.steps_remaining = None

    def fail(self, subtask_id: str, error: str) -> None:
        """Transition an in_progress subtask to failed."""
        st = self._get(subtask_id)
        if st.status != "in_progress":
            raise ValueError(
                f"Cannot fail '{subtask_id}': status is '{st.status}', expected 'in_progress'"
            )
        st.status = "failed"
        st.error = error
        st.attempt_count += 1
        st.assigned_to = None
        st.steps_remaining = None

    def retry(self, subtask_id: str, agent_name: str) -> None:
        """Transition a failed subtask back to in_progress with a (possibly different) agent."""
        st = self._get(subtask_id)
        if st.status != "failed":
            raise ValueError(
                f"Cannot retry '{subtask_id}': status is '{st.status}', expected 'failed'"
            )
        st.status = "in_progress"
        st.assigned_to = agent_name
        st.error = None

    def abort(self, subtask_id: str) -> None:
        """Permanently fail a subtask (any status except completed)."""
        st = self._get(subtask_id)
        if st.status == "completed":
            raise ValueError(f"Cannot abort '{subtask_id}': already completed")
        st.status = "failed"
        st.error = "aborted"
        st.assigned_to = None
        st.steps_remaining = None

    # ── Queries ──

    def get_ready_subtasks(self) -> list[str]:
        """Return IDs of subtasks with status 'ready'."""
        return [sid for sid, st in self._subtasks.items() if st.status == "ready"]

    def get_in_progress_subtasks(self) -> list[str]:
        """Return IDs of subtasks with status 'in_progress'."""
        return [sid for sid, st in self._subtasks.items() if st.status == "in_progress"]

    def get_failed_subtasks(self) -> list[str]:
        """Return IDs of subtasks with status 'failed'."""
        return [sid for sid, st in self._subtasks.items() if st.status == "failed"]

    def is_all_completed(self) -> bool:
        """Check if every subtask has status 'completed'."""
        return all(st.status == "completed" for st in self._subtasks.values())

    def get_completed_outputs(self) -> dict[str, str]:
        """Return {subtask_id: output} for all completed subtasks."""
        return {
            sid: st.output
            for sid, st in self._subtasks.items()
            if st.status == "completed" and st.output is not None
        }

    def get_subtask_type(self, subtask_id: str) -> str:
        return self._get(subtask_id).type

    def get_subtask_status(self, subtask_id: str) -> str:
        return self._get(subtask_id).status

    def get_subtask_attempt_count(self, subtask_id: str) -> int:
        return self._get(subtask_id).attempt_count

    def is_valid_subtask(self, subtask_id: str) -> bool:
        return subtask_id in self._subtasks

    def set_steps_remaining(self, subtask_id: str, steps: int) -> None:
        """Set steps_remaining for an in_progress subtask (called by environment after assign)."""
        self._get(subtask_id).steps_remaining = steps

    def get_subtask_infos(self) -> list[SubtaskInfo]:
        """Export current state as list of SubtaskInfo Pydantic models (for observations)."""
        infos: list[SubtaskInfo] = []
        for st in self._subtasks.values():
            deps_met = all(
                self._subtasks[dep].status == "completed"
                for dep in st.dependencies
            )
            infos.append(SubtaskInfo(
                id=st.id,
                type=st.type,
                status=st.status,
                dependencies=st.dependencies,
                dependencies_met=deps_met,
                assigned_to=st.assigned_to,
                output=st.output,
                error=st.error,
                steps_remaining=st.steps_remaining,
                attempt_count=st.attempt_count,
            ))
        return infos

    def _get(self, subtask_id: str) -> _SubtaskState:
        """Get internal subtask state, raising KeyError for unknown IDs."""
        if subtask_id not in self._subtasks:
            raise KeyError(f"Unknown subtask_id: '{subtask_id}'")
        return self._subtasks[subtask_id]
