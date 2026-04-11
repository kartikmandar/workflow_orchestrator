"""Custom Gradio UI for the Workflow Orchestrator — Mission Control Dashboard.

Provides a visual DAG workflow, agent pool cards, metrics bar, and interactive
controls. Registered via the ``gradio_builder`` parameter of ``create_app()``;
appears as a "Custom" tab alongside the default "Playground" tab.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

import gradio as gr

try:
    from openenv.core.env_server.types import EnvironmentMetadata
except ImportError:
    EnvironmentMetadata = Any  # type: ignore[assignment,misc]


# ── Status colors ──

STATUS_COLORS: Dict[str, str] = {
    "pending": "#475569",
    "ready": "#06b6d4",
    "in_progress": "#f59e0b",
    "completed": "#22c55e",
    "failed": "#ef4444",
}

STATUS_LABELS: Dict[str, str] = {
    "pending": "PENDING",
    "ready": "READY",
    "in_progress": "IN PROGRESS",
    "completed": "DONE",
    "failed": "FAILED",
}

AGENT_STATUS_COLORS: Dict[str, str] = {
    "idle": "#06b6d4",
    "working": "#f59e0b",
    "failed": "#ef4444",
    "offline": "#64748b",
}


# ── Dashboard CSS ──

DASHBOARD_CSS = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap');

.gradio-container {
    background: #0a0f1a !important;
    font-family: 'Inter', system-ui, sans-serif !important;
}

.mc-dashboard {
    background: #0a0f1a;
    color: #e2e8f0;
    font-family: 'Inter', system-ui, sans-serif;
    padding: 0;
    min-height: 600px;
    background-image:
        linear-gradient(rgba(59,130,246,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(59,130,246,0.03) 1px, transparent 1px);
    background-size: 24px 24px;
    border-radius: 12px;
    overflow: hidden;
}

.mc-header {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    padding: 16px 24px;
    border-bottom: 1px solid rgba(59,130,246,0.2);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}

.mc-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: 700;
    color: #3b82f6;
    letter-spacing: 2px;
    text-transform: uppercase;
}

.mc-task-name {
    font-size: 13px;
    color: #94a3b8;
    font-family: 'JetBrains Mono', monospace;
}

/* ── Metrics Bar ── */
.mc-metrics {
    display: flex;
    gap: 12px;
    padding: 12px 24px;
    background: #0f172a;
    border-bottom: 1px solid rgba(59,130,246,0.1);
    flex-wrap: wrap;
}

.mc-pill {
    display: flex;
    align-items: center;
    gap: 8px;
    background: #1e293b;
    border-radius: 20px;
    padding: 6px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    border: 1px solid rgba(255,255,255,0.06);
}

.mc-pill-label {
    color: #64748b;
    font-weight: 500;
}

.mc-pill-value {
    color: #e2e8f0;
    font-weight: 700;
}

.mc-pill-bar {
    width: 60px;
    height: 4px;
    background: #334155;
    border-radius: 2px;
    overflow: hidden;
}

.mc-pill-bar-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.4s ease;
}

/* ── Main Content Grid ── */
.mc-body {
    display: grid;
    grid-template-columns: 1fr 280px;
    gap: 0;
    min-height: 420px;
}

.mc-dag-panel {
    padding: 20px;
    overflow: auto;
    border-right: 1px solid rgba(59,130,246,0.1);
}

.mc-side-panel {
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow-y: auto;
    max-height: 500px;
}

/* ── DAG SVG ── */
.mc-dag-panel svg {
    max-width: 100%;
    height: auto;
}

@keyframes pulse-node {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}

@keyframes flow-edge {
    to { stroke-dashoffset: -12; }
}

.node-in_progress { animation: pulse-node 1.5s ease-in-out infinite; }
.edge-active { animation: flow-edge 0.8s linear infinite; }

/* ── Agent Cards ── */
.mc-agent-section {
    padding: 12px 16px;
    border-bottom: 1px solid rgba(59,130,246,0.08);
}

.mc-section-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 700;
    color: #3b82f6;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 10px;
}

.mc-agent-card {
    background: #111827;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 6px;
    border: 1px solid rgba(255,255,255,0.04);
    transition: border-color 0.3s;
}

.mc-agent-card:hover {
    border-color: rgba(59,130,246,0.3);
}

.mc-agent-name {
    font-weight: 600;
    font-size: 12px;
    color: #e2e8f0;
    display: flex;
    align-items: center;
    gap: 6px;
}

.mc-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}

.mc-agent-meta {
    font-size: 10px;
    color: #64748b;
    margin-top: 4px;
    font-family: 'JetBrains Mono', monospace;
}

.mc-agent-task {
    font-size: 10px;
    color: #f59e0b;
    margin-top: 3px;
    font-style: italic;
}

.mc-cap-tag {
    display: inline-block;
    background: #1e293b;
    border-radius: 4px;
    padding: 1px 5px;
    font-size: 9px;
    color: #94a3b8;
    margin-right: 3px;
    margin-top: 3px;
    font-family: 'JetBrains Mono', monospace;
}

/* ── Event Log ── */
.mc-log-section {
    padding: 12px 16px;
    flex: 1;
}

.mc-log-entry {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    padding: 4px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    color: #94a3b8;
}

.mc-log-error { color: #ef4444; }
.mc-log-hint { color: #06b6d4; }
.mc-log-success { color: #22c55e; }

/* ── Hint Banner ── */
.mc-hint {
    background: linear-gradient(90deg, rgba(6,182,212,0.1), rgba(6,182,212,0.02));
    border-left: 3px solid #06b6d4;
    padding: 10px 16px;
    font-size: 12px;
    color: #06b6d4;
    font-family: 'JetBrains Mono', monospace;
}

/* ── Welcome Screen ── */
.mc-welcome {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 500px;
    text-align: center;
    color: #475569;
    gap: 16px;
}

.mc-welcome-icon {
    font-size: 48px;
    opacity: 0.3;
}

.mc-welcome-text {
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    letter-spacing: 1px;
}
"""


# ── DAG Layout Algorithm ──


def _compute_layers(subtasks: List[Dict[str, Any]]) -> Dict[str, int]:
    """Assign each subtask to a layer (depth) via BFS from roots."""
    dep_map: Dict[str, List[str]] = {}
    all_ids: List[str] = []
    for s in subtasks:
        sid = s.get("id", s.get("subtask_id", ""))
        deps = s.get("dependencies", [])
        dep_map[sid] = deps
        all_ids.append(sid)

    # Find roots (no dependencies)
    roots = [sid for sid in all_ids if not dep_map.get(sid)]
    layers: Dict[str, int] = {}
    queue: deque[str] = deque()
    for r in roots:
        layers[r] = 0
        queue.append(r)

    # BFS — assign max depth
    children: Dict[str, List[str]] = defaultdict(list)
    for sid in all_ids:
        for dep in dep_map.get(sid, []):
            children[dep].append(sid)

    while queue:
        node = queue.popleft()
        for child in children[node]:
            new_depth = layers[node] + 1
            if child not in layers or new_depth > layers[child]:
                layers[child] = new_depth
                queue.append(child)

    # Assign any orphans
    for sid in all_ids:
        if sid not in layers:
            layers[sid] = 0

    return layers


def _render_dag_svg(subtasks: List[Dict[str, Any]]) -> str:
    """Render the subtask DAG as an inline SVG with status-colored nodes."""
    if not subtasks:
        return "<div style='color:#64748b;text-align:center;padding:40px;'>No subtasks</div>"

    layers = _compute_layers(subtasks)
    subtask_map: Dict[str, Dict[str, Any]] = {}
    for s in subtasks:
        sid = s.get("id", s.get("subtask_id", ""))
        subtask_map[sid] = s

    # Group by layer
    layer_groups: Dict[int, List[str]] = defaultdict(list)
    for sid, layer in layers.items():
        layer_groups[layer].append(sid)

    max_layer = max(layers.values()) if layers else 0
    max_per_layer = max(len(g) for g in layer_groups.values()) if layer_groups else 1

    # Layout constants
    node_w, node_h = 120, 44
    h_gap, v_gap = 160, 60
    pad_x, pad_y = 40, 30

    svg_w = (max_layer + 1) * h_gap + pad_x * 2
    svg_h = max_per_layer * v_gap + pad_y * 2

    # Compute node positions
    positions: Dict[str, tuple[float, float]] = {}
    for layer_idx in range(max_layer + 1):
        nodes_in_layer = layer_groups.get(layer_idx, [])
        n = len(nodes_in_layer)
        total_height = (n - 1) * v_gap
        start_y = (svg_h - total_height) / 2
        for i, sid in enumerate(nodes_in_layer):
            x = pad_x + layer_idx * h_gap
            y = start_y + i * v_gap
            positions[sid] = (x, y)

    # Build SVG
    elements: List[str] = []

    # Defs for arrow marker and glow filter
    elements.append("""
    <defs>
        <marker id="arrow" viewBox="0 0 10 6" refX="10" refY="3"
                markerWidth="8" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 3 L 0 6 z" fill="#334155"/>
        </marker>
        <filter id="glow-ready">
            <feGaussianBlur stdDeviation="3" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <filter id="glow-progress">
            <feGaussianBlur stdDeviation="4" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
    </defs>
    """)

    # Draw edges
    for sid, s in subtask_map.items():
        deps = s.get("dependencies", [])
        sx, sy = positions.get(sid, (0, 0))
        for dep in deps:
            if dep in positions:
                dx, dy = positions[dep]
                dep_status = subtask_map.get(dep, {}).get("status", "pending")
                edge_color = "#334155"
                edge_class = ""
                if dep_status == "completed":
                    edge_color = "#22c55e"
                elif dep_status == "in_progress":
                    edge_color = "#f59e0b"
                    edge_class = "edge-active"
                elements.append(
                    f'<line class="{edge_class}" '
                    f'x1="{dx + node_w}" y1="{dy + node_h/2}" '
                    f'x2="{sx}" y2="{sy + node_h/2}" '
                    f'stroke="{edge_color}" stroke-width="2" '
                    f'stroke-dasharray="6 6" '
                    f'marker-end="url(#arrow)" opacity="0.7"/>'
                )

    # Draw nodes
    for sid, (x, y) in positions.items():
        s = subtask_map.get(sid, {})
        status = s.get("status", "pending")
        color = STATUS_COLORS.get(status, "#475569")
        label = sid.replace("_", " ")
        if len(label) > 16:
            label = label[:14] + ".."

        assigned = s.get("assigned_to", "")
        steps_rem = s.get("steps_remaining")

        node_filter = ""
        node_class = ""
        if status == "ready":
            node_filter = 'filter="url(#glow-ready)"'
        elif status == "in_progress":
            node_filter = 'filter="url(#glow-progress)"'
            node_class = f'class="node-{status}"'

        # Node rectangle
        elements.append(
            f'<g {node_class}>'
            f'<rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" '
            f'rx="8" ry="8" fill="{color}" {node_filter} opacity="0.9"/>'
            f'<text x="{x + node_w/2}" y="{y + 18}" '
            f'text-anchor="middle" fill="white" font-size="10" '
            f'font-family="JetBrains Mono, monospace" font-weight="600">'
            f'{label}</text>'
        )

        # Status label
        status_text = STATUS_LABELS.get(status, status.upper())
        elements.append(
            f'<text x="{x + node_w/2}" y="{y + 33}" '
            f'text-anchor="middle" fill="rgba(255,255,255,0.6)" font-size="8" '
            f'font-family="JetBrains Mono, monospace">'
            f'{status_text}</text>'
        )

        # Agent assignment annotation
        if assigned and status == "in_progress":
            remaining_text = f" ({steps_rem}t)" if steps_rem is not None else ""
            elements.append(
                f'<text x="{x + node_w/2}" y="{y + node_h + 14}" '
                f'text-anchor="middle" fill="#f59e0b" font-size="9" '
                f'font-family="JetBrains Mono, monospace" font-style="italic">'
                f'{assigned}{remaining_text}</text>'
            )

        elements.append("</g>")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {svg_w} {svg_h + 20}" '
        f'width="100%" height="{svg_h + 20}">'
        f'{"".join(elements)}</svg>'
    )


# ── Agent Cards ──


def _render_agent_cards(agents: List[Dict[str, Any]]) -> str:
    """Render agent pool as compact HTML cards."""
    if not agents:
        return ""

    cards: List[str] = []
    for a in agents:
        name = a.get("name", "?")
        status = a.get("status", "idle")
        color = AGENT_STATUS_COLORS.get(status, "#64748b")
        caps = a.get("capabilities", [])
        current = a.get("current_task")
        speed = a.get("speed", 1)
        cost = a.get("cost_per_step", 1.0)
        rel = a.get("reliability", 1.0)

        cap_tags = "".join(f'<span class="mc-cap-tag">{c}</span>' for c in caps)

        task_line = ""
        if current:
            task_line = f'<div class="mc-agent-task">working on: {current}</div>'

        cards.append(f"""
        <div class="mc-agent-card">
            <div class="mc-agent-name">
                <span class="mc-status-dot" style="background:{color};
                    box-shadow:0 0 6px {color};"></span>
                {name}
                <span style="color:{color};font-size:10px;margin-left:auto;">
                    {status.upper()}</span>
            </div>
            <div class="mc-agent-meta">spd={speed} cost={cost:.1f} rel={rel:.0%}</div>
            <div>{cap_tags}</div>
            {task_line}
        </div>
        """)

    return (
        f'<div class="mc-agent-section">'
        f'<div class="mc-section-title">Agent Pool</div>'
        f'{"".join(cards)}'
        f'</div>'
    )


# ── Metrics Bar ──


def _render_metrics_bar(obs: Dict[str, Any]) -> str:
    """Render the top metrics bar with pill indicators."""
    time_elapsed = obs.get("time_elapsed", 0)
    time_remaining = obs.get("time_remaining", 0)
    time_total = time_elapsed + time_remaining
    time_pct = (time_elapsed / max(1, time_total)) * 100

    budget_used = obs.get("budget_used", 0)
    budget_remaining = obs.get("budget_remaining")
    budget_total = budget_used + (budget_remaining or 0) if budget_remaining is not None else None

    active = obs.get("active_task_count", 0)
    capacity = obs.get("capacity_limit", 3)

    reward = obs.get("reward", 0)
    reward_color = "#22c55e" if reward and reward > 0.05 else "#ef4444" if reward and reward < 0 else "#64748b"

    failures_occurred = obs.get("failures_occurred", 0)
    failures_recovered = obs.get("failures_recovered", 0)

    done = obs.get("done", False)

    pills: List[str] = []

    # Time pill
    time_color = "#22c55e" if time_pct < 60 else "#f59e0b" if time_pct < 85 else "#ef4444"
    pills.append(f"""
    <div class="mc-pill">
        <span class="mc-pill-label">STEP</span>
        <span class="mc-pill-value">{time_elapsed}/{time_total}</span>
        <div class="mc-pill-bar">
            <div class="mc-pill-bar-fill" style="width:{time_pct:.0f}%;background:{time_color};"></div>
        </div>
    </div>
    """)

    # Budget pill
    if budget_total is not None and budget_total > 0:
        budget_pct = (budget_used / budget_total) * 100
        budget_color = "#22c55e" if budget_pct < 60 else "#f59e0b" if budget_pct < 85 else "#ef4444"
        pills.append(f"""
        <div class="mc-pill">
            <span class="mc-pill-label">BUDGET</span>
            <span class="mc-pill-value">{budget_used:.1f}/{budget_total:.1f}</span>
            <div class="mc-pill-bar">
                <div class="mc-pill-bar-fill" style="width:{budget_pct:.0f}%;background:{budget_color};"></div>
            </div>
        </div>
        """)

    # Capacity pill
    cap_pct = (active / max(1, capacity)) * 100
    cap_color = "#22c55e" if cap_pct < 70 else "#f59e0b" if cap_pct < 100 else "#ef4444"
    pills.append(f"""
    <div class="mc-pill">
        <span class="mc-pill-label">CAPACITY</span>
        <span class="mc-pill-value" style="color:{cap_color};">{active}/{capacity}</span>
    </div>
    """)

    # Reward pill
    reward_val = f"{reward:.2f}" if reward else "—"
    pills.append(f"""
    <div class="mc-pill">
        <span class="mc-pill-label">REWARD</span>
        <span class="mc-pill-value" style="color:{reward_color};">{reward_val}</span>
    </div>
    """)

    # Failures pill
    if failures_occurred > 0:
        pills.append(f"""
        <div class="mc-pill">
            <span class="mc-pill-label">FAILURES</span>
            <span class="mc-pill-value" style="color:#ef4444;">
                {failures_occurred}
                <span style="color:#22c55e;">/{failures_recovered} recovered</span>
            </span>
        </div>
        """)

    # Done indicator
    if done:
        pills.append("""
        <div class="mc-pill" style="border-color:rgba(34,197,94,0.4);">
            <span class="mc-pill-value" style="color:#22c55e;">EPISODE COMPLETE</span>
        </div>
        """)

    return f'<div class="mc-metrics">{"".join(pills)}</div>'


# ── Event Log ──


def _render_event_log(
    errors: List[str], hint: Optional[str], available_actions: List[str]
) -> str:
    """Render the event log and hint panel."""
    entries: List[str] = []

    if hint:
        entries.append(
            f'<div class="mc-log-entry mc-log-hint">HINT: {hint}</div>'
        )

    for err in errors:
        entries.append(
            f'<div class="mc-log-entry mc-log-error">ERROR: {err}</div>'
        )

    if available_actions:
        actions_str = ", ".join(available_actions)
        entries.append(
            f'<div class="mc-log-entry">Available: {actions_str}</div>'
        )

    if not entries:
        entries.append(
            '<div class="mc-log-entry" style="color:#334155;">Waiting for actions...</div>'
        )

    return (
        f'<div class="mc-log-section">'
        f'<div class="mc-section-title">Status Log</div>'
        f'{"".join(entries)}'
        f'</div>'
    )


# ── Full Dashboard ──


def _build_full_dashboard(obs_data: Dict[str, Any]) -> str:
    """Combine all sections into the full Mission Control dashboard HTML."""
    obs = obs_data.get("observation", obs_data)

    task_desc = obs.get("task_description", "")
    # Truncate for header
    task_short = task_desc[:80] + "..." if len(task_desc) > 80 else task_desc

    subtasks = obs.get("subtasks", [])
    agents = obs.get("agents", [])
    errors = obs.get("errors", [])
    hint = obs.get("hint")
    available = obs.get("available_actions", [])

    metrics_html = _render_metrics_bar(obs)
    dag_html = _render_dag_svg(subtasks)
    agents_html = _render_agent_cards(agents)
    log_html = _render_event_log(errors, hint, available)

    # SLA milestones
    sla_milestones = obs.get("sla_milestones")
    sla_html = ""
    if sla_milestones:
        time_elapsed = obs.get("time_elapsed", 0)
        sla_items: List[str] = []
        for subtask_id, deadline in sla_milestones.items():
            name = subtask_id.replace("_", " ")
            if time_elapsed > deadline:
                sla_items.append(
                    f'<span style="color:#ef4444;">{name} (due step {deadline}) MISSED</span>'
                )
            elif time_elapsed >= deadline - 2:
                sla_items.append(
                    f'<span style="color:#f59e0b;">{name} (due step {deadline}) URGENT</span>'
                )
            else:
                sla_items.append(
                    f'<span style="color:#64748b;">{name} by step {deadline}</span>'
                )
        sla_html = (
            f'<div class="mc-hint" style="border-left-color:#f59e0b;'
            f'background:linear-gradient(90deg,rgba(245,158,11,0.08),transparent);">'
            f'SLA: {" | ".join(sla_items)}'
            f'</div>'
        )

    # Hint banner
    hint_html = ""
    if hint:
        hint_html = f'<div class="mc-hint">{hint}</div>'

    return f"""
    <div class="mc-dashboard">
        <div class="mc-header">
            <span class="mc-title">Mission Control</span>
            <span class="mc-task-name">{task_short}</span>
        </div>
        {metrics_html}
        {sla_html}
        {hint_html}
        <div class="mc-body">
            <div class="mc-dag-panel">
                <div class="mc-section-title">Workflow DAG</div>
                {dag_html}
            </div>
            <div class="mc-side-panel">
                {agents_html}
                {log_html}
            </div>
        </div>
    </div>
    """


def _build_welcome_screen() -> str:
    """Render the initial welcome screen before reset."""
    return """
    <div class="mc-dashboard">
        <div class="mc-welcome">
            <div class="mc-welcome-icon">&#9651;</div>
            <div class="mc-welcome-text">WORKFLOW ORCHESTRATOR</div>
            <div style="color:#334155;font-size:12px;">
                Select a task and click Reset to begin
            </div>
        </div>
    </div>
    """


# ── Gradio Builder ──


def build_orchestrator_gradio_app(
    web_manager: Any,
    action_fields: List[Dict[str, Any]],
    metadata: Optional[EnvironmentMetadata],
    is_chat_env: bool,
    title: str,
    quick_start_md: str,
) -> gr.Blocks:
    """Build the custom Mission Control dashboard tab for the Workflow Orchestrator.

    Signature matches the ``gradio_builder`` contract required by
    ``openenv.core.env_server.http_server.create_app()``.
    """

    with gr.Blocks(
        title="Workflow Orchestrator — Mission Control",
    ) as blocks:
        # State
        obs_state = gr.State(value={})
        step_log = gr.State(value=[])

        # ── Controls ──
        with gr.Row():
            task_dd = gr.Dropdown(
                choices=["easy", "medium", "hard", "expert"],
                value="easy",
                label="Task",
                scale=1,
            )
            action_dd = gr.Dropdown(
                choices=["delegate", "retry", "wait", "synthesize", "abort"],
                value="wait",
                label="Action",
                scale=1,
            )
            subtask_dd = gr.Dropdown(
                choices=[],
                label="Subtask",
                interactive=True,
                scale=1,
            )
            agent_dd = gr.Dropdown(
                choices=[],
                label="Agent",
                interactive=True,
                scale=1,
            )

        with gr.Row():
            reset_btn = gr.Button("Reset", variant="primary", scale=1)
            step_btn = gr.Button("Step", variant="secondary", scale=1)
            status_text = gr.Markdown(
                value="*Select a task and click Reset to begin.*",
            )

        # ── Dashboard ──
        dashboard = gr.HTML(value=_build_welcome_screen())

        # ── Raw JSON (collapsed) ──
        with gr.Accordion("Raw Observation JSON", open=False):
            raw_json = gr.Code(language="json", value="{}", label="Response")

        # ── Event handlers ──

        async def do_reset(task_id: str) -> tuple:
            """Reset environment and return updated dashboard."""
            try:
                data = await web_manager.reset_environment({"task_id": task_id})
                obs = data.get("observation", {})
                html = _build_full_dashboard(data)

                # Extract choices for dropdowns
                subtask_choices = [
                    s.get("id", s.get("subtask_id", ""))
                    for s in obs.get("subtasks", [])
                    if s.get("status") in ("ready", "failed")
                ]
                agent_choices = [
                    a.get("name", "")
                    for a in obs.get("agents", [])
                    if a.get("status") == "idle"
                ]

                return (
                    html,
                    data,
                    [],
                    gr.update(choices=subtask_choices, value=subtask_choices[0] if subtask_choices else None),
                    gr.update(choices=agent_choices, value=agent_choices[0] if agent_choices else None),
                    f"*Reset complete — **{task_id}** task loaded.*",
                    json.dumps(data, indent=2),
                )
            except Exception as e:
                return (
                    _build_welcome_screen(),
                    {},
                    [],
                    gr.update(choices=[]),
                    gr.update(choices=[]),
                    f"**Error:** {e}",
                    "{}",
                )

        async def do_step(
            action_type: str,
            subtask_id: Optional[str],
            agent_name: Optional[str],
            current_obs: Dict[str, Any],
            current_log: List[str],
        ) -> tuple:
            """Execute one step and return updated dashboard."""
            action: Dict[str, Any] = {"action_type": action_type}
            if subtask_id and action_type in ("delegate", "retry", "abort"):
                action["subtask_id"] = subtask_id
            if agent_name and action_type in ("delegate", "retry"):
                action["agent_name"] = agent_name

            try:
                data = await web_manager.step_environment(action)
                obs = data.get("observation", {})
                html = _build_full_dashboard(data)

                # Update log
                reward = data.get("reward", obs.get("reward", 0))
                done = data.get("done", obs.get("done", False))
                action_str = action_type
                if subtask_id and action_type in ("delegate", "retry", "abort"):
                    action_str += f"({subtask_id}"
                    if agent_name and action_type in ("delegate", "retry"):
                        action_str += f", {agent_name}"
                    action_str += ")"

                new_log = current_log + [
                    f"Step {obs.get('time_elapsed', '?')}: {action_str} → reward={reward:.2f}"
                ]

                # Extract updated choices
                subtask_choices = [
                    s.get("id", s.get("subtask_id", ""))
                    for s in obs.get("subtasks", [])
                    if s.get("status") in ("ready", "failed")
                ]
                agent_choices = [
                    a.get("name", "")
                    for a in obs.get("agents", [])
                    if a.get("status") == "idle"
                ]

                status = f"*Step complete — reward: **{reward:.2f}***"
                if done:
                    status = "**Episode complete!** Reset to start a new episode."

                return (
                    html,
                    data,
                    new_log,
                    gr.update(choices=subtask_choices, value=subtask_choices[0] if subtask_choices else None),
                    gr.update(choices=agent_choices, value=agent_choices[0] if agent_choices else None),
                    status,
                    json.dumps(data, indent=2),
                )
            except Exception as e:
                return (
                    _build_full_dashboard(current_obs) if current_obs else _build_welcome_screen(),
                    current_obs,
                    current_log,
                    gr.update(),
                    gr.update(),
                    f"**Error:** {e}",
                    "{}",
                )

        reset_btn.click(
            fn=do_reset,
            inputs=[task_dd],
            outputs=[dashboard, obs_state, step_log, subtask_dd, agent_dd, status_text, raw_json],
        )

        step_btn.click(
            fn=do_step,
            inputs=[action_dd, subtask_dd, agent_dd, obs_state, step_log],
            outputs=[dashboard, obs_state, step_log, subtask_dd, agent_dd, status_text, raw_json],
        )

    return blocks
