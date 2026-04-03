# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Workflow Orchestrator Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult

from .models import OrchestratorAction, OrchestratorObservation, OrchestratorState


class OrchestratorClient(
    EnvClient[OrchestratorAction, OrchestratorObservation, OrchestratorState]
):
    """Client for the Workflow Orchestrator Environment."""

    def _step_payload(self, action: OrchestratorAction) -> Dict:
        return action.model_dump(exclude_none=True)

    def _parse_result(self, payload: Dict) -> StepResult[OrchestratorObservation]:
        obs_data = payload.get("observation", {})
        observation = OrchestratorObservation(**obs_data)
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> OrchestratorState:
        return OrchestratorState(**payload)
