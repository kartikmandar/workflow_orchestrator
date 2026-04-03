# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Workflow Orchestrator Environment Implementation.

Temporary stub using OrchestratorAction/Observation types.
Full implementation in Phase 2.
"""

from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import OrchestratorAction, OrchestratorObservation
except ImportError:
    from models import OrchestratorAction, OrchestratorObservation


class OrchestratorEnvironment(Environment):
    """Workflow Orchestrator Environment — stub for Phase 1.

    Returns minimal valid observations so openenv validate passes.
    Full reset/step/state logic implemented in Phase 2.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self) -> None:
        self._state = State(episode_id=str(uuid4()), step_count=0)

    def reset(self, **kwargs) -> OrchestratorObservation:  # type: ignore[override]
        self._state = State(episode_id=str(uuid4()), step_count=0)
        return OrchestratorObservation(
            task_description="Stub — Phase 2 implements full logic",
            subtasks=[],
            agents=[],
            completed_outputs={},
            errors=[],
            time_remaining=0,
            time_elapsed=0,
            capacity_limit=0,
            active_task_count=0,
            available_actions=[],
            done=False,
            reward=0.0,
        )

    def step(self, action: OrchestratorAction, **kwargs) -> OrchestratorObservation:  # type: ignore[override]
        self._state.step_count += 1
        return OrchestratorObservation(
            task_description="Stub — Phase 2 implements full logic",
            subtasks=[],
            agents=[],
            completed_outputs={},
            errors=[],
            time_remaining=0,
            time_elapsed=0,
            capacity_limit=0,
            active_task_count=0,
            available_actions=[],
            done=True,
            reward=0.0,
        )

    @property
    def state(self) -> State:
        return self._state
