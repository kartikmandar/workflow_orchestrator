---
title: Workflow Orchestrator Environment Server
emoji: 🎰
colorFrom: purple
colorTo: yellow
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
---

# Workflow Orchestrator Environment

An OpenEnv environment where an LLM agent acts as a **project coordinator**, managing DAG-based workflows of subtasks across simulated specialist agents with varying capabilities, failure rates, and cost profiles. Tests coordination, delegation, parallelism, failure recovery, and cost management.

## Motivation

Agent orchestration is the #1 enterprise AI trend — yet LLMs are terrible at it. Research documents 14+ failure modes in multi-agent systems (MAST taxonomy), up to 17x error amplification in unstructured networks (Spark to Fire), and only 25% baseline correctness with GPT-4o (ChatDev). This environment provides a controlled, deterministic testbed for training and evaluating LLM orchestration capabilities across three real-world scenarios: software development, CI/CD deployment, and production incident response.

## Action Space

| Field | Type | Description |
|-------|------|-------------|
| `action_type` | `"delegate"\|"retry"\|"wait"\|"synthesize"\|"abort"` | Which action to take |
| `subtask_id` | `Optional[str]` | Target subtask (required for delegate/retry/abort) |
| `agent_name` | `Optional[str]` | Agent to assign (required for delegate/retry) |

**Actions:**
- **delegate**: Assign a ready subtask to an idle, capable agent
- **retry**: Re-assign a failed subtask (same or different agent)
- **wait**: Advance time by 1 step; working agents tick
- **synthesize**: Combine all completed outputs (only valid when all subtasks done)
- **abort**: Permanently fail a non-completed subtask

Invalid actions are accepted but penalized — the step is consumed, a penalty is applied, and state remains unchanged.

## Observation Space

| Field | Type | Description |
|-------|------|-------------|
| `task_description` | `str` | Natural-language task objective |
| `subtasks` | `list[SubtaskInfo]` | Status of each subtask in the DAG |
| `agents` | `list[AgentInfo]` | Status of each simulated agent |
| `completed_outputs` | `dict[str, str]` | Outputs from finished subtasks |
| `errors` | `list[str]` | Errors from the current step |
| `time_remaining` | `int` | Steps left before timeout |
| `time_elapsed` | `int` | Steps taken so far |
| `capacity_limit` | `int` | Max concurrent in-progress tasks |
| `active_task_count` | `int` | Currently in-progress task count |
| `budget_remaining` | `Optional[float]` | Cost budget left (None if unlimited) |
| `budget_used` | `float` | Cost spent so far |
| `available_actions` | `list[str]` | Which action types are currently valid |
| `hint` | `Optional[str]` | One-line suggestion for the agent |
| `done` | `bool` | Whether the episode has ended |
| `reward` | `float\|None` | Step reward |

## Tasks

### Easy: Feature Development Sprint
- **6 subtasks**: technical_design -> implement_backend -> [implement_frontend, write_tests] -> run_tests -> review_and_merge
- **4 agents**: All reliable (1.0), speed=1, cost=1.0
- **Constraints**: time=15, capacity=4, no cost budget
- **Challenge**: Basic delegation ordering + optional parallel fan-out

### Medium: Microservice Deployment Pipeline
- **9 subtasks**: checkout -> [lint, unit_tests, security_scan] -> build -> push -> staging -> smoke_tests -> production
- **5 agents**: Varying speed (1-2), cost (1.0-3.0), reliability
- **Constraints**: time=16, capacity=3, cost_budget=35.0
- **Challenge**: 3-way parallelism, guaranteed security scan failure requiring retry, cost awareness

### Hard: Production Incident Response
- **10 subtasks**: triage -> [enrich_logs, check_dashboards, check_dependencies] -> root_cause -> hotfix -> validate -> monitor + side channels
- **7 agents**: Overlapping capabilities, costs 1.0-5.0
- **Constraints**: time=22, capacity=3, cost_budget=40.0
- **Challenge**: Permanent failure trap (investigator_alpha on enrich_logs), agent dropout at step 12, SLA milestones, conflicting findings, monitoring patience

### Expert (Bonus): Life OS Daily Orchestration
- **14 subtasks**: morning_check_in -> [assess_sleep, assess_career, assess_personal] -> plan_day -> [focus, inbox] -> [deep_work, handle_urgent] -> midday_health -> resolve_conflict -> [afternoon, notify] -> synthesize_report
- **8 agents**: Including 2 permanent failure traps (wellness_monitor, executive_assistant)
- **Constraints**: time=25, capacity=3, cost_budget=55.0
- **Challenge**: Multi-objective optimization across health/career/personal pillars, career_agent speed degradation at step 7, personal_agent dropout at step 10, 3 SLA milestones, 2 conflict resolution points

## Reward Design

Dense per-step rewards with 7 positive and 9 negative signals:

| Signal | Value | Trigger |
|--------|-------|---------|
| correct_delegation | +0.05 | Right agent for right subtask |
| subtask_completed | +0.08 | Agent finishes successfully |
| parallelism_exploited | +0.10 | 2+ tasks concurrent |
| failure_recovered | +0.10 | Retry succeeds after failure |
| efficient_wait | +0.03 | Wait when nothing delegatable |
| dependency_violation | -0.10 | Delegate blocked subtask |
| capacity_violation | -0.15 | Exceed concurrent limit |
| permanent_retry | -0.06 | Retry permanently failing agent |

End-of-episode: +0.20 (all complete + synthesized), +0.10 * time_efficiency, +0.05 * cost_efficiency, -0.10 (incomplete).

## Baseline Scores

| Task | Score | Model |
|------|-------|-------|
| Easy | 0.900 | Qwen/Qwen3-32B |
| Medium | 0.633 | Qwen/Qwen3-32B |
| Hard | 0.808 | Qwen/Qwen3-32B |
| Expert | 0.802 | Qwen/Qwen3-32B |

## Setup

### Local Development

```bash
cd workflow_orchestrator
uv sync
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker build -t workflow-orchestrator .
docker run -p 8000:8000 workflow-orchestrator
```

### Running Inference

```bash
export HF_TOKEN=<your-token>
export API_BASE_URL=https://router.huggingface.co/v1
export MODEL_NAME=Qwen/Qwen3-32B
python inference.py
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/reset` | POST | Reset environment, returns observation |
| `/step` | POST | Execute action, returns observation |
| `/state` | GET | Current environment state |
| `/tasks` | GET | List all available tasks |
| `/grader` | POST | Grade most recent episode |
| `/baseline` | POST | Return pre-computed baseline scores |
| `/health` | GET | Container health check |
| `/web` | GET | Interactive web interface |
| `/ws` | WS | WebSocket for persistent sessions |

## Project Structure

```
workflow_orchestrator/
├── openenv.yaml             # OpenEnv manifest
├── pyproject.toml            # Dependencies and metadata
├── Dockerfile                # Multi-stage Docker build
├── README.md                 # This file
├── inference.py              # Baseline inference script
├── baseline_scores.json      # Pre-computed baseline scores
├── requirements.txt          # Pip-compatible dependencies
├── models.py                 # Pydantic Action/Observation/State models
├── client.py                 # OrchestratorClient (EnvClient subclass)
├── __init__.py               # Module exports
├── server/
│   ├── app.py               # FastAPI application + custom endpoints
│   ├── environment.py        # Core environment (reset/step/state)
│   ├── dag_executor.py       # DAG state tracking + dependency resolution
│   ├── agent_pool.py         # Simulated agent state machines
│   ├── reward_calculator.py  # Dense reward computation
│   ├── graders.py            # Per-task grading functions
│   ├── task_registry.py      # Easy/medium/hard task configurations
│   └── observation_formatter.py  # Text rendering for LLM consumption
└── tests/                    # 137 passing tests
```
