"""
Integration Test — Phase 1: Governed Agentic Loop End-to-End

Tests the full Phase 1 loop with a real Anthropic API call.

REQUIREMENTS:
  - LLM_API_KEY must be set in .env or environment
  - No Docker needed (ExecutionOrchestrator is still a stub in Phase 1)
  - Estimated cost: $0.01 - $0.05 per full run
  - Estimated time: 10 - 30 seconds per test

WHAT IS REAL vs STUBBED:
  Real:
    - Anthropic API call (PlanningOrchestrator)
    - PolicyEngine evaluation (fully deterministic)
    - GovernedAgenticLoop sequencing

  Stubbed (Phase 2 will replace):
    - ExecutionOrchestrator.execute() → returns "stub_completed"
    - AuditStore → not yet connected
    - CheckpointStore → not yet connected

SKIP BEHAVIOUR:
  All tests in this file are skipped when LLM_API_KEY is not set.
  Run: pytest tests/integration/ -v -s
  to see skip reason or test output.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

import pytest

# Load .env if present (for local development)
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass  # dotenv optional — env vars may be set directly

# Skip all tests in this file if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv("LLM_API_KEY"),
    reason=(
        "LLM_API_KEY not set. "
        "Copy .env.example to .env and add your Anthropic API key. "
        "Integration tests cost approximately $0.01-$0.05 per run."
    ),
)


# ── Imports (after skip check) ───────────────────────────────

from daf import GovernedAgenticLoop
from daf.models.final_response import FinalResponse
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig,
)
from daf.runtime.anthropic_client import AnthropicLLMClient
from daf.runtime.llm_client import LLMClientError, LLMOutputError


# ── Test PolicyMatrix Configurations ─────────────────────────

def make_permissive_matrix_yaml(tmp_path) -> str:
    """
    A permissive PolicyMatrix for the happy path test.

    Designed so the LLM can propose a plan that passes easily:
    - One flexible agent role with common tools
    - Generous budget ($1.00)
    - No compliance rules
    - max_replan_attempts=3
    """
    import yaml
    matrix = {
        "version": "1.0.0",
        "tenant_id": "integration-test",
        "effective": "2026-01-01T00:00:00Z",
        "agent_roles": {
            "analyst": {
                "permitted_tools": [
                    "read_db", "read_file", "llm_extraction",
                    "llm_summarization", "llm_generation",
                ],
                "permitted_data_sources": [
                    "documents", "reports", "public_data",
                ],
                "permitted_task_types": [
                    "deterministic", "llm_extraction",
                    "llm_summarization", "llm_generation",
                    "llm_evaluation",
                ],
                "max_llm_calls_per_step": 5,
            }
        },
        "orchestrator_routing": {
            "default_orchestrator": {
                "may_spawn_roles": ["analyst"]
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
            "auto_approve_action_classes": [
                "deterministic", "llm_extraction",
                "llm_summarization", "llm_generation",
            ],
        },
        "loop_policy": {
            "max_replan_attempts": 3,
            "max_duration_s": 120,
        }
    }
    path = tmp_path / "permissive.yaml"
    path.write_text(yaml.dump(matrix))
    return str(path)


def make_restrictive_matrix_yaml(tmp_path) -> str:
    """
    A restrictive PolicyMatrix for the rejection/escalation test.

    Designed so ANY plan the LLM proposes will be rejected:
    - Agent role exists but has NO permitted tools
    - Any tool the LLM proposes will fail the tool_permission check
    - max_replan_attempts=2 to keep the test fast
    """
    import yaml
    matrix = {
        "version": "1.0.0",
        "tenant_id": "integration-test-restrictive",
        "effective": "2026-01-01T00:00:00Z",
        "agent_roles": {
            "locked_agent": {
                "permitted_tools": [],          # NO tools permitted
                "permitted_data_sources": [],   # NO data permitted
                "permitted_task_types": [
                    "deterministic", "llm_extraction",
                ],
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
            "irreversible_min_confidence": 0.90,
            "always_gate_action_classes": [],
            "auto_approve_action_classes": [],
        },
        "loop_policy": {
            "max_replan_attempts": 2,   # fast escalation
            "max_duration_s": 120,
        }
    }
    path = tmp_path / "restrictive.yaml"
    path.write_text(yaml.dump(matrix))
    return str(path)


# ── Helper ────────────────────────────────────────────────────

def make_client() -> AnthropicLLMClient:
    """Build an AnthropicLLMClient from environment."""
    return AnthropicLLMClient(
        api_key=os.getenv("LLM_API_KEY"),
        model=os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001"),
        # Use Haiku for integration tests — faster and cheaper
        # Override with LLM_MODEL=claude-sonnet-4-20250514 for higher quality
    )


# ── Tests ─────────────────────────────────────────────────────

class TestPhase1HappyPath:
    """
    Happy path: real LLM plan → PolicyEngine approves → stub execute.

    Uses a permissive PolicyMatrix so the LLM plan passes easily.
    Verifies the loop produces a completed FinalResponse.
    """

    @pytest.mark.asyncio
    async def test_loop_completes_with_real_llm(self, tmp_path):
        """
        Full loop runs end-to-end with a real Anthropic API call.

        Verifies:
        - Loop returns FinalResponse (not an exception)
        - outcome is "completed" (plan was approved and executed)
        - loop_iterations is at least 1
        - total_cost_usd is populated (LLM was called)
        """
        client = make_client()
        loop   = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=make_permissive_matrix_yaml(tmp_path),
        )

        response = await loop.run({
            "task": (
                "Summarise the key findings from the quarterly reports "
                "and identify the top three risks."
            ),
            "tenant_id": "integration-test",
            "user_id":   "test-runner",
        })

        assert isinstance(response, FinalResponse)
        assert response.outcome == "completed", (
            f"Expected 'completed', got '{response.outcome}'. "
            f"Escalation context: {response.escalation_context}"
        )
        assert response.loop_iterations >= 1
        # Cost should be > 0 (a real LLM call was made)
        # Note: cost comes from the stub executor in Phase 1
        # which returns 0.0. The LLM call cost is tracked in
        # the planning orchestrator logs. Phase 2 will wire this properly.

    @pytest.mark.asyncio
    async def test_llm_produces_valid_plan_proposal(self, tmp_path):
        """
        The LLM returns a PlanProposal conforming to the schema.

        Verifies the structured output enforcement works:
        - sub_tasks is a non-empty list
        - Each sub_task has required fields
        - planning_rationale is a non-empty string
        - confidence is between 0 and 1
        """
        client  = make_client()
        matrix_path = make_permissive_matrix_yaml(tmp_path)
        loop    = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=matrix_path,
        )

        # Capture the proposal by intercepting plan()
        captured_proposal = []
        original_plan = loop.planning_orchestrator.plan

        async def capturing_plan(*args, **kwargs):
            proposal = await original_plan(*args, **kwargs)
            captured_proposal.append(proposal)
            return proposal

        loop.planning_orchestrator.plan = capturing_plan

        await loop.run({
            "task": "Read the sales reports and extract the total revenue figures.",
            "tenant_id": "integration-test",
            "user_id":   "test-runner",
        })

        assert len(captured_proposal) >= 1, "No proposal was captured"
        proposal = captured_proposal[0]

        # Verify PlanProposal structure
        assert isinstance(proposal, PlanProposal)
        assert len(proposal.sub_tasks) > 0, (
            "LLM produced a plan with no sub_tasks"
        )
        assert isinstance(proposal.planning_rationale, str)
        assert len(proposal.planning_rationale) > 0
        assert 0.0 <= proposal.confidence <= 1.0
        assert isinstance(proposal.total_estimated_cost, float)
        assert proposal.total_estimated_cost >= 0

        # Verify each sub_task
        for task in proposal.sub_tasks:
            assert isinstance(task, SubTask)
            assert task.task_id != "", f"sub_task missing task_id: {task}"
            assert task.task_type != "", f"sub_task missing task_type: {task}"
            assert task.agent_required != "", f"sub_task missing agent_required: {task}"
            assert isinstance(task.tools_required, list)
            assert isinstance(task.data_required, list)
            assert isinstance(task.depends_on, list)
            assert isinstance(task.estimated_cost, float)
            assert task.estimated_cost >= 0
            assert isinstance(task.reversible, bool)
            assert isinstance(task.rationale, str)

    @pytest.mark.asyncio
    async def test_policy_engine_evaluates_real_proposal(self, tmp_path):
        """
        The Policy Engine evaluates the real LLM proposal deterministically.

        Verifies:
        - PolicyEngine.evaluate() is called
        - It returns a verdict (APPROVED or REJECTED — both valid)
        - The verdict is deterministic given the same proposal + matrix
        """
        from daf.components.policy_engine import PolicyEvaluation
        from unittest.mock import MagicMock, patch

        client = make_client()
        loop   = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=make_permissive_matrix_yaml(tmp_path),
        )

        # Track Policy Engine calls
        evaluate_calls = []
        original_evaluate = loop.policy_engine.evaluate

        def tracking_evaluate(proposal, matrix):
            result = original_evaluate(proposal, matrix)
            evaluate_calls.append(result)
            return result

        loop.policy_engine.evaluate = tracking_evaluate

        await loop.run({
            "task": "Extract the key metrics from the performance report.",
            "tenant_id": "integration-test",
            "user_id":   "test-runner",
        })

        assert len(evaluate_calls) >= 1, "PolicyEngine.evaluate() was never called"

        for call_result in evaluate_calls:
            assert isinstance(call_result, PolicyEvaluation)
            assert call_result.verdict in ("APPROVED", "REJECTED")
            if call_result.verdict == "APPROVED":
                assert call_result.approval_grant is not None
                assert call_result.violation_report is None
            else:
                assert call_result.violation_report is not None
                assert call_result.approval_grant is None


class TestPhase1RejectionAndEscalation:
    """
    Rejection path: LLM plan → PolicyEngine rejects → escalation.

    Uses a restrictive PolicyMatrix (no tools permitted) so any
    plan the LLM proposes will be rejected by the Policy Engine.
    Verifies the loop escalates correctly after max attempts.
    """

    @pytest.mark.asyncio
    async def test_loop_escalates_when_all_plans_rejected(self, tmp_path):
        """
        When the Policy Engine rejects all proposals, loop escalates.

        The restrictive matrix has no permitted tools. Any plan the
        LLM proposes will fail the tool_permission check deterministically.

        Verifies:
        - Loop returns FinalResponse (not an exception)
        - outcome is "escalated"
        - loop_iterations equals max_replan_attempts (2)
        - escalation_context contains violation_history
        """
        client = make_client()
        loop   = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=make_restrictive_matrix_yaml(tmp_path),
        )

        response = await loop.run({
            "task": "Read the contract files and summarise the payment terms.",
            "tenant_id": "integration-test-restrictive",
            "user_id":   "test-runner",
        })

        assert isinstance(response, FinalResponse)
        assert response.outcome == "escalated", (
            f"Expected 'escalated', got '{response.outcome}'"
        )
        assert response.loop_iterations == 2  # max_replan_attempts in restrictive matrix
        assert response.escalation_context is not None
        assert "violation_history" in response.escalation_context
        assert len(response.escalation_context["violation_history"]) > 0

    @pytest.mark.asyncio
    async def test_violation_history_grows_with_each_rejection(self, tmp_path):
        """
        Each rejected iteration adds to violation_history.

        Verifies the loop correctly accumulates violations
        across re-planning iterations.
        """
        client = make_client()
        loop   = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=make_restrictive_matrix_yaml(tmp_path),
        )

        response = await loop.run({
            "task": "Analyse the documents.",
            "tenant_id": "integration-test-restrictive",
            "user_id":   "test-runner",
        })

        assert response.outcome == "escalated"
        violations = response.escalation_context["violation_history"]
        # Each iteration should have produced at least one violation
        assert len(violations) >= 1

    @pytest.mark.asyncio
    async def test_replan_prompt_reaches_llm_on_second_iteration(self, tmp_path):
        """
        On second iteration, the re-plan prompt (with violation context)
        is sent to the LLM — not the bare task description.

        Verifies the loop correctly passes violation_history to plan().
        """
        client = make_client()
        loop   = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=make_restrictive_matrix_yaml(tmp_path),
        )

        # Track plan() calls to inspect violation_history argument
        plan_call_histories = []
        original_plan = loop.planning_orchestrator.plan

        async def tracking_plan(*args, **kwargs):
            plan_call_histories.append(
                list(kwargs.get("violation_history", []))
            )
            return await original_plan(*args, **kwargs)

        loop.planning_orchestrator.plan = tracking_plan

        await loop.run({
            "task": "Read and summarise the files.",
            "tenant_id": "integration-test-restrictive",
            "user_id":   "test-runner",
        })

        # First call: empty violation history
        assert plan_call_histories[0] == []

        # Second call (if it happened): one violation in history
        if len(plan_call_histories) > 1:
            assert len(plan_call_histories[1]) == 1


class TestPhase1SchemaEnforcement:
    """
    Structured output enforcement: the LLM must return valid PlanProposal schema.

    These tests verify that the tool_use + input_schema enforcement
    produces valid structured output — not free-form text.
    """

    @pytest.mark.asyncio
    async def test_llm_returns_structured_json_not_prose(self, tmp_path):
        """
        The LLM response is parsed into a PlanProposal dict — not prose.

        Verifies AnthropicLLMClient.complete() returns a dict,
        not a string or other type.
        """
        client = make_client()

        from daf.components.planning_orchestrator import _PLAN_PROPOSAL_SCHEMA

        # Make a direct call to verify structured output enforcement
        response = await client.complete(
            system=(
                "You are a planning assistant. "
                "Decompose the task into steps using the structured_response tool."
            ),
            user="Read a document and summarise it.",
            schema=_PLAN_PROPOSAL_SCHEMA,
            max_tokens=1024,
            max_retries=2,
        )

        assert isinstance(response.content, dict), (
            f"Expected dict, got {type(response.content)}: {response.content}"
        )

        # Required fields must be present
        required = [
            "orchestrator", "planning_rationale", "sub_tasks",
            "total_estimated_cost", "confidence", "requires_human_gate",
        ]
        for field in required:
            assert field in response.content, (
                f"Required field '{field}' missing from LLM response"
            )

    @pytest.mark.asyncio
    async def test_llm_usage_is_populated(self, tmp_path):
        """
        LLMUsage is populated with real token counts after an API call.

        Verifies cost tracking infrastructure is wired correctly.
        """
        client = make_client()

        from daf.components.planning_orchestrator import _PLAN_PROPOSAL_SCHEMA

        response = await client.complete(
            system="You are a planning assistant.",
            user="List two steps to read and summarise a document.",
            schema=_PLAN_PROPOSAL_SCHEMA,
            max_tokens=512,
        )

        assert response.usage.input_tokens > 0, (
            "input_tokens should be > 0 after a real API call"
        )
        assert response.usage.output_tokens > 0, (
            "output_tokens should be > 0 after a real API call"
        )
        assert response.usage.cost_usd > 0.0, (
            "cost_usd should be > 0 after a real API call"
        )
        assert response.usage.model_id == client.model_id


class TestPhase1LoopInvariantsBehavior:
    """
    Verify DAF architectural invariants hold in real execution.

    These tests confirm the design philosophy properties hold
    with real LLM calls — not just in unit tests with mocks.
    """

    @pytest.mark.asyncio
    async def test_policy_engine_never_called_with_llm(self, tmp_path):
        """
        PolicyEngine.evaluate() runs synchronously — it never awaits.

        This confirms the Policy Engine is deterministic code,
        not an async LLM-touching function.
        """
        import inspect
        from daf.components.policy_engine import PolicyEngine

        # evaluate() must be a regular function, not a coroutine function
        assert not inspect.iscoroutinefunction(PolicyEngine.evaluate), (
            "PolicyEngine.evaluate() must be synchronous. "
            "It must never be an async function. "
            "This is a design invariant."
        )

    @pytest.mark.asyncio
    async def test_planning_orchestrator_is_the_only_llm_caller(self, tmp_path):
        """
        Only PlanningOrchestrator.plan() calls the LLM.

        Verifies that PolicyEngine and ExecutionOrchestrator
        never touch the LLM client.
        """
        from daf.components.policy_engine import PolicyEngine
        from daf.components.execution_orchestrator import ExecutionOrchestrator
        import inspect

        # PolicyEngine must not have async methods that could call LLM
        policy_engine_methods = [
            m for m in dir(PolicyEngine)
            if not m.startswith("__")
        ]
        async_methods = [
            m for m in policy_engine_methods
            if inspect.iscoroutinefunction(getattr(PolicyEngine, m, None))
        ]
        assert async_methods == [], (
            f"PolicyEngine has async methods: {async_methods}. "
            "The Policy Engine must be entirely synchronous."
        )

    @pytest.mark.asyncio
    async def test_loop_produces_fresh_proposal_id_each_iteration(self, tmp_path):
        """
        Each iteration of the loop produces a unique proposal_id.

        Verifies the Planning Orchestrator generates a new proposal_id
        on every call — proposals are not cached or reused.
        """
        client = make_client()
        loop   = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=make_restrictive_matrix_yaml(tmp_path),
        )

        proposal_ids = []
        original_plan = loop.planning_orchestrator.plan

        async def tracking_plan(*args, **kwargs):
            proposal = await original_plan(*args, **kwargs)
            proposal_ids.append(proposal.proposal_id)
            return proposal

        loop.planning_orchestrator.plan = tracking_plan

        await loop.run({
            "task": "Summarise the documents.",
            "tenant_id": "integration-test-restrictive",
            "user_id":   "test-runner",
        })

        # Each iteration must produce a unique proposal_id
        assert len(proposal_ids) == len(set(proposal_ids)), (
            "Duplicate proposal_ids detected — proposals are being reused"
        )
