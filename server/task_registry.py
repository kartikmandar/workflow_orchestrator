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


# ── Expert (Bonus): Life OS Daily Orchestration ──

_EXPERT_TASK = TaskConfig(
    task_id="expert",
    name="Life OS Daily Orchestration",
    difficulty="expert",
    description="Orchestrate a user's day across health, career, and personal pillars",
    subtask_definitions=[
        {
            "id": "morning_check_in",
            "type": "context",
            "dependencies": [],
            "output_template": "Morning context loaded: sleep 5.2h, 3 meetings, friend's birthday",
        },
        {
            "id": "assess_sleep_energy",
            "type": "health_analysis",
            "dependencies": ["morning_check_in"],
            "output_template": "Sleep analysis: 5.2h (poor), energy low, recommend light day",
        },
        {
            "id": "assess_career_deadlines",
            "type": "career_analysis",
            "dependencies": ["morning_check_in"],
            "output_template": "Career analysis: client deadline Friday, 2 PRs pending review, full effort needed",
        },
        {
            "id": "assess_personal_commitments",
            "type": "personal_analysis",
            "dependencies": ["morning_check_in"],
            "output_template": "Personal analysis: friend's birthday call at 6PM, protect evening",
        },
        {
            "id": "plan_day_schedule",
            "type": "planning",
            "dependencies": ["assess_sleep_energy", "assess_career_deadlines", "assess_personal_commitments"],
            "output_template": "Day plan: light morning focus, deep work 10-12, health break, afternoon push, 6PM call",
        },
        {
            "id": "start_focus_session",
            "type": "focus_setup",
            "dependencies": ["plan_day_schedule"],
            "output_template": "Focus mode: notifications blocked, Slack DND, 90-min timer started",
        },
        {
            "id": "process_inbox",
            "type": "email_triage",
            "dependencies": ["plan_day_schedule"],
            "output_template": "Inbox processed: 3 urgent flagged, 12 archived, 2 delegated",
        },
        {
            "id": "deep_work_block",
            "type": "career_execution",
            "dependencies": ["start_focus_session"],
            "output_template": "Deep work complete: PR #247 submitted, client draft 80% done",
        },
        {
            "id": "handle_urgent_request",
            "type": "career_urgent",
            "dependencies": ["process_inbox"],
            "output_template": "Urgent handled: client deadline moved to Thursday, escalated to manager",
        },
        {
            "id": "midday_health_check",
            "type": "health_alert",
            "dependencies": ["deep_work_block"],
            "output_template": "Health alert: stress critical (HRV 22ms), mandatory 15-min break enforced",
        },
        {
            "id": "resolve_priority_conflict",
            "type": "conflict_resolution",
            "dependencies": ["midday_health_check", "handle_urgent_request"],
            "output_template": "Conflict resolved: 15-min break now, then client push, birthday call preserved at 6PM",
        },
        {
            "id": "afternoon_execution",
            "type": "career_execution",
            "dependencies": ["resolve_priority_conflict"],
            "output_template": "Afternoon complete: client deliverable submitted, PRs reviewed",
        },
        {
            "id": "notify_stakeholders",
            "type": "communication",
            "dependencies": ["resolve_priority_conflict"],
            "output_template": "Notifications sent: manager updated, birthday reminder set, health log saved",
        },
        {
            "id": "synthesize_day_report",
            "type": "communication",
            "dependencies": ["afternoon_execution", "notify_stakeholders"],
            "output_template": "Day report: health managed (break taken), career delivered (client + PRs), personal preserved (6PM call)",
        },
    ],
    agent_definitions=[
        {
            "name": "companion",
            "capabilities": [
                "context", "health_analysis", "health_alert", "career_analysis",
                "career_execution", "career_urgent", "personal_analysis", "planning",
                "focus_setup", "email_triage", "conflict_resolution", "communication",
            ],
            "speed": 2,
            "reliability": 0.90,
            "cost_per_step": 3.0,
        },
        {
            "name": "health_agent",
            "capabilities": ["context", "health_analysis", "health_alert"],
            "speed": 1,
            "reliability": 0.85,
            "cost_per_step": 1.5,
        },
        {
            "name": "career_agent",
            "capabilities": ["context", "career_analysis", "career_execution", "career_urgent"],
            "speed": 2,
            "reliability": 0.80,
            "cost_per_step": 2.0,
        },
        {
            "name": "focus_agent",
            "capabilities": ["context", "focus_setup"],
            "speed": 1,
            "reliability": 0.95,
            "cost_per_step": 1.0,
        },
        {
            "name": "mail_agent",
            "capabilities": ["context", "email_triage", "communication"],
            "speed": 1,
            "reliability": 0.85,
            "cost_per_step": 1.0,
        },
        {
            "name": "personal_agent",
            "capabilities": ["context", "personal_analysis", "communication"],
            "speed": 1,
            "reliability": 0.90,
            "cost_per_step": 0.5,
        },
        {
            "name": "wellness_monitor",
            "capabilities": ["context", "health_analysis"],
            "speed": 2,
            "reliability": 0.70,
            "cost_per_step": 1.0,
        },
        {
            "name": "executive_assistant",
            "capabilities": [
                "context", "planning", "career_analysis", "career_urgent",
                "email_triage", "communication",
            ],
            "speed": 2,
            "reliability": 0.75,
            "cost_per_step": 2.0,
        },
    ],
    constraints={
        "time_budget": 25,
        "capacity_limit": 3,
        "cost_budget": 55.0,
    },
    reliability_overrides={
        # Wellness monitor permanently can't do health_alert (lacks clinical-grade analysis)
        ("wellness_monitor", "health_alert"): 0.0,
        # Executive assistant permanently can't do conflict_resolution (can't reason across pillars)
        ("executive_assistant", "conflict_resolution"): 0.0,
    },
    scheduled_events=[
        {"step": 7, "event_type": "degradation", "target": "career_agent", "params": {"new_speed": 4}},
        {"step": 10, "event_type": "dropout", "target": "personal_agent", "params": {}},
    ],
    sla_milestones={
        "plan_day_schedule": 8,
        "resolve_priority_conflict": 16,
        "synthesize_day_report": 23,
    },
    seed=45,
    sequential_time=14,
    communication_subtasks=["notify_stakeholders", "synthesize_day_report"],
)


# ── Registry ──

_TASKS: dict[str, TaskConfig] = {
    "easy": _EASY_TASK,
    "medium": _MEDIUM_TASK,
    "hard": _HARD_TASK,
    "expert": _EXPERT_TASK,
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
