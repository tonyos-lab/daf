"""
Integration Test — Example 03: Human Escalation Gate (Mocked)

Tests the HITL mechanism end-to-end.

Scenario:
  - PolicyMatrix has always_gate_action_classes: ["llm_generation"]
  - LLM proposes a plan with an llm_generation step
  - Policy Engine approves the plan BUT marks ST-02 as gated
  - EvaluateStage requests human review for ST-02
  - Human approves (via StubGateway)
  - Execution completes with outcome "completed"

Also tests the rejection path:
  - Human rejects the gated task
  - EvaluateStage builds a ViolationReport
  - Loop re-plans or escalates
"""
from __future__ import annotations

import uuid
import tempfile
import yaml
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from daf import GovernedAgenticLoop
from daf.agents.stub_agent import StubAgent
from daf.models.audit_record import AuditEventType
from daf.models.human_review import HumanReviewResponse
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway
from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


# ── Matrix with HITL gate on llm_generation ──────────────────

HITL_MATRIX = {
    "version":   "1.0.0",
    "tenant_id": "hitl-test",
    "effective": "2026-01-01T00:00:00Z",
    "agent_roles": {
        "analyst": {
            "permitted_tools":        ["read_db", "llm_extraction", "llm_generation"],
            "permitted_data_sources": ["documents"],
            "permitted_task_types":   [
                "llm_extraction", "llm_generation", "deterministic"
            ],
            "max_llm_calls_per_step": 5,
        }
    },
    "budget_policy": {
        "max_cost_per_call_usd":     0.05,
        "max_cost_per_step_usd":     0.20,
        "max_cost_per_workflow_usd": 1.00,
        "max_cost_per_user_day_usd": 10.00,
        "max_cost_per_tenant_day_usd": 50.00,
    },
    "compliance_rules": [],
    "risk_policy": {
        "irreversible_min_confidence": 0.70,
        "always_gate_action_classes": ["llm_generation"],  # ← HITL trigger
        "auto_approve_action_classes": ["llm_extraction", "deterministic"],
    },
    "loop_policy": {
        "max_replan_attempts": 3,
        "max_duration_s": 120,
    },
}


# ── Plan with gated task ──────────────────────────────────────

HITL_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read documents then generate a report",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_documents",
            "task_type":      "llm_extraction",      # auto-approved
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read source documents",
        },
        {
            "task_id":        "ST-02",
            "name":           "generate_report",
            "task_type":      "llm_generation",      # ← ALWAYS GATED
            "agent_required": "analyst",
            "tools_required": ["llm_generation"],
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.03,
            "reversible":     False,
            "rationale":      "Generate final report for distribution",
        },
    ],
    "total_estimated_cost": 0.05,
    "confidence": 0.90,
    "requires_human_gate": True,
}


def make_matrix_file() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", delete=False, mode="w"
    ) as f:
        yaml.dump(HITL_MATRIX, f)
        return f.name


def make_mock_llm() -> LLMClient:
    usage = LLMUsage(400, 250, 0.0003, "claude-haiku-4-5-20251001")
    mock  = AsyncMock(spec=LLMClient)
    mock.model_id      = "claude-haiku-4-5-20251001"
    mock.estimate_cost = lambda i, o: 0.0
    mock.complete      = AsyncMock(
        return_value=LLMResponse(content=HITL_PLAN, usage=usage)
    )
    return mock


def make_registries():
    tool_registry = ToolRegistry()
    tool_registry.register(StubTool("read_db",        idempotent=True))
    tool_registry.register(StubTool("llm_extraction",  idempotent=True))
    tool_registry.register(StubTool("llm_generation",  idempotent=True))

    agent_registry = AgentRegistry()

    class AnalystAgent(StubAgent):
        role = "analyst"
        def __init__(self):
            super().__init__(role="analyst",
                             output={"result": "done"}, cost_usd=0.02)

    agent_registry.register(AnalystAgent)
    return agent_registry, tool_registry


# ── Tests: HITL Approved ──────────────────────────────────────

class TestExample03HITLApproved:
    """Human approves all gated tasks — workflow completes."""

    @pytest.mark.asyncio
    async def test_hitl_approved_workflow_completes(self):
        """When human approves, outcome is 'completed'."""
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        assert result.outcome == "completed"

    @pytest.mark.asyncio
    async def test_hitl_gateway_receives_review_request(self):
        """HITL gateway receives exactly one review request."""
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
        )

        await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        assert len(hitl_gateway.requests) == 1
        request = hitl_gateway.requests[0]
        assert "ST-02" in request.gated_task_ids

    @pytest.mark.asyncio
    async def test_hitl_request_contains_correct_task_details(self):
        """Review request contains correct task details for reviewer."""
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
        )

        await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        request    = hitl_gateway.requests[0]
        gated_task = next(t for t in request.gated_tasks
                          if t.task_id == "ST-02")

        assert gated_task.action_class == "llm_generation"
        assert gated_task.reversible   is False

    @pytest.mark.asyncio
    async def test_hitl_audit_records_written(self):
        """HUMAN_REVIEW_REQUESTED and HUMAN_REVIEW_RESPONDED are written."""
        audit_store              = InMemoryAuditStore()
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        records     = await audit_store.query(result.request_id)
        event_types = {r.event_type for r in records}

        assert AuditEventType.HUMAN_REVIEW_REQUESTED in event_types
        assert AuditEventType.HUMAN_REVIEW_RESPONDED in event_types

    @pytest.mark.asyncio
    async def test_hitl_one_iteration_with_approved_review(self):
        """
        When HITL is approved, loop completes in one iteration.
        The review does not count as a re-plan.
        """
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        assert result.loop_iterations == 1


# ── Tests: HITL Rejected ──────────────────────────────────────

class TestExample03HITLRejected:
    """Human rejects gated task — loop re-plans or escalates."""

    @pytest.mark.asyncio
    async def test_hitl_rejected_triggers_replan(self):
        """
        When human rejects, the loop treats it as a violation
        and attempts to re-plan. With max_replan_attempts=3
        and the LLM always proposing the same gated plan,
        the loop escalates.
        """
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=False)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        # Human always rejects, LLM always proposes same gated plan
        # → escalates after max_replan_attempts
        assert result.outcome == "escalated"

    @pytest.mark.asyncio
    async def test_hitl_rejection_in_audit_trail(self):
        """Rejected HITL review is recorded in audit trail."""
        audit_store              = InMemoryAuditStore()
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(approve_all=False)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        records     = await audit_store.query(result.request_id)
        hitl_resp   = next(
            (r for r in records
             if r.event_type == AuditEventType.HUMAN_REVIEW_RESPONDED),
            None
        )
        assert hitl_resp is not None
        assert hitl_resp.payload["fully_approved"] is False


# ── Tests: HITL Timeout ───────────────────────────────────────

class TestExample03HITLTimeout:
    """Review times out — auto-rejected and loop re-plans."""

    @pytest.mark.asyncio
    async def test_hitl_timeout_treated_as_rejection(self):
        """Timeout auto-rejects and the loop escalates."""
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(simulate_timeout=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        assert result.outcome == "escalated"

    @pytest.mark.asyncio
    async def test_timeout_audit_record_has_timed_out_flag(self):
        """HUMAN_REVIEW_RESPONDED audit payload has timed_out=True."""
        audit_store              = InMemoryAuditStore()
        llm                      = make_mock_llm()
        agent_registry, tool_reg = make_registries()
        hitl_gateway             = StubHumanReviewGateway(simulate_timeout=True)

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            hitl_gateway=hitl_gateway,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and generate a report",
            "tenant_id": "hitl-test",
            "user_id":   "test-user",
        })

        records = await audit_store.query(result.request_id)
        # Find the first HUMAN_REVIEW_RESPONDED with timed_out=True
        timeout_record = next(
            (r for r in records
             if r.event_type == AuditEventType.HUMAN_REVIEW_RESPONDED
             and r.payload.get("timed_out") is True),
            None
        )
        assert timeout_record is not None
