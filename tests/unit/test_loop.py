"""
Unit tests for GovernedAgenticLoop.

All LLM calls mocked. All external services mocked.
Tests verify the loop logic — not the components inside it.

Coverage:
  - Happy path: plan → approved → execute → completed
  - Violation path: plan → rejected → re-plan → approved → execute
  - Escalation path: max attempts reached → escalated
  - Policy Engine forced escalation → escalated
  - LLMClientError propagates (not caught by loop)
  - LLMOutputError propagates (not caught by loop)
  - Loop uses policy_matrix max_replan_attempts for termination
  - loop.run() returns FinalResponse in all non-error paths
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import Any

import pytest

from daf.loop import GovernedAgenticLoop
from daf.components.policy_engine import PolicyEvaluation
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.models.execution_result import ExecutionResult
from daf.models.final_response import FinalResponse
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig,
)
from daf.models.violation_report import ViolationReport, Violation
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.llm_client import LLMClient, LLMClientError, LLMOutputError


# ── Fixtures ─────────────────────────────────────────────────

def make_workflow_request(task: str = "Test task") -> WorkflowRequest:
    return WorkflowRequest(
        request_id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        user_id="test-user",
        tenant_id="test-tenant",
        task_description=task,
    )


def make_policy_matrix(max_replan: int = 3) -> PolicyMatrix:
    return PolicyMatrix(
        version="1.0.0",
        tenant_id="test-tenant",
        effective="2026-01-01T00:00:00Z",
        agent_roles={
            "test_agent": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["test_data"],
                permitted_task_types=["llm_extraction"],
            )
        },
        budget_policy=BudgetPolicyConfig(max_cost_per_workflow_usd=0.50),
        loop_policy=LoopPolicyConfig(max_replan_attempts=max_replan),
        risk_policy=RiskPolicyConfig(),
        compliance_rules=[],
    )


def make_plan_proposal(iteration: int = 1) -> PlanProposal:
    return PlanProposal(
        proposal_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        iteration=iteration,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=[
            SubTask(
                task_id="ST-01",
                task_type="llm_extraction",
                agent_required="test_agent",
                tools_required=["read_db"],
                data_required=["test_data"],
                estimated_cost=0.03,
                reversible=True,
                rationale="test",
            )
        ],
        total_estimated_cost=0.03,
        confidence=0.90,
    )


def make_approval_grant(proposal: PlanProposal) -> ApprovalGrant:
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=proposal.proposal_id,
        approved_plan=proposal,
        agent_permissions={
            "test_agent": AgentPermissions(
                tools=["read_db"],
                data_sources=["test_data"],
            )
        },
        gated_tasks=[],
        execution_constraints={
            "max_cost_usd": 0.50,
            "human_gate_required": False,
        },
    )


def make_violation_report(
    proposal_id: uuid.UUID | None = None,
    escalate: bool = False,
) -> ViolationReport:
    return ViolationReport(
        proposal_id=proposal_id or uuid.uuid4(),
        violations=[
            Violation(
                task_id="ST-01",
                dimension="tool_permission",
                severity="blocking",
                detail="Role may not call forbidden_tool",
                suggestion="Use read_db instead",
            )
        ],
        approvable_task_ids=[],
        escalate_to_human=escalate,
    )


def make_exec_result(grant: ApprovalGrant) -> ExecutionResult:
    return ExecutionResult(
        grant_id=grant.grant_id,
        proposal_id=grant.proposal_id,
        outcome="completed",
        step_results=[],
        total_cost_usd=0.03,
        total_duration_ms=1200,
        completed_at=datetime.now(timezone.utc),
    )


def make_mock_llm() -> LLMClient:
    mock = AsyncMock(spec=LLMClient)
    mock.model_id = "claude-sonnet-4-20250514"
    return mock


def build_loop(
    llm: LLMClient | None = None,
    matrix: PolicyMatrix | None = None,
) -> GovernedAgenticLoop:
    """Build a GovernedAgenticLoop with all components mocked."""
    import tempfile, yaml

    _matrix = matrix or make_policy_matrix()
    _llm    = llm or make_mock_llm()

    # Write a minimal policy matrix YAML (PolicyEngine needs a file)
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", delete=False, mode="w"
    ) as f:
        yaml.dump(_matrix.model_dump(), f)
        tmp = f.name

    loop = GovernedAgenticLoop(
        llm_client=_llm,
        policy_matrix=tmp,
    )
    # Override cached matrix so we control it
    loop.policy_engine._cached_matrix = _matrix
    return loop


# ── Happy Path ───────────────────────────────────────────────

class TestGovernedAgenticLoopHappyPath:
    """Plan → Approved → Execute → Completed."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_completed(self):
        """Clean plan, approved first time, executes successfully."""
        loop   = build_loop()
        matrix = make_policy_matrix()
        loop.policy_engine._cached_matrix = matrix

        proposal = make_plan_proposal(iteration=1)
        grant    = make_approval_grant(proposal)
        result   = make_exec_result(grant)

        # Mock: planning returns a valid proposal
        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)

        # Mock: policy engine approves
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="APPROVED",
            approval_grant=grant,
        ))

        # Mock: execution succeeds
        loop.execution_orchestrator.execute = AsyncMock(return_value=result)

        response = await loop.run({
            "task": "Analyse contracts",
            "tenant_id": "test-tenant",
        })

        assert response.outcome == "completed"
        assert response.loop_iterations == 1
        assert response.total_cost_usd == 0.03

    @pytest.mark.asyncio
    async def test_happy_path_calls_plan_with_policy_matrix(self):
        """plan() is called with the policy_matrix argument."""
        loop   = build_loop()
        matrix = make_policy_matrix()
        loop.policy_engine._cached_matrix = matrix

        proposal = make_plan_proposal()
        grant    = make_approval_grant(proposal)

        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="APPROVED",
            approval_grant=grant,
        ))
        loop.execution_orchestrator.execute = AsyncMock(
            return_value=make_exec_result(grant)
        )

        await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        call_kwargs = loop.planning_orchestrator.plan.call_args.kwargs
        assert call_kwargs["policy_matrix"] is matrix

    @pytest.mark.asyncio
    async def test_happy_path_calls_plan_with_empty_violation_history(self):
        """On first iteration, violation_history is empty."""
        loop   = build_loop()
        matrix = make_policy_matrix()
        loop.policy_engine._cached_matrix = matrix

        proposal = make_plan_proposal()
        grant    = make_approval_grant(proposal)

        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="APPROVED",
            approval_grant=grant,
        ))
        loop.execution_orchestrator.execute = AsyncMock(
            return_value=make_exec_result(grant)
        )

        await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        call_kwargs = loop.planning_orchestrator.plan.call_args.kwargs
        assert call_kwargs["violation_history"] == []
        assert call_kwargs["iteration"] == 1


# ── Violation and Re-plan Path ────────────────────────────────

class TestGovernedAgenticLoopReplan:
    """Plan → Rejected → Re-plan → Approved → Execute."""

    @pytest.mark.asyncio
    async def test_replan_on_first_rejection(self):
        """Loop re-plans once after rejection and succeeds on second attempt."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=3)
        loop.policy_engine._cached_matrix = matrix

        proposal_1 = make_plan_proposal(iteration=1)
        proposal_2 = make_plan_proposal(iteration=2)
        violation  = make_violation_report(proposal_id=proposal_1.proposal_id)
        grant      = make_approval_grant(proposal_2)

        # First call: rejected. Second call: approved.
        loop.planning_orchestrator.plan = AsyncMock(
            side_effect=[proposal_1, proposal_2]
        )
        loop.policy_engine.evaluate = MagicMock(side_effect=[
            PolicyEvaluation(verdict="REJECTED", violation_report=violation),
            PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
        ])
        loop.execution_orchestrator.execute = AsyncMock(
            return_value=make_exec_result(grant)
        )

        response = await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        assert response.outcome == "completed"
        assert response.loop_iterations == 2

    @pytest.mark.asyncio
    async def test_replan_passes_violation_history(self):
        """Second plan() call receives the violation from iteration 1."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=3)
        loop.policy_engine._cached_matrix = matrix

        proposal_1 = make_plan_proposal(iteration=1)
        proposal_2 = make_plan_proposal(iteration=2)
        violation  = make_violation_report(proposal_id=proposal_1.proposal_id)
        grant      = make_approval_grant(proposal_2)

        loop.planning_orchestrator.plan = AsyncMock(
            side_effect=[proposal_1, proposal_2]
        )
        loop.policy_engine.evaluate = MagicMock(side_effect=[
            PolicyEvaluation(verdict="REJECTED", violation_report=violation),
            PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
        ])
        loop.execution_orchestrator.execute = AsyncMock(
            return_value=make_exec_result(grant)
        )

        await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        # Second plan() call should include the violation
        second_call_kwargs = loop.planning_orchestrator.plan.call_args_list[1].kwargs
        assert len(second_call_kwargs["violation_history"]) == 1
        assert second_call_kwargs["violation_history"][0] is violation
        assert second_call_kwargs["iteration"] == 2

    @pytest.mark.asyncio
    async def test_multiple_rejections_accumulate_history(self):
        """Each rejection adds to violation_history for subsequent re-plans."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=5)
        loop.policy_engine._cached_matrix = matrix

        proposals  = [make_plan_proposal(iteration=i) for i in range(1, 5)]
        violations = [make_violation_report() for _ in range(3)]
        grant      = make_approval_grant(proposals[3])

        loop.planning_orchestrator.plan = AsyncMock(side_effect=proposals)
        loop.policy_engine.evaluate = MagicMock(side_effect=[
            PolicyEvaluation(verdict="REJECTED", violation_report=violations[0]),
            PolicyEvaluation(verdict="REJECTED", violation_report=violations[1]),
            PolicyEvaluation(verdict="REJECTED", violation_report=violations[2]),
            PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
        ])
        loop.execution_orchestrator.execute = AsyncMock(
            return_value=make_exec_result(grant)
        )

        response = await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        assert response.outcome == "completed"
        assert response.loop_iterations == 4

        # 4th plan() call should have all 3 violations in history
        fourth_call = loop.planning_orchestrator.plan.call_args_list[3].kwargs
        assert len(fourth_call["violation_history"]) == 3


# ── Escalation Paths ─────────────────────────────────────────

class TestGovernedAgenticLoopEscalation:
    """Tests for loop escalation — max attempts or forced escalation."""

    @pytest.mark.asyncio
    async def test_max_attempts_reached_returns_escalated(self):
        """Loop returns escalated when max_replan_attempts exhausted."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=3)
        loop.policy_engine._cached_matrix = matrix

        proposal  = make_plan_proposal()
        violation = make_violation_report()

        # Always rejected, never approved
        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="REJECTED",
            violation_report=violation,
        ))

        response = await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        assert response.outcome == "escalated"
        assert response.loop_iterations == 3  # max_replan_attempts

    @pytest.mark.asyncio
    async def test_max_attempts_respects_policy_matrix_setting(self):
        """Loop uses max_replan_attempts from PolicyMatrix, not a hardcoded value."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=2)  # set to 2
        loop.policy_engine._cached_matrix = matrix

        proposal  = make_plan_proposal()
        violation = make_violation_report()

        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="REJECTED",
            violation_report=violation,
        ))

        response = await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        assert response.loop_iterations == 2  # stopped at 2, not 3

    @pytest.mark.asyncio
    async def test_forced_escalation_exits_loop_early(self):
        """escalate_to_human=True on violation exits loop before max attempts."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=5)  # generous limit
        loop.policy_engine._cached_matrix = matrix

        proposal  = make_plan_proposal()
        # First rejection has escalate_to_human=True
        violation = make_violation_report(escalate=True)

        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="REJECTED",
            violation_report=violation,
        ))

        response = await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        # Should escalate after iteration 1, not run 5 times
        assert response.outcome == "escalated"
        assert response.loop_iterations == 1

    @pytest.mark.asyncio
    async def test_escalated_response_includes_violation_context(self):
        """Escalated FinalResponse carries the violation history."""
        loop   = build_loop()
        matrix = make_policy_matrix(max_replan=1)
        loop.policy_engine._cached_matrix = matrix

        proposal  = make_plan_proposal()
        violation = make_violation_report()

        loop.planning_orchestrator.plan = AsyncMock(return_value=proposal)
        loop.policy_engine.evaluate = MagicMock(return_value=PolicyEvaluation(
            verdict="REJECTED",
            violation_report=violation,
        ))

        response = await loop.run({"task": "Test", "tenant_id": "test-tenant"})

        assert response.outcome == "escalated"
        assert response.escalation_context is not None
        assert "violation_history" in response.escalation_context


# ── Error Propagation ────────────────────────────────────────

class TestGovernedAgenticLoopErrors:
    """LLM errors propagate — the loop does not swallow them."""

    @pytest.mark.asyncio
    async def test_llm_client_error_propagates(self):
        """LLMClientError from PlanningOrchestrator propagates out of run()."""
        loop   = build_loop()
        matrix = make_policy_matrix()
        loop.policy_engine._cached_matrix = matrix

        loop.planning_orchestrator.plan = AsyncMock(
            side_effect=LLMClientError(
                "Connection timeout", provider="anthropic"
            )
        )

        with pytest.raises(LLMClientError, match="Connection timeout"):
            await loop.run({"task": "Test", "tenant_id": "test-tenant"})

    @pytest.mark.asyncio
    async def test_llm_output_error_propagates(self):
        """LLMOutputError from PlanningOrchestrator propagates out of run()."""
        loop   = build_loop()
        matrix = make_policy_matrix()
        loop.policy_engine._cached_matrix = matrix

        loop.planning_orchestrator.plan = AsyncMock(
            side_effect=LLMOutputError(
                "Schema failed after 3 attempts",
                raw_response="{}",
                attempt=3,
            )
        )

        with pytest.raises(LLMOutputError):
            await loop.run({"task": "Test", "tenant_id": "test-tenant"})

    @pytest.mark.asyncio
    async def test_llm_error_does_not_return_response(self):
        """When LLM fails, run() raises — it does NOT return a FinalResponse."""
        loop   = build_loop()
        matrix = make_policy_matrix()
        loop.policy_engine._cached_matrix = matrix

        loop.planning_orchestrator.plan = AsyncMock(
            side_effect=LLMClientError("auth failed", provider="anthropic")
        )

        result = None
        try:
            result = await loop.run({"task": "Test", "tenant_id": "test-tenant"})
        except LLMClientError:
            pass

        assert result is None  # never returned a response


# ── Constructor ──────────────────────────────────────────────

class TestGovernedAgenticLoopConstructor:
    """Tests for GovernedAgenticLoop.__init__()."""

    def test_constructor_accepts_llm_client(self):
        """Constructor accepts an LLMClient instance."""
        import tempfile, yaml
        matrix = make_policy_matrix()
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(matrix.model_dump(), f)
            tmp = f.name

        llm  = make_mock_llm()
        loop = GovernedAgenticLoop(llm_client=llm, policy_matrix=tmp)

        assert loop.planning_orchestrator._llm is llm

    def test_constructor_wires_policy_engine(self):
        """PolicyEngine is initialized with the policy_matrix path."""
        import tempfile, yaml
        matrix = make_policy_matrix()
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(matrix.model_dump(), f)
            tmp = f.name

        loop = GovernedAgenticLoop(llm_client=make_mock_llm(), policy_matrix=tmp)

        assert loop.policy_engine is not None
        assert str(loop.policy_engine._policy_matrix_path) == tmp
