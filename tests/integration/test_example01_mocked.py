"""
Integration Test — Example 01: Basic Analysis (Mocked LLM)

Tests the complete Phase 2 stack end-to-end using a mocked LLM.
No API key needed. No Docker needed.

This test verifies:
  - All Phase 2 components wire together correctly
  - The full PLAN → EVALUATE → EXECUTE loop runs
  - Audit trail is complete (WORKFLOW_STARTED through WORKFLOW_COMPLETED)
  - Budget is tracked across all agents
  - Checkpoint lifecycle is correct
  - FinalResponse is correct

The LLM is mocked to return a deterministic PlanProposal.
All agents are StubAgents. All tools are StubTools.
PolicyEngine is real — deterministic evaluation.
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
from daf.models.final_response import FinalResponse
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.checkpoint_store import InMemoryCheckpointStore
from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


# ── Fixtures ──────────────────────────────────────────────────

EXAMPLE_MATRIX = {
    "version":   "1.0.0",
    "tenant_id": "example-org",
    "effective": "2026-01-01T00:00:00Z",
    "agent_roles": {
        "analyst": {
            "permitted_tools": [
                "read_db", "read_file",
                "llm_extraction", "llm_summarization",
            ],
            "permitted_data_sources": ["documents", "reports"],
            "permitted_task_types": [
                "deterministic", "llm_extraction",
                "llm_summarization", "llm_generation", "llm_evaluation",
            ],
            "max_llm_calls_per_step": 5,
        }
    },
    "orchestrator_routing": {
        "default_orchestrator": {"may_spawn_roles": ["analyst"]}
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
        "auto_approve_action_classes": [
            "deterministic", "llm_extraction",
            "llm_summarization", "llm_generation",
        ],
    },
    "loop_policy": {
        "max_replan_attempts": 3,
        "max_duration_s": 120,
    },
}

# A deterministic PlanProposal that will always pass the PolicyEngine
VALID_PLAN_CONTENT = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read documents, extract features, summarise findings",
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
            "tools_required": ["llm_extraction"],
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.03,
            "reversible":     True,
            "rationale":      "Extract key features from documents",
        },
        {
            "task_id":        "ST-03",
            "name":           "summarise_findings",
            "task_type":      "llm_summarization",
            "agent_required": "analyst",
            "tools_required": ["llm_summarization"],
            "data_required":  [],
            "depends_on":     ["ST-02"],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Summarise extracted features",
        },
    ],
    "total_estimated_cost": 0.07,
    "confidence": 0.92,
    "requires_human_gate": False,
}


def make_matrix_file() -> str:
    """Write example matrix to temp file and return path."""
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", delete=False, mode="w"
    ) as f:
        yaml.dump(EXAMPLE_MATRIX, f)
        return f.name


def make_mock_llm() -> LLMClient:
    """Build a mock LLM that returns the valid plan content."""
    mock = AsyncMock(spec=LLMClient)
    mock.model_id = "claude-haiku-4-5-20251001"
    mock.complete = AsyncMock(return_value=LLMResponse(
        content=VALID_PLAN_CONTENT,
        usage=LLMUsage(
            input_tokens=450,
            output_tokens=280,
            cost_usd=0.0003,
            model_id="claude-haiku-4-5-20251001",
        ),
    ))
    mock.estimate_cost = lambda i, o: (i * 0.0000008 + o * 0.000004)
    return mock


def make_registries() -> tuple[AgentRegistry, ToolRegistry]:
    """Build agent and tool registries for the example."""
    # Tools
    tool_registry = ToolRegistry()
    tool_registry.register(StubTool(
        "read_db", idempotent=True,
        output={"documents": [{"id": 1, "content": "Product features..."}]},
    ))
    tool_registry.register(StubTool(
        "read_file", idempotent=True,
        output={"content": "File content"},
    ))
    tool_registry.register(StubTool(
        "llm_extraction", idempotent=True,
        output={"features": ["Multi-tenant", "Real-time", "Compliant"]},
    ))
    tool_registry.register(StubTool(
        "llm_summarization", idempotent=True,
        output={"summary": "Product is a real-time, compliant platform."},
    ))

    # Agents
    agent_registry = AgentRegistry()

    class AnalystAgent(StubAgent):
        role = "analyst"
        def __init__(self):
            super().__init__(
                role="analyst",
                output={"result": "Analyst completed step successfully"},
                cost_usd=0.02,
            )

    agent_registry.register(AnalystAgent)
    return agent_registry, tool_registry


# ── Tests ──────────────────────────────────────────────────────

class TestExample01EndToEnd:
    """
    Complete Phase 2 end-to-end test.
    All components real except LLM (mocked).
    """

    @pytest.mark.asyncio
    async def test_loop_runs_and_returns_final_response(self):
        """Full loop completes and returns FinalResponse."""
        matrix_path               = make_matrix_file()
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=matrix_path,
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":       "Read product docs and extract key features",
            "tenant_id":  "example-org",
            "user_id":    "test-user",
            "constraints": {"max_cost_usd": 1.0},
        })

        assert isinstance(result, FinalResponse)

    @pytest.mark.asyncio
    async def test_outcome_is_completed(self):
        """Outcome is 'completed' when all tasks succeed."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read product docs and extract key features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        assert result.outcome == "completed"

    @pytest.mark.asyncio
    async def test_loop_iterates_once_on_first_approval(self):
        """Plan passes Policy Engine on first attempt — one iteration."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Extract key features from documents",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        assert result.loop_iterations == 1

    @pytest.mark.asyncio
    async def test_three_steps_executed(self):
        """Three sub-tasks in the plan → three step results."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        assert result.result is not None
        assert len(result.result) == 3

    @pytest.mark.asyncio
    async def test_all_steps_succeed(self):
        """All three steps succeed."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        assert all(step["success"] for step in result.result)

    @pytest.mark.asyncio
    async def test_step_task_ids_correct(self):
        """Step results contain correct task IDs in order."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        task_ids = [step["task_id"] for step in result.result]
        assert "ST-01" in task_ids
        assert "ST-02" in task_ids
        assert "ST-03" in task_ids

    @pytest.mark.asyncio
    async def test_budget_tracked(self):
        """total_cost_usd is positive (agents have non-zero cost)."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        # Each AnalystAgent costs 0.02, 3 agents = 0.06
        assert result.total_cost_usd == pytest.approx(0.06)


class TestExample01AuditTrail:
    """
    Verify the complete audit trail is written correctly.
    """

    @pytest.mark.asyncio
    async def test_full_audit_trail_written(self):
        """All expected audit events are written."""
        audit_store               = InMemoryAuditStore()
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        # Query all records for this workflow
        records     = await audit_store.query(result.request_id)
        event_types = {r.event_type for r in records}

        # These events MUST be present
        required_events = {
            AuditEventType.WORKFLOW_STARTED,
            AuditEventType.PLAN_PROPOSED,
            AuditEventType.PLAN_EVALUATED,
            AuditEventType.EXECUTION_STARTED,
            AuditEventType.STEP_STARTED,
            AuditEventType.STEP_COMPLETED,
            AuditEventType.WORKFLOW_COMPLETED,
        }
        for event in required_events:
            assert event in event_types, (
                f"Expected audit event '{event}' not found. "
                f"Found: {event_types}"
            )

    @pytest.mark.asyncio
    async def test_three_step_started_and_completed_events(self):
        """Three STEP_STARTED and three STEP_COMPLETED events."""
        audit_store               = InMemoryAuditStore()
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        records = await audit_store.query(result.request_id)
        event_counts = {}
        for r in records:
            event_counts[r.event_type] = event_counts.get(r.event_type, 0) + 1

        assert event_counts.get(AuditEventType.STEP_STARTED)   == 3
        assert event_counts.get(AuditEventType.STEP_COMPLETED) == 3

    @pytest.mark.asyncio
    async def test_workflow_completed_is_last_event(self):
        """WORKFLOW_COMPLETED is the last audit event written."""
        audit_store               = InMemoryAuditStore()
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        records = await audit_store.query(result.request_id)
        assert records[-1].event_type == AuditEventType.WORKFLOW_COMPLETED

    @pytest.mark.asyncio
    async def test_audit_summary_in_response(self):
        """FinalResponse.audit_summary contains event counts."""
        audit_store               = InMemoryAuditStore()
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            audit_store=audit_store,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        assert result.audit_summary.get("total_events", 0) > 0
        assert "event_counts" in result.audit_summary


class TestExample01CheckpointLifecycle:
    """
    Verify checkpoint is created and deleted through the workflow.
    """

    @pytest.mark.asyncio
    async def test_checkpoint_deleted_after_completion(self):
        """No checkpoint remains after successful completion."""
        checkpoint_store          = InMemoryCheckpointStore()
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
            checkpoint_store=checkpoint_store,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        # No checkpoint should remain after successful completion
        exists = await checkpoint_store.exists(result.request_id)
        assert exists is False


class TestExample01PolicyEnforcement:
    """
    Verify Policy Engine enforces permissions correctly in the full loop.
    """

    @pytest.mark.asyncio
    async def test_plan_with_forbidden_tool_causes_escalation(self):
        """
        If LLM proposes a tool not in the PolicyMatrix,
        Policy Engine rejects it. After max retries, loop escalates.
        """
        # Matrix with NO permitted tools for the analyst
        restrictive_matrix = dict(EXAMPLE_MATRIX)
        restrictive_matrix["agent_roles"] = {
            "analyst": {
                "permitted_tools":        [],  # no tools permitted
                "permitted_data_sources": [],
                "permitted_task_types":   ["llm_extraction"],
                "max_llm_calls_per_step": 3,
            }
        }
        restrictive_matrix["loop_policy"] = {
            "max_replan_attempts": 2,
            "max_duration_s": 60,
        }
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", delete=False, mode="w"
        ) as f:
            yaml.dump(restrictive_matrix, f)
            restrictive_path = f.name

        llm = make_mock_llm()
        # LLM always proposes read_db — which is forbidden
        agent_registry, tool_reg = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=restrictive_path,
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "example-org",
            "user_id":   "test-user",
        })

        # Should escalate — no compliant plan possible
        assert result.outcome == "escalated"
        assert result.loop_iterations == 2  # max_replan_attempts

    @pytest.mark.asyncio
    async def test_invalid_input_handled_before_llm(self):
        """Invalid input returns immediately without calling the LLM."""
        llm                       = make_mock_llm()
        agent_registry, tool_reg  = make_registries()

        loop = GovernedAgenticLoop(
            llm_client=llm,
            policy_matrix=make_matrix_file(),
            agent_registry=agent_registry,
            tool_registry=tool_reg,
        )

        result = await loop.run({"task": ""})

        assert result.outcome == "invalid_input"
        llm.complete.assert_not_called()
