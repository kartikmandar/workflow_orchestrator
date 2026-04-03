# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Pydantic models for the Workflow Orchestrator Environment."""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from openenv.core.env_server.types import (
    Action as BaseAction,
    Observation as BaseObservation,
    State as BaseState,
)


# ── Nested info models (not Actions/Observations, just data) ��─


class SubtaskInfo(BaseModel):
    """State of a single subtask in the workflow DAG."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    status: Literal[
        "pending",
        "ready",
        "in_progress",
        "completed",
        "failed",
    ]
    dependencies: list[str]
    dependencies_met: bool
    assigned_to: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    steps_remaining: Optional[int] = None
    attempt_count: int = 0


class AgentInfo(BaseModel):
    """State of a simulated specialist agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    capabilities: list[str]
    status: Literal["idle", "working", "failed", "offline"]
    current_task: Optional[str] = None
    reliability: float
    speed: int
    cost_per_step: float


# ── OpenEnv-compliant top-level models ──


class OrchestratorAction(BaseAction):
    """Action the orchestrator LLM can take each step."""

    action_type: Literal[
        "delegate",
        "retry",
        "wait",
        "synthesize",
        "abort",
    ]
    subtask_id: Optional[str] = None
    agent_name: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class OrchestratorObservation(BaseObservation):
    """Full observable state returned each step."""

    task_description: str
    subtasks: list[SubtaskInfo]
    agents: list[AgentInfo]
    completed_outputs: Dict[str, str]
    errors: list[str]
    time_remaining: int
    time_elapsed: int
    capacity_limit: int
    active_task_count: int
    budget_remaining: Optional[float] = None
    budget_used: float = 0.0
    available_actions: list[str]
    hint: Optional[str] = None


class OrchestratorState(BaseState):
    """Episode metadata snapshot."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    task_name: str
    difficulty: str
    subtask_statuses: Dict[str, str]
    agent_statuses: Dict[str, str]
    completed_outputs: Dict[str, str]
    total_reward: float
    failures_occurred: int
    failures_recovered: int
    parallelism_events: int
    capacity_violations: int
    budget_total: Optional[float] = None
    budget_used: float = 0.0


# ── Grading types ──


class GradeResult(BaseModel):
    """Result from a grader evaluation."""

    score: float
    breakdown: Dict[str, float]


# ── Episode logging types ──


class EpisodeEvent(BaseModel):
    """Single event in the episode log."""

    step: int
    event_type: Literal[
        "action_taken",
        "action_invalid",
        "subtask_delegated",
        "subtask_completed",
        "subtask_failed",
        "agent_dropout",
        "agent_degraded",
        "parallelism",
        "sla_missed",
        "episode_end",
    ]
    data: Dict[str, Any]


class EpisodeLog(BaseModel):
    """Append-only event log for grader analysis."""

    task_id: str
    events: list[EpisodeEvent] = Field(default_factory=list)
    total_steps: int = 0
    time_remaining: int = 0
    budget_used: float = 0.0
    budget_total: Optional[float] = None

    def append(self, step: int, event_type: str, data: Dict[str, Any]) -> None:
        """Append an event to the log."""
        self.events.append(
            EpisodeEvent(step=step, event_type=event_type, data=data)
        )
