"""Tests for agent pool — tick simulation, seeded failures, dropout, cost tracking."""

import pytest

from server.agent_pool import AgentPool
from server.task_registry import get_task


class TestAgentPoolBasic:
    def test_easy_agents_always_succeed(self) -> None:
        """Easy task agents all have reliability=1.0."""
        config = get_task("easy")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        pool.assign("tech_lead", "technical_design", "technical_design", 0)
        results = pool.tick(1)  # speed=1, completes immediately
        assert len(results) == 1
        assert results[0].succeeded is True

    def test_assign_validates_capability(self) -> None:
        config = get_task("easy")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        with pytest.raises(ValueError, match="lacks capability"):
            pool.assign("frontend_dev", "technical_design", "technical_design", 0)

    def test_assign_validates_idle(self) -> None:
        config = get_task("easy")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        pool.assign("tech_lead", "technical_design", "technical_design", 0)
        with pytest.raises(ValueError, match="not idle"):
            pool.assign("tech_lead", "other_task", "review", 0)


class TestReliabilityOverrides:
    def test_medium_scanner_fails_first_succeeds_second(self) -> None:
        """security_scanner has [0.0, 1.0] override for security_scan."""
        config = get_task("medium")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)

        # Attempt 0: guaranteed failure
        pool.assign("security_scanner", "run_security_scan", "security_scan", 0)
        pool.tick(1)  # speed=2
        results = pool.tick(2)
        assert results[0].succeeded is False

        # Attempt 1: guaranteed success
        pool.release_agent("security_scanner")
        pool.assign("security_scanner", "run_security_scan", "security_scan", 1)
        pool.tick(3)
        results = pool.tick(4)
        assert results[0].succeeded is True

    def test_hard_alpha_permanent_failure_on_enrich_logs(self) -> None:
        """investigator_alpha reliability=0.0 for enrich_logs."""
        config = get_task("hard")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        pool.assign("investigator_alpha", "enrich_logs", "enrich_logs", 0)
        pool.tick(1)  # speed=2
        results = pool.tick(2)
        assert results[0].succeeded is False
        assert results[0].is_permanent_failure is True

    def test_hard_alpha_can_do_root_cause(self) -> None:
        """investigator_alpha has normal reliability (0.85) for root_cause."""
        config = get_task("hard")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        # No override for (investigator_alpha, root_cause) — uses default 0.85
        pool.assign("investigator_alpha", "root_cause_analysis", "root_cause", 0)
        pool.tick(1)
        results = pool.tick(2)
        # We can't assert success/failure deterministically without knowing the RNG output,
        # but we can verify it ran and produced a result
        assert len(results) == 1
        assert results[0].agent_name == "investigator_alpha"


class TestDeterminism:
    def test_same_seed_same_results(self) -> None:
        """Two pools with same seed produce identical outcomes."""
        config = get_task("hard")
        pool1 = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        pool2 = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)

        pool1.assign("triage_analyst", "alert_triage", "triage", 0)
        pool2.assign("triage_analyst", "alert_triage", "triage", 0)

        r1 = pool1.tick(1)
        r2 = pool2.tick(1)

        assert r1[0].succeeded == r2[0].succeeded
        assert r1[0].output_or_error == r2[0].output_or_error


class TestCostTracking:
    def test_cost_accrues_per_tick(self) -> None:
        config = get_task("medium")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        assert pool.get_budget_used() == 0.0

        pool.assign("test_service", "run_unit_tests", "unit_test", 0)  # cost=2.0
        pool.assign("security_scanner", "run_security_scan", "security_scan", 0)  # cost=3.0
        pool.tick(1)
        assert pool.get_budget_used() == 5.0  # 2.0 + 3.0

        pool.tick(2)  # Both agents still working (speed=2)
        assert pool.get_budget_used() == 10.0  # 5.0 + 5.0


class TestScheduledEvents:
    def test_deployer_dropout_at_step_12(self) -> None:
        config = get_task("hard")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)

        assert pool.is_online("deployer")
        fired = pool.apply_scheduled_events(11, config.scheduled_events)
        assert len(fired) == 0  # Not yet

        fired = pool.apply_scheduled_events(12, config.scheduled_events)
        assert len(fired) == 1
        assert fired[0]["event_type"] == "agent_dropout"
        assert not pool.is_online("deployer")

    def test_dropout_releases_working_task(self) -> None:
        config = get_task("hard")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        pool.assign("deployer", "deploy_hotfix", "deploy_hotfix", 0)

        fired = pool.apply_scheduled_events(12, config.scheduled_events)
        assert fired[0]["was_working"] is True
        assert fired[0]["released_task"] == "deploy_hotfix"
        assert not pool.is_online("deployer")


class TestQueries:
    def test_get_idle_agents(self) -> None:
        config = get_task("easy")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        idle = pool.get_idle_agents()
        assert len(idle) == 4

        pool.assign("tech_lead", "technical_design", "technical_design", 0)
        idle = pool.get_idle_agents()
        assert len(idle) == 3
        assert "tech_lead" not in idle

    def test_get_capable_agents(self) -> None:
        config = get_task("easy")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        capable = pool.get_capable_agents("technical_design")
        assert capable == ["tech_lead"]

        capable = pool.get_capable_agents("testing")
        assert set(capable) == {"backend_dev", "qa_engineer"}

    def test_agent_infos_export(self) -> None:
        config = get_task("easy")
        pool = AgentPool(config.agent_definitions, config.reliability_overrides, config.seed)
        infos = pool.get_agent_infos()
        assert len(infos) == 4
        assert all(info.status == "idle" for info in infos)
