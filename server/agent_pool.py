"""Simulated agent state machines with tick-based countdown and seeded failures.

Agent state machine:
  idle → (assign) → working(steps_remaining) → tick countdown →
    when steps_remaining==0: seeded_random < reliability ? completed : failed
"""

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Union

from models import AgentInfo


def _deterministic_hash(s: str) -> int:
    """Process-independent hash for seeded RNG determinism.

    Python's built-in hash() is randomized per process since 3.3.
    Using SHA-256 ensures reproducibility across restarts and machines.
    """
    return int(hashlib.sha256(s.encode()).hexdigest()[:16], 16)


def _get_effective_reliability(
    overrides: dict[tuple[str, str], Union[float, list[float]]],
    agent_name: str,
    subtask_type: str,
    attempt_count: int,
    default_reliability: float,
) -> float:
    """Get the reliability for an (agent, subtask_type, attempt) triple.

    If overrides has a list, index by attempt_count (clamped to last element).
    If overrides has a float, use it for all attempts.
    If no override, use the agent's default reliability.
    """
    key = (agent_name, subtask_type)
    override = overrides.get(key)
    if override is None:
        return default_reliability
    if isinstance(override, list):
        idx = min(attempt_count, len(override) - 1)
        return override[idx]
    return override


@dataclass
class _AgentState:
    """Internal mutable state for an agent."""

    name: str
    capabilities: list[str] = field(default_factory=list)
    status: str = "idle"
    current_task: str | None = None
    current_task_type: str | None = None
    reliability: float = 1.0
    speed: int = 1
    cost_per_step: float = 1.0
    steps_remaining: int = 0
    attempt_count: int = 0


@dataclass
class TickResult:
    """Result from a single agent completing or failing a task during tick."""

    agent_name: str
    subtask_id: str
    succeeded: bool
    output_or_error: str
    is_permanent_failure: bool = False


class AgentPool:
    """Manages simulated specialist agents with tick-based work simulation."""

    def __init__(
        self,
        agent_definitions: list[dict[str, Any]],
        reliability_overrides: dict[tuple[str, str], Union[float, list[float]]],
        seed: int,
    ) -> None:
        self._agents: dict[str, _AgentState] = {}
        for defn in agent_definitions:
            name = defn["name"]
            self._agents[name] = _AgentState(
                name=name,
                capabilities=list(defn["capabilities"]),
                reliability=defn["reliability"],
                speed=defn["speed"],
                cost_per_step=defn["cost_per_step"],
            )
        self._reliability_overrides = reliability_overrides
        self._seed = seed
        self._budget_used: float = 0.0

    # ── State mutations ──

    def assign(
        self,
        agent_name: str,
        subtask_id: str,
        subtask_type: str,
        attempt_count: int,
    ) -> None:
        """Assign a subtask to an idle, capable agent."""
        agent = self._get(agent_name)
        if agent.status != "idle":
            raise ValueError(f"Agent '{agent_name}' is not idle (status: {agent.status})")
        if subtask_type not in agent.capabilities:
            raise ValueError(
                f"Agent '{agent_name}' lacks capability '{subtask_type}'"
            )
        agent.status = "working"
        agent.current_task = subtask_id
        agent.current_task_type = subtask_type
        agent.steps_remaining = agent.speed
        agent.attempt_count = attempt_count

    def tick(self, step_number: int) -> list[TickResult]:
        """Advance all working agents by one step.

        For each working agent:
          - Accrue cost (budget_used += cost_per_step)
          - Decrement steps_remaining
          - If steps_remaining reaches 0: determine success via seeded RNG

        Returns list of TickResults for agents that finished this tick.
        """
        results: list[TickResult] = []

        for agent in self._agents.values():
            if agent.status != "working":
                continue

            self._budget_used += agent.cost_per_step
            agent.steps_remaining -= 1

            if agent.steps_remaining <= 0:
                reliability = _get_effective_reliability(
                    self._reliability_overrides,
                    agent.name,
                    agent.current_task_type,
                    agent.attempt_count,
                    agent.reliability,
                )

                h = _deterministic_hash(
                    f"{agent.name}:{agent.current_task}:{agent.attempt_count}"
                )
                rng = random.Random(self._seed + h)
                roll = rng.random()
                succeeded = roll < reliability

                is_permanent = reliability == 0.0

                if succeeded:
                    output_or_error = ""  # environment fills from output_template
                else:
                    if is_permanent:
                        output_or_error = (
                            f"Agent '{agent.name}' lacks required tooling for "
                            f"'{agent.current_task_type}' — permanent failure"
                        )
                    else:
                        output_or_error = (
                            f"Execution failed on '{agent.current_task}', may succeed on retry"
                        )

                results.append(TickResult(
                    agent_name=agent.name,
                    subtask_id=agent.current_task,
                    succeeded=succeeded,
                    output_or_error=output_or_error,
                    is_permanent_failure=is_permanent and not succeeded,
                ))

        return results

    def release_agent(self, agent_name: str) -> None:
        """Reset an agent to idle after task completion or failure."""
        agent = self._get(agent_name)
        agent.status = "idle"
        agent.current_task = None
        agent.current_task_type = None
        agent.steps_remaining = 0

    def apply_scheduled_events(
        self, step: int, scheduled_events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Apply any scheduled events for the current step.

        Returns list of events that fired (for episode log).
        """
        fired: list[dict[str, Any]] = []
        for event in scheduled_events:
            if event["step"] != step:
                continue

            target = event["target"]
            event_type = event["event_type"]

            if event_type == "dropout":
                agent = self._agents.get(target)
                if agent and agent.status != "offline":
                    was_working = agent.status == "working"
                    released_task = agent.current_task
                    agent.status = "offline"
                    agent.current_task = None
                    agent.current_task_type = None
                    agent.steps_remaining = 0
                    fired.append({
                        "event_type": "agent_dropout",
                        "agent_name": target,
                        "was_working": was_working,
                        "released_task": released_task,
                    })

            elif event_type == "degradation":
                agent = self._agents.get(target)
                if agent and agent.status != "offline":
                    new_speed = event.get("params", {}).get("new_speed", agent.speed * 2)
                    agent.speed = new_speed
                    fired.append({
                        "event_type": "agent_degraded",
                        "agent_name": target,
                        "new_speed": new_speed,
                    })

        return fired

    # ── Queries ──

    def get_idle_agents(self) -> list[str]:
        """Return names of agents with status 'idle'."""
        return [a.name for a in self._agents.values() if a.status == "idle"]

    def get_capable_agents(self, subtask_type: str) -> list[str]:
        """Return names of idle agents that have the capability for subtask_type."""
        return [
            a.name for a in self._agents.values()
            if a.status == "idle" and subtask_type in a.capabilities
        ]

    def get_active_count(self) -> int:
        """Return count of agents currently working."""
        return sum(1 for a in self._agents.values() if a.status == "working")

    def get_budget_used(self) -> float:
        return self._budget_used

    def has_capability(self, agent_name: str, subtask_type: str) -> bool:
        agent = self._agents.get(agent_name)
        return agent is not None and subtask_type in agent.capabilities

    def is_idle(self, agent_name: str) -> bool:
        agent = self._agents.get(agent_name)
        return agent is not None and agent.status == "idle"

    def is_online(self, agent_name: str) -> bool:
        agent = self._agents.get(agent_name)
        return agent is not None and agent.status != "offline"

    def get_agent_cost(self, agent_name: str) -> float:
        return self._get(agent_name).cost_per_step

    def get_agent_infos(self) -> list[AgentInfo]:
        """Export current state as list of AgentInfo Pydantic models (for observations)."""
        return [
            AgentInfo(
                name=a.name,
                capabilities=a.capabilities,
                status=a.status,
                current_task=a.current_task,
                reliability=a.reliability,
                speed=a.speed,
                cost_per_step=a.cost_per_step,
            )
            for a in self._agents.values()
        ]

    def get_effective_reliability(
        self, agent_name: str, subtask_type: str, attempt_count: int
    ) -> float:
        """Get the effective reliability for an (agent, subtask_type, attempt) triple.

        Public API for use by the environment to check for permanent failures
        without duplicating reliability override logic.
        """
        agent = self._get(agent_name)
        return _get_effective_reliability(
            self._reliability_overrides,
            agent_name,
            subtask_type,
            attempt_count,
            agent.reliability,
        )

    def _get(self, agent_name: str) -> _AgentState:
        if agent_name not in self._agents:
            raise KeyError(f"Unknown agent: '{agent_name}'")
        return self._agents[agent_name]
