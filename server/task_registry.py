"""Task configurations for the Workflow Orchestrator Environment.

Defines the 3 core tasks (easy/medium/hard) with their DAGs, agents,
constraints, reliability overrides, scheduled events, and SLA milestones.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Union


@dataclass
class TaskConfig:
    """Configuration for a single orchestration task."""

    task_id: str
    name: str
    difficulty: str
    description: str
    subtask_definitions: list[dict[str, Any]]
    agent_definitions: list[dict[str, Any]]
    constraints: dict[str, Any]
    reliability_overrides: dict[tuple[str, str], Union[float, list[float]]]
    scheduled_events: list[dict[str, Any]]
    sla_milestones: Optional[dict[str, int]]
    seed: int
    sequential_time: int
    communication_subtasks: list[str] = field(default_factory=list)


# ── Easy: Feature Development Sprint ──

_EASY_TASK = TaskConfig(
    task_id="easy",
    name="Feature Development Sprint",
    difficulty="easy",
    description="Coordinate a development team to build and merge a feature",
    subtask_definitions=[
        {
            "id": "technical_design",
            "type": "technical_design",
            "dependencies": [],
            "output_template": "Design document: API endpoints defined, data models specified, architecture reviewed",
        },
        {
            "id": "implement_backend",
            "type": "backend_impl",
            "dependencies": ["technical_design"],
            "output_template": "Backend API endpoints implemented with unit tests passing",
        },
        {
            "id": "implement_frontend",
            "type": "frontend_impl",
            "dependencies": ["implement_backend"],
            "output_template": "Frontend UI components implemented and connected to API",
        },
        {
            "id": "write_tests",
            "type": "testing",
            "dependencies": ["implement_backend"],
            "output_template": "Integration test suite written covering all endpoints",
        },
        {
            "id": "run_tests",
            "type": "testing",
            "dependencies": ["implement_frontend", "write_tests"],
            "output_template": "All 47 tests passing, 94% coverage",
        },
        {
            "id": "review_and_merge",
            "type": "review",
            "dependencies": ["run_tests"],
            "output_template": "Code reviewed, approved, and merged to main branch",
        },
    ],
    agent_definitions=[
        {
            "name": "tech_lead",
            "capabilities": ["technical_design", "review"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
        {
            "name": "backend_dev",
            "capabilities": ["backend_impl", "testing"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
        {
            "name": "frontend_dev",
            "capabilities": ["frontend_impl"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
        {
            "name": "qa_engineer",
            "capabilities": ["testing"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
    ],
    constraints={
        "time_budget": 15,
        "capacity_limit": 4,
        "cost_budget": None,
    },
    reliability_overrides={},
    scheduled_events=[],
    sla_milestones=None,
    seed=42,
    sequential_time=6,
)


# ── Medium: Microservice Deployment Pipeline ──

_MEDIUM_TASK = TaskConfig(
    task_id="medium",
    name="Microservice Deployment Pipeline",
    difficulty="medium",
    description="Deploy a code change through the full CI/CD pipeline",
    subtask_definitions=[
        {
            "id": "checkout_code",
            "type": "checkout",
            "dependencies": [],
            "output_template": "Repository checked out at commit abc123",
        },
        {
            "id": "run_linter",
            "type": "lint",
            "dependencies": ["checkout_code"],
            "output_template": "Linting passed: 0 errors, 2 warnings (eslint)",
        },
        {
            "id": "run_unit_tests",
            "type": "unit_test",
            "dependencies": ["checkout_code"],
            "output_template": "Unit tests passed: 142/142 tests, 89% coverage",
        },
        {
            "id": "run_security_scan",
            "type": "security_scan",
            "dependencies": ["checkout_code"],
            "output_template": "Security scan passed: no critical vulnerabilities found",
        },
        {
            "id": "build_image",
            "type": "build",
            "dependencies": ["run_linter", "run_unit_tests", "run_security_scan"],
            "output_template": "Docker image built: app:v2.1.0-abc123",
        },
        {
            "id": "push_registry",
            "type": "push_image",
            "dependencies": ["build_image"],
            "output_template": "Image pushed to registry: ecr/app:v2.1.0-abc123",
        },
        {
            "id": "deploy_staging",
            "type": "deploy_staging",
            "dependencies": ["push_registry"],
            "output_template": "Deployed to staging environment, health checks passing",
        },
        {
            "id": "run_smoke_tests",
            "type": "smoke_test",
            "dependencies": ["deploy_staging"],
            "output_template": "Smoke tests passed: all critical paths verified",
        },
        {
            "id": "deploy_production",
            "type": "deploy_production",
            "dependencies": ["run_smoke_tests"],
            "output_template": "Production deployment complete, canary metrics healthy",
        },
    ],
    agent_definitions=[
        {
            "name": "ci_runner",
            "capabilities": ["checkout", "lint", "build"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
        {
            "name": "test_service",
            "capabilities": ["unit_test", "smoke_test"],
            "speed": 2,
            "reliability": 1.0,
            "cost_per_step": 2.0,
        },
        {
            "name": "security_scanner",
            "capabilities": ["security_scan"],
            "speed": 2,
            "reliability": 0.85,
            "cost_per_step": 3.0,
        },
        {
            "name": "registry_service",
            "capabilities": ["push_image"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
        {
            "name": "deploy_service",
            "capabilities": ["deploy_staging", "deploy_production"],
            "speed": 1,
            "reliability": 0.90,
            "cost_per_step": 2.0,
        },
    ],
    constraints={
        "time_budget": 16,
        "capacity_limit": 3,
        "cost_budget": 35.0,
    },
    reliability_overrides={
        # Attempt 0: guaranteed fail (false positive CVE). Attempt 1+: guaranteed succeed.
        ("security_scanner", "security_scan"): [0.0, 1.0],
    },
    scheduled_events=[],
    sla_milestones=None,
    seed=43,
    sequential_time=12,
)


# ── Hard: Production Incident Response ──

_HARD_TASK = TaskConfig(
    task_id="hard",
    name="Production Incident Response",
    difficulty="hard",
    description="Resolve a production incident within SLA constraints",
    subtask_definitions=[
        {
            "id": "alert_triage",
            "type": "triage",
            "dependencies": [],
            "output_template": "SEV-1 confirmed: service X latency >5s, error rate 40%, 3 regions affected",
        },
        {
            "id": "enrich_logs",
            "type": "enrich_logs",
            "dependencies": ["alert_triage"],
            "output_template": "Log analysis: database connection pool exhausted, 50+ pending connections",
        },
        {
            "id": "check_dashboards",
            "type": "dashboard",
            "dependencies": ["alert_triage"],
            "output_template": "Dashboard analysis: memory leak in service X, 85% memory utilization",
        },
        {
            "id": "check_dependencies",
            "type": "dependencies",
            "dependencies": ["alert_triage"],
            "output_template": "Dependency check: upstream API healthy, database primary responding",
        },
        {
            "id": "root_cause_analysis",
            "type": "root_cause",
            "dependencies": ["enrich_logs", "check_dashboards", "check_dependencies"],
            "output_template": "Root cause: connection pool exhaustion due to memory leak in service X",
        },
        {
            "id": "deploy_hotfix",
            "type": "deploy_hotfix",
            "dependencies": ["root_cause_analysis"],
            "output_template": "Hotfix deployed: connection pool limit increased, memory leak patched",
        },
        {
            "id": "validate_fix",
            "type": "validate",
            "dependencies": ["deploy_hotfix"],
            "output_template": "Fix validated: latency <200ms, error rate <0.1%, all regions recovered",
        },
        {
            "id": "monitor_recovery",
            "type": "monitor",
            "dependencies": ["validate_fix"],
            "output_template": "Recovery confirmed: 15 minutes stable, no anomalies detected",
        },
        {
            "id": "notify_stakeholders",
            "type": "notify",
            "dependencies": ["alert_triage"],
            "output_template": "Stakeholders notified: incident channel updated, status page posted",
        },
        {
            "id": "update_status_page",
            "type": "status",
            "dependencies": ["alert_triage"],
            "output_template": "Status page updated: investigating → identified → monitoring → resolved",
        },
    ],
    agent_definitions=[
        {
            "name": "triage_analyst",
            "capabilities": ["triage", "dashboard"],
            "speed": 1,
            "reliability": 0.95,
            "cost_per_step": 1.0,
        },
        {
            "name": "investigator_alpha",
            "capabilities": ["enrich_logs", "root_cause", "dependencies"],
            "speed": 2,
            "reliability": 0.85,
            "cost_per_step": 2.0,
        },
        {
            "name": "investigator_beta",
            "capabilities": ["enrich_logs", "root_cause", "dashboard"],
            "speed": 2,
            "reliability": 0.80,
            "cost_per_step": 2.0,
        },
        {
            "name": "senior_engineer",
            "capabilities": ["root_cause", "deploy_hotfix", "validate"],
            "speed": 1,
            "reliability": 0.90,
            "cost_per_step": 5.0,
        },
        {
            "name": "communicator",
            "capabilities": ["notify", "status"],
            "speed": 1,
            "reliability": 0.95,
            "cost_per_step": 1.0,
        },
        {
            "name": "deployer",
            "capabilities": ["deploy_hotfix"],
            "speed": 2,
            "reliability": 0.85,
            "cost_per_step": 1.5,
        },
        {
            "name": "monitor",
            "capabilities": ["monitor", "dashboard"],
            "speed": 1,
            "reliability": 1.0,
            "cost_per_step": 1.0,
        },
    ],
    constraints={
        "time_budget": 22,
        "capacity_limit": 3,
        "cost_budget": 40.0,
    },
    reliability_overrides={
        # investigator_alpha permanently cannot do enrich_logs (lacks log tooling)
        ("investigator_alpha", "enrich_logs"): 0.0,
    },
    scheduled_events=[
        {"step": 12, "event_type": "dropout", "target": "deployer", "params": {}},
    ],
    sla_milestones={
        "root_cause_analysis": 10,
        "deploy_hotfix": 16,
    },
    seed=44,
    sequential_time=12,
    communication_subtasks=["notify_stakeholders", "update_status_page"],
)


# ── Registry ──

_TASKS: dict[str, TaskConfig] = {
    "easy": _EASY_TASK,
    "medium": _MEDIUM_TASK,
    "hard": _HARD_TASK,
}


def get_task(task_id: str) -> TaskConfig:
    """Get a task configuration by ID.

    Args:
        task_id: One of "easy", "medium", "hard"

    Returns:
        TaskConfig for the requested task

    Raises:
        KeyError: If task_id is not found
    """
    if task_id not in _TASKS:
        raise KeyError(f"Unknown task_id '{task_id}'. Available: {list(_TASKS.keys())}")
    return _TASKS[task_id]


def list_tasks() -> list[TaskConfig]:
    """Return all available task configurations."""
    return list(_TASKS.values())
