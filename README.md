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

Agent orchestration is the #1 enterprise AI trend — yet LLMs are terrible at it. Research documents 14+ failure modes in multi-agent systems (MAST taxonomy), up to 17x error amplification in unstructured networks (Spark to Fire), and only 25% baseline correctness with GPT-4o (ChatDev). This environment provides a controlled, deterministic testbed for training and evaluating LLM orchestration capabilities across four real-world scenarios forming a narrative arc: **build** a feature (Easy), **ship** it (Medium), **fix** the outage (Hard), and **orchestrate** your day (Expert).

**Novel domain:** Zero orchestration environments exist in OpenEnv today. This fills the biggest gap in the ecosystem — coordination, delegation, parallelism, failure recovery, and cost management are untested by any existing environment.

## Research Foundation

This environment is grounded in 5 recent research papers:

| Paper | Key Finding | How It Shaped Our Design |
|-------|-------------|--------------------------|
| **MAST Taxonomy** ([arxiv 2503.13657](https://arxiv.org/abs/2503.13657)) | 14 failure modes across 150+ multi-agent traces; GPT-4o achieves only 25% on ChatDev | Our tasks test 8 of 14 MAST failure modes (spec violation, role violation, step repetition, info withholding, premature termination, incomplete verification) |
| **Spark to Fire** ([arxiv 2603.04474](https://arxiv.org/abs/2603.04474)) | 17.2x error amplification in unstructured agent networks; hub injection → 100% infection | Hard task DAG topology creates realistic cascade potential; failure recovery rewards incentivize early intervention |
| **AgentErrorBench** ([arxiv 2509.25370](https://arxiv.org/abs/2509.25370)) | Targeted RL feedback improves error recovery by up to 26% across 5 failure categories | Dense per-step rewards target each error category; permanent vs. transient failure classification forces root-cause reasoning |
| **MARBLE / MultiAgentBench** ([ACL 2025](https://aclanthology.org/2025.acl-long.421/)) | 3-agent teams optimize coordination-performance balance; excessive iterations degrade coordination | Capacity limit of 3 concurrent tasks; milestone-based grading; DAG-based task structure |
| **DAAO** ([arxiv 2509.11079](https://arxiv.org/html/2509.11079v1)) | Task difficulty should dynamically determine orchestration strategy; 11% accuracy improvement | Our 4 tasks require fundamentally different strategies, not just more nodes |

## Capabilities Tested (22 Total)

Each difficulty level introduces **qualitatively different reasoning**, not just more nodes:

| # | Capability | Easy | Med | Hard | Expert | What It Tests |
|---|---|:---:|:---:|:---:|:---:|---|
| 1 | Dependency comprehension | ✓ | ✓ | ✓ | ✓ | Read DAG, understand what blocks what |
| 2 | Correct delegation | ✓ | ✓ | ✓ | ✓ | Match subtask type → agent capability |
| 3 | Sequential ordering | ✓ | ✓ | ✓ | ✓ | Don't delegate before prerequisites complete |
| 4 | Wait discipline | ✓ | ✓ | ✓ | ✓ | Wait when nothing is delegatable |
| 5 | Output synthesis | ✓ | ✓ | ✓ | ✓ | Combine outputs into final deliverable |
| 6 | Parallelism detection | | ✓ | ✓ | ✓ | Run independent subtasks concurrently |
| 7 | Failure recovery | | ✓ | ✓ | ✓ | Retry after agent failure |
| 8 | Capacity management | | ✓ | ✓ | ✓ | Stay within max concurrent task limit |
| 9 | Time pressure planning | | ✓ | ✓ | ✓ | Must parallelize to meet deadline |
| 10 | Cost awareness | | ✓ | ✓ | ✓ | Don't blindly retry expensive agents |
| 11 | Agent selection under overlap | | | ✓ | ✓ | Multiple agents for same task — pick best |
| 12 | Adaptation to agent dropout | | | ✓ | ✓ | Re-plan when agent goes offline |
| 13 | Conflicting info aggregation | | | ✓ | ✓ | Two tracks produce different findings |
| 14 | SLA milestone awareness | | | ✓ | ✓ | Hit deadlines or face escalating penalties |
| 15 | Patience under pressure | | | ✓ | | Wait for monitoring — resist premature synthesis |
| 16 | Priority reasoning | | | ✓ | ✓ | Side-channel tasks mustn't block critical path |
| 17 | Error classification | | | ✓ | ✓ | Distinguish permanent vs. transient failure |
| 18 | Multi-objective optimization | | | | ✓ | Balance competing pillar scores |
| 19 | Cross-domain conflict resolution | | | | ✓ | Reconcile health vs career vs personal |
| 20 | Agent cost-benefit analysis | | | ✓ | ✓ | When is the cheap agent actually more expensive? |
| 21 | Cascading delay awareness | | | | ✓ | Speed degradation means earlier delegation = critical |
| 22 | Multi-conflict episodes | | | | ✓ | Two distinct conflict resolution points |

**Difficulty progression:** Easy = DAG comprehension (1-5). Medium = parallelism + recovery + budgets (6-10). Hard = chaos adaptation + error classification (11-17). Expert = multi-objective optimization across life domains (18-22).

## Grader Design

Each task has a multi-dimensional grader returning a score in [0.0, 1.0] with a detailed breakdown. Graders analyze the **episode event log** (process matters, not just outcome) and are fully **deterministic** — same actions = same score.

| Task | Dimensions | Key Metrics |
|------|-----------|-------------|
| Easy | 4 | completion (85%), parallelism bonus (10%), episode complete (5%), invalid penalty |
| Medium | 6 | completion (40%), parallelism (20%), failure recovery (20%), time efficiency (10%), cost efficiency (10%) |
| Hard | 10 | completion (20%), recovery (15%), error classification (10%), capacity (10%), parallelism (10%), cost (10%), conflict resolution (10%), SLA compliance (10%), monitoring patience (5%) |
| Expert | 10 | completion (15%), health pillar (12%), career pillar (10%), conflict resolution (20%), cost (8%), parallelism (10%), time (5%), error classification (8%), SLA (8%), communication (4%) |

**Activity-gated scoring:** Dimensions that reward "no harm" (error classification, capacity discipline, cost efficiency) scale with actual activity via `min(1.0, completed / threshold)`. A do-nothing policy scores 0.0, not free points.

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

Scores from running the baseline inference script with Qwen3-32B via OpenRouter:

| Task | Score | Subtasks | Key Challenge |
|------|-------|----------|---------------|
| Easy | 0.900 | 6/6 | DAG comprehension + optional parallelism |
| Medium | 0.626 | 9/9 | 3-way fan-out + security scan failure recovery |
| Hard | 0.724 | 10/10 | Permanent failure trap + agent dropout + SLA pressure |
| Expert | 0.747 | 14/14 | Multi-objective optimization + 2 permanent failure traps |

Scores reflect the LLM's orchestration ability: easy tasks are near-perfect, while medium/hard/expert require parallelism planning, failure recovery, and cost optimization that challenge even frontier models.

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
│   ├── task_registry.py      # Easy/medium/hard/expert task configurations
│   └── observation_formatter.py  # Text rendering for LLM consumption
└── tests/                    # 160+ passing tests
```
