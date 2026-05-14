"""
Integration Test — Example 02: Re-planning Loop (Mocked LLM)

Tests the self-correction mechanism of the Governed Agentic Loop.

Scenario:
  1. LLM proposes a plan with a forbidden tool (write_db)
  2. Policy Engine rejects: tool_permission violation
  3. LLM re-plans with only permitted tools (read_db)
  4. Policy Engine approves the revised plan
  5. Execution completes — loop_iterations == 2

The Policy Engine's rejection is DETERMINISTIC — it always rejects
write_db because it is not in analyst.permitted_tools.
The LLM re-plan is MOCKED — the second call returns a valid plan.

This proves the re-planning loop works correctly.
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
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


# ── Matrix: analyst with read_db only ────────────────────────

REPLAN_MATRIX = {
    "version":   "1.0.0",
    "tenant_id": "replan-test",
    "effective": "2026-01-01T00:00:00Z",
    "agent_roles": {
        "analyst": {
            "permitted_tools":        ["read_db", "llm_extraction"],
            "permitted_data_sources": ["documents"],
            "permitted_task_types":   ["llm_extraction", "deterministic"],
            "max_llm_calls_per_step": 3,
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
        "always_gate_action_classes": [],
        "auto_approve_action_classes": ["llm_extraction", "deterministic"],
    },
    "loop_policy": {
        "max_replan_attempts": 3,
        "max_duration_s": 120,
    },
}


# ── Plan with forbidden tool (iteration 1) ───────────────────

FORBIDDEN_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read then write extracted data",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_documents",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read documents",
        },
        {
            "task_id":        "ST-02",
            "name":           "write_results",
            "task_type":      "deterministic",
            "agent_required": "analyst",
            "tools_required": ["write_db"],   # ← FORBIDDEN (not in permitted_tools)
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.01,
            "reversible":     False,
            "rationale":      "Write extracted results to DB",
        },
    ],
    "total_estimated_cost": 0.03,
    "confidence": 0.88,
    "requires_human_gate": False,
}


# ── Revised plan without forbidden tool (iteration 2) ────────

COMPLIANT_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Revised: use only read_db and llm_extraction "
        "as write_db is not permitted"
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_documents",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read documents from database",
        },
        {
            "task_id":        "ST-02",
            "name":           "extract_features",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["llm_extraction"],  # ← permitted
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Extract features without writing to DB",
        },
    ],
    "total_estimated_cost": 0.04,
    "confidence": 0.91,
    "requires_human_gate": False,
}


def make_matrix_file() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", delete=False, mode="w"
    ) as f:
        yaml.dump(REPLAN_MATRIX, f)
        return f.name


def make_mock_llm_replan() -> LLMClient:
    """
    Mock LLM that returns forbidden plan first, compliant plan second.
    Simulates the re-planning scenario deterministically.
    """
    usage = LLMUsage(
        input_tokens=400, output_tokens=250,
        cost_usd=0.0003, model_id="claude-haiku-4-5-20251001",
    )
    mock = AsyncMock(spec=LLMClient)
    mock.model_id = "claude-haiku-4-5-20251001"
    mock.estimate_cost = lambda i, o: (i * 0.0000008 + o * 0.000004)
    # First call: forbidden plan. Second call: compliant plan.
    mock.complete = AsyncMock(side_effect=[
        LLMResponse(content=FORBIDDEN_PLAN, usage=usage),
        LLMResponse(content=COMPLIANT_PLAN, usage=usage),
    ])
    return mock


def make_registries():
    tool_registry = ToolRegistry()
    tool_registry.register(StubTool("read_db",       idempotent=True))
    tool_registry.register(StubTool("llm_extraction", idempotent=True))

    agent_registry = AgentRegistry()

    class AnalystAgent(StubAgent):
        role = "analyst"
        def __init__(self):
            super().__init__(role="analyst",
                             output={"result": "done"}, cost_usd=0.02)

    agent_registry.register(AnalystAgent)
    return agent_registry, tool_registry


# ── Tests ─────────────────────────────────────────────────────

class TestExample02ReplanLoop:

    @pytest.mark.asyncio
    async def test_loop_self_corrects_after_violation(self):
        """
        After a policy violation, the loop re-plans and succeeds.
        Final outcome is 'completed', not 'escalated'.
        """
        llm                      = make_mock_llm_replan()
        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract key data",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        assert result.outcome == "completed"

    @pytest.mark.asyncio
    async def test_loop_takes_two_iterations(self):
        """
        The loop iterates twice: once rejected, once approved.
        loop_iterations == 2.
        """
        llm                      = make_mock_llm_replan()
        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract key data",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        assert result.loop_iterations == 2

    @pytest.mark.asyncio
    async def test_llm_called_twice(self):
        """
        LLM is called exactly twice: initial plan + re-plan.
        """
        llm                      = make_mock_llm_replan()
        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        await loop.run({
            "task":      "Read documents and extract key data",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        assert llm.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_replan_receives_violation_context(self):
        """
        The second LLM call receives violation_history
        so it knows what to fix.
        """
        llm                      = make_mock_llm_replan()
        agent_registry, tool_reg = make_registries()
        plan_calls               = []

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        original_plan = loop.planning_orchestrator.plan

        async def tracking_plan(*args, **kwargs):
            plan_calls.append({
                "iteration":        kwargs.get("iteration"),
                "violation_history_len": len(kwargs.get("violation_history", [])),
            })
            return await original_plan(*args, **kwargs)

        loop.planning_orchestrator.plan = tracking_plan

        await loop.run({
            "task":      "Read documents",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        # Second call should have violation history from first rejection
        assert len(plan_calls) == 2
        assert plan_calls[0]["violation_history_len"] == 0  # first call: no history
        assert plan_calls[1]["violation_history_len"] == 1  # second: one violation

    @pytest.mark.asyncio
    async def test_audit_trail_shows_two_plan_proposed_events(self):
        """
        Audit trail contains two PLAN_PROPOSED events (one per iteration).
        """
        audit_store              = InMemoryAuditStore()
        llm                      = make_mock_llm_replan()
        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        records     = await audit_store.query(result.request_id)
        plan_events = [
            r for r in records
            if r.event_type == AuditEventType.PLAN_PROPOSED
        ]
        assert len(plan_events) == 2

    @pytest.mark.asyncio
    async def test_audit_trail_shows_one_rejection_one_approval(self):
        """
        Audit trail: first PLAN_EVALUATED is REJECTED,
        second is APPROVED.
        """
        audit_store              = InMemoryAuditStore()
        llm                      = make_mock_llm_replan()
        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        records     = await audit_store.query(result.request_id)
        eval_events = [
            r for r in records
            if r.event_type == AuditEventType.PLAN_EVALUATED
        ]
        assert len(eval_events) == 2
        assert eval_events[0].payload["verdict"] == "REJECTED"
        assert eval_events[1].payload["verdict"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_always_escalating_plan_returns_escalated(self):
        """
        If the LLM always returns a forbidden plan, loop escalates
        after max_replan_attempts.
        """
        # Always return forbidden plan
        usage = LLMUsage(500, 250, 0.0004, "test")
        mock  = AsyncMock(spec=LLMClient)
        mock.model_id      = "test"
        mock.estimate_cost = lambda i, o: 0.0
        mock.complete      = AsyncMock(
            return_value=LLMResponse(content=FORBIDDEN_PLAN, usage=usage)
        )

        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=mock,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents",
            "tenant_id": "replan-test",
            "user_id":   "test-user",
        })

        assert result.outcome == "escalated"
        assert result.loop_iterations == 3  # max_replan_attempts
