"""inference.py — Baseline inference for Workflow Orchestrator Environment.

MANDATORY STDOUT FORMAT:
    [START] task=<task_name> env=workflow_orchestrator model=<model_name>
    [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> score=<0.000> rewards=<r1,r2,...,rn>

Runs a free HF-hosted model against all 3 tasks and reports scores.
Requires HF_TOKEN (or API_KEY), API_BASE_URL, and MODEL_NAME environment variables.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI

from client import OrchestratorClient
from models import OrchestratorAction, OrchestratorObservation

# ── Load .env file if present ──

_env_path: Path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── Configuration (hackathon-mandated env vars) ──

API_BASE_URL: str = os.getenv("API_BASE_URL") or "https://router.huggingface.co/v1"
API_KEY: str = os.getenv("API_KEY") or os.getenv("HF_TOKEN") or ""
MODEL_NAME: str = os.getenv("MODEL_NAME") or "Qwen/Qwen3-32B"
IMAGE_NAME: Optional[str] = os.getenv("IMAGE_NAME")
ENV_URL: str = os.getenv("ENV_URL") or "http://localhost:8000"
BENCHMARK: str = "workflow_orchestrator"
TEMPERATURE: float = 0.0
MAX_TOKENS: int = 4096  # High ceiling for verbose models; concise models just use fewer tokens
MAX_STEPS: int = 50
SUCCESS_SCORE_THRESHOLD: float = 0.1
TASK_TIMEOUT_S: int = 600  # 10 min per task; total 4 tasks fits in 20 min hackathon limit
HISTORY_WINDOW: int = 6  # Last 6 turns — expert task needs longer context to avoid repeating mistakes

VALID_ACTIONS: set[str] = {"delegate", "retry", "wait", "synthesize", "abort"}

llm: OpenAI = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

# Model-agnostic system prompt — no Qwen-specific /no_think, JSON-first structure
SYSTEM_PROMPT: str = """OUTPUT FORMAT: Respond with ONLY a single JSON object. No explanations, no reasoning text, no markdown.

You are a workflow orchestrator managing specialist agents to complete a DAG of subtasks.

ACTIONS (as JSON):
{"action_type": "delegate", "subtask_id": "<id>", "agent_name": "<name>"}
{"action_type": "retry", "subtask_id": "<id>", "agent_name": "<name>"}
{"action_type": "wait"}
{"action_type": "synthesize"}
{"action_type": "abort", "subtask_id": "<id>"}

DECISION PROCEDURE (follow this exact order):
1. If ALL subtasks are COMPLETED → synthesize immediately (unless you need monitoring waits).
2. If any subtask is FAILED → retry it NOW with a capable IDLE agent.
   CRITICAL: If error says "permanent failure" or "lacks required tooling", the SAME agent will ALWAYS fail. You MUST pick a DIFFERENT agent with the same capability. Never retry the same agent on a permanent failure.
3. If any subtask is READY and a capable IDLE agent exists → delegate it.
   - When MULTIPLE subtasks are READY, delegate them ALL across consecutive steps before waiting.
   - Prefer cheaper agents (lower cost_per_step) when multiple agents can do the same task.
4. ONLY wait when no subtasks are READY or all capable agents are busy working.
5. After validate_fix completes, wait 2 steps for monitoring before synthesizing.

KEY PRINCIPLES:
- MAXIMIZE PARALLELISM: If 3 subtasks are ready and 3 agents are idle, delegate all 3 in 3 consecutive steps.
- NEVER wait when there is a READY subtask and an IDLE capable agent — this wastes a step.
- Check the HINT line — it tells you what to do next.
- Match subtask TYPE to agent CAPABILITIES (not just any agent).

Respond with a single JSON object. Nothing else."""


# ── Mandatory stdout logging ──


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val: str = error if error else "null"
    done_val: str = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str: str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ── Observation formatting ──


def format_observation(obs: OrchestratorObservation) -> str:
    """Format observation as structured text for LLM consumption.

    NOTE: obs.done and obs.reward are defaults on the client side
    (the real values live on StepResult). This function only formats
    workflow state — subtasks, agents, budget, etc.
    """
    lines: List[str] = []
    time_total: int = obs.time_elapsed + obs.time_remaining

    budget_str: str = ""
    if obs.budget_remaining is not None:
        budget_total: float = obs.budget_used + obs.budget_remaining
        budget_str = f" | Budget: {obs.budget_used:.1f}/{budget_total:.1f} used"

    lines.append("=== WORKFLOW STATUS ===")
    lines.append(f"Task: {obs.task_description}")
    lines.append(
        f"Step: {obs.time_elapsed}/{time_total} | "
        f"Active: {obs.active_task_count}/{obs.capacity_limit}{budget_str}"
    )

    # SLA milestones (critical deadlines for hard/expert tasks)
    if obs.sla_milestones:
        milestones_str: str = ", ".join(
            f"{k} by step {v}" for k, v in obs.sla_milestones.items()
        )
        lines.append(f"SLA Deadlines: {milestones_str}")

    # Failure tracking
    if obs.failures_occurred > 0:
        lines.append(
            f"Failures: {obs.failures_occurred} occurred, "
            f"{obs.failures_recovered} recovered"
        )

    # Hint at top for visibility (verbose models may not read to the end)
    if obs.hint:
        lines.append(f">>> HINT: {obs.hint}")
    lines.append("")

    # Subtasks
    lines.append("-- SUBTASKS --")
    for s in obs.subtasks:
        label: str = s.status.upper()
        if s.status == "pending" and not s.dependencies_met:
            label = "BLOCKED"

        detail: str = ""
        if s.status == "completed" and s.output:
            detail = f' -> "{s.output}"'
        elif s.status == "in_progress" and s.assigned_to:
            detail = f" assigned to: {s.assigned_to}"
            if s.steps_remaining is not None:
                detail += f" ({s.steps_remaining} step(s) left)"
        elif s.status == "failed" and s.error:
            detail = f' ERROR: "{s.error}" (attempt {s.attempt_count})'
        elif s.dependencies:
            deps: str = ", ".join(s.dependencies)
            met: str = "met" if s.dependencies_met else "not met"
            detail = f" deps: [{deps}] ({met})"

        lines.append(f"  [{label:12s}] {s.id} (type: {s.type}){detail}")
    lines.append("")

    # Agents
    lines.append("-- AGENTS --")
    for a in obs.agents:
        caps: str = ", ".join(a.capabilities)
        task_info: str = f" | working on: {a.current_task}" if a.current_task else ""
        lines.append(
            f"  [{a.status:8s}] {a.name} ({caps}) "
            f"speed={a.speed} cost={a.cost_per_step:.1f} rel={a.reliability:.2f}{task_info}"
        )
    lines.append("")

    # Errors
    if obs.errors:
        lines.append("-- ERRORS --")
        for e in obs.errors:
            lines.append(f"  ! {e}")
        lines.append("")

    # Available actions
    lines.append(f"Available actions: {', '.join(obs.available_actions)}")

    return "\n".join(lines)


# ── Action parsing ──


def _is_valid_action(parsed: Dict[str, Any]) -> bool:
    """Check if a parsed action dict has a valid action_type and non-placeholder values."""
    if not isinstance(parsed, dict):
        return False
    if parsed.get("action_type") not in VALID_ACTIONS:
        return False

    # Reject placeholder values (Nemotron outputs "...", "<id>", "<name>" etc.)
    placeholder_patterns: set[str] = {"...", "<id>", "<name>", "id", "name", ""}
    for key in ("subtask_id", "agent_name"):
        val = parsed.get(key)
        if val is not None and not isinstance(val, str):
            parsed[key] = None  # Non-string values (int, bool, etc.)
        elif val is not None and (
            val in placeholder_patterns
            or val.startswith("<")
            or val.startswith("...")
        ):
            parsed[key] = None  # Clear placeholder, let validation catch it

    return True


def parse_llm_action(response_text: str) -> Dict[str, Any]:
    """Parse LLM response into action dict. Falls back to wait on failure.

    Handles: direct JSON, <think> tags, markdown code blocks, embedded JSON in reasoning text.
    Rejects placeholder values like "..." or "<id>" that verbose models produce.
    """
    if not response_text:
        return {"action_type": "wait"}

    text: str = response_text.strip()

    # Strip <think>...</think> tags (Qwen3 thinking mode)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Try direct JSON parse
    try:
        parsed: Dict[str, Any] = json.loads(text)
        if _is_valid_action(parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from markdown code block
    code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_match:
        try:
            parsed = json.loads(code_match.group(1))
            if _is_valid_action(parsed):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Try extracting JSON object containing action_type (handles reasoning + JSON)
    for json_match in re.finditer(r"\{[^{}]*\"action_type\"[^{}]*\}", text):
        try:
            parsed = json.loads(json_match.group(0))
            if _is_valid_action(parsed):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue

    # Last resort: try any JSON-like object
    json_match = re.search(r"\{[^{}]*\}", text)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if _is_valid_action(parsed):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    return {"action_type": "wait"}


def _call_llm(messages: List[Dict[str, str]]) -> str:
    """Synchronous LLM call with retry — designed to be run via asyncio.to_thread()."""
    import time

    for attempt in range(2):
        try:
            completion = llm.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                stream=False,
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            print(f"[DEBUG] LLM call failed (attempt {attempt + 1}): {exc}", flush=True)
            if attempt == 0:
                time.sleep(2)
    return ""


# ── Task runner ──


async def run_task(task_id: str, env: OrchestratorClient) -> float:
    """Run a single task episode with mandatory stdout logging.

    Uses conversation history (sliding window) so the LLM can track its
    prior actions and make coherent multi-step decisions.
    """
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    steps_taken: int = 0
    score: float = 0.01
    success: bool = False

    # Conversation history: sliding window of recent turns
    history: List[Dict[str, str]] = []

    try:
        result = await env.reset(task_id=task_id)

        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break

            obs_text: str = format_observation(result.observation)

            # Build messages: system + recent history + current observation
            history.append({"role": "user", "content": obs_text})

            # Trim history to sliding window (keep last N user+assistant pairs)
            if len(history) > HISTORY_WINDOW * 2:
                history = history[-(HISTORY_WINDOW * 2):]

            messages: List[Dict[str, str]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history,
            ]

            # Async-safe LLM call: run sync OpenAI client in thread pool
            # to avoid blocking the event loop (prevents WebSocket keepalive timeout)
            raw_response: str = await asyncio.to_thread(_call_llm, messages)

            action_dict: Dict[str, Any] = parse_llm_action(raw_response)

            # Add assistant response to history
            action_json: str = json.dumps(action_dict)
            history.append({"role": "assistant", "content": action_json})

            action_type: str = action_dict.get("action_type", "wait")
            subtask_id: Optional[str] = action_dict.get("subtask_id")
            agent_name: Optional[str] = action_dict.get("agent_name")

            action: OrchestratorAction = OrchestratorAction(
                action_type=action_type,
                subtask_id=subtask_id,
                agent_name=agent_name,
            )

            # Format action string for logging
            parts: List[str] = [action_type]
            if subtask_id:
                parts.append(subtask_id)
            if agent_name:
                parts.append(agent_name)
            action_str: str = f"{parts[0]}({','.join(parts[1:])})"

            result = await env.step(action)

            reward: float = max(0.01, min(0.99, result.reward or 0.0))
            done: bool = result.done
            error: Optional[str] = None
            if result.observation.errors:
                error = result.observation.errors[0]

            rewards.append(reward)
            steps_taken = step

            log_step(step=step, action=action_str, reward=reward, done=done, error=error)

            if done:
                break

        # Get graded score via HTTP (custom endpoint, not WebSocket)
        try:
            async with httpx.AsyncClient(base_url=ENV_URL, timeout=60.0) as http:
                grade_resp = await http.post("/grader", json={"task_id": task_id})
                grade_resp.raise_for_status()
                grade_data: Dict[str, Any] = grade_resp.json()
            score = grade_data.get("score", 0.01)
        except Exception as exc:
            print(f"[DEBUG] Grader call failed: {exc}", flush=True)
            score = 0.01

        success = score >= SUCCESS_SCORE_THRESHOLD

    finally:
        # Safety clamp: ensure score is strictly in (0, 1) for Phase 2 validation
        score = max(0.01, min(0.99, score))
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


# ── Main ──


async def main() -> None:
    """Run all 4 tasks sequentially and report scores."""
    if IMAGE_NAME:
        env: OrchestratorClient = await OrchestratorClient.from_docker_image(IMAGE_NAME)
    else:
        env = OrchestratorClient(base_url=ENV_URL)

    scores: Dict[str, float] = {}

    try:
        for task_id in ["easy", "medium", "hard", "expert"]:
            try:
                scores[task_id] = await asyncio.wait_for(
                    run_task(task_id, env),
                    timeout=TASK_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                print(f"[DEBUG] Task {task_id} timed out after {TASK_TIMEOUT_S}s", flush=True)
                scores[task_id] = 0.01
                # Don't call log_end here — run_task's finally block already emits [END]
    finally:
        try:
            await env.close()
        except Exception as exc:
            print(f"[DEBUG] env.close() error: {exc}", flush=True)

    print(f"\nFinal scores: {json.dumps(scores, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
