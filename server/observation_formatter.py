"""Render OrchestratorObservation as structured text for LLM consumption.

Used by inference.py (Phase 3), not by the server itself.
"""

try:
    from ..models import OrchestratorObservation
except ImportError:
    from models import OrchestratorObservation


def format_observation(obs: OrchestratorObservation) -> str:
    """Format an observation as structured text for an LLM agent.

    Sections: header, subtasks, agents, errors, available actions, hint.
    """
    lines: list[str] = []

    # ── Header ──
    lines.append("=== Workflow Orchestrator ===")
    lines.append(f"Task: {obs.task_description}")
    lines.append(f"Time: {obs.time_elapsed} elapsed, {obs.time_remaining} remaining")
    lines.append(f"Active tasks: {obs.active_task_count}/{obs.capacity_limit}")
    if obs.budget_remaining is not None:
        lines.append(f"Budget: {obs.budget_used:.1f} used, {obs.budget_remaining:.1f} remaining")
    lines.append("")

    # ── Subtasks ──
    lines.append("--- Subtasks ---")
    for s in obs.subtasks:
        # Map status to display label
        if s.status == "pending" and not s.dependencies_met:
            label = "BLOCKED"
        elif s.status == "pending":
            label = "PENDING"
        else:
            label = s.status.upper()

        line = f"  [{label:12s}] {s.id} (type: {s.type})"
        if s.assigned_to:
            line += f" -> {s.assigned_to}"
        if s.steps_remaining is not None and s.status == "in_progress":
            line += f" ({s.steps_remaining} step(s) left)"
        if s.error:
            line += f" [error: {s.error}]"
        if s.dependencies:
            deps_status = []
            for dep in s.dependencies:
                dep_info = next((si for si in obs.subtasks if si.id == dep), None)
                if dep_info and dep_info.status == "completed":
                    deps_status.append(f"{dep} done")
                elif dep_info:
                    deps_status.append(f"{dep} {dep_info.status}")
                else:
                    deps_status.append(dep)
            line += f" | deps: [{', '.join(deps_status)}]"
        if s.attempt_count > 0:
            line += f" | attempts: {s.attempt_count}"
        lines.append(line)
    lines.append("")

    # ── Agents ──
    lines.append("--- Agents ---")
    for a in obs.agents:
        caps = ", ".join(a.capabilities)
        line = f"  [{a.status:8s}] {a.name} ({caps})"
        line += f" | speed={a.speed} cost={a.cost_per_step:.1f} rel={a.reliability:.2f}"
        if a.current_task:
            line += f" | working on: {a.current_task}"
        lines.append(line)
    lines.append("")

    # ── Completed outputs ──
    if obs.completed_outputs:
        lines.append("--- Completed Outputs ---")
        for sid, output in obs.completed_outputs.items():
            lines.append(f"  {sid}: {output}")
        lines.append("")

    # ── Errors ──
    if obs.errors:
        lines.append("--- Errors ---")
        for e in obs.errors:
            lines.append(f"  ! {e}")
        lines.append("")

    # ── Available actions ──
    lines.append(f"Available actions: {', '.join(obs.available_actions)}")

    # ── Hint ──
    if obs.hint:
        lines.append(f"Hint: {obs.hint}")

    if obs.done:
        lines.append("")
        lines.append(f"*** EPISODE DONE | Reward: {obs.reward:.4f} ***")

    return "\n".join(lines)
