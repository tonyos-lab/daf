"""
Adversarial tests — Layer 2: Policy Engine Invariants.

These tests verify that the Policy Engine's deterministic guarantees
hold under adversarial inputs: malformed proposals, manipulated
confidence scores, and attempts to bypass policy dimensions.

ALL TESTS MUST PASS. Any failure is a security regression.
"""
from __future__ import annotations

import uuid
import pytest
import tempfile
import yaml

from daf.components.policy_engine import PolicyEngine, PolicyEvaluation
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig, ComplianceRule,
    ComplianceAction, Condition, ConditionOperator,
)


# ── Fixtures ─────────────────────────────────────────────────

def make_matrix(**overrides) -> PolicyMatrix:
    defaults = dict(
        version="1.0.0", tenant_id="test",
        effective="2026-01-01T00:00:00Z",
        agent_roles={
            "test_agent": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["test_data"],
                permitted_task_types=["llm_extraction"],
                max_llm_calls_per_step=3,
            )
        },
        budget_policy=BudgetPolicyConfig(
            max_cost_per_step_usd=0.10,
            max_cost_per_workflow_usd=0.50,
        ),
        loop_policy=LoopPolicyConfig(max_replan_attempts=3),
        risk_policy=RiskPolicyConfig(irreversible_min_confidence=0.90),
        compliance_rules=[],
    )
    defaults.update(overrides)
    return PolicyMatrix(**defaults)


def make_engine(matrix: PolicyMatrix | None = None) -> PolicyEngine:
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._policy_matrix_path = None
    engine._cached_matrix      = matrix or make_matrix()
    return engine


def make_proposal(**overrides) -> PlanProposal:
    defaults = dict(
        request_id=uuid.uuid4(),
        iteration=1,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=[SubTask(
            task_id="ST-01",
            task_type="llm_extraction",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=["test_data"],
            estimated_cost=0.05,
            reversible=True,
            rationale="test",
        )],
        total_estimated_cost=0.05,
        confidence=0.95,
    )
    defaults.update(overrides)
    return PlanProposal(**defaults)


# ── Determinism ───────────────────────────────────────────────

class TestPolicyEngineDeterminism:
    """
    The Policy Engine must always return the same result
    for the same inputs. This is the core security guarantee.
    """

    def test_same_proposal_same_matrix_same_result(self):
        """
        Evaluating the same proposal with the same matrix
        twice always returns the same verdict.

        SECURITY: If this fails, the Policy Engine has hidden
        state that could be exploited.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal()

        result_a = engine.evaluate(proposal, matrix)
        result_b = engine.evaluate(proposal, matrix)

        assert result_a.verdict == result_b.verdict

    def test_evaluation_does_not_modify_proposal(self):
        """
        Evaluation must not modify the proposal it receives.

        SECURITY: If the Policy Engine modifies proposals, a
        malicious proposal could change its own evaluation.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal()

        original_sub_tasks = [t.task_id for t in proposal.sub_tasks]
        original_cost      = proposal.total_estimated_cost
        original_confidence = proposal.confidence

        engine.evaluate(proposal, matrix)

        assert [t.task_id for t in proposal.sub_tasks] == original_sub_tasks
        assert proposal.total_estimated_cost == original_cost
        assert proposal.confidence           == original_confidence

    def test_evaluation_does_not_modify_matrix(self):
        """
        Evaluation must not modify the PolicyMatrix it receives.

        SECURITY: If evaluation modifies the matrix, a malicious
        proposal could weaken future evaluations.
        """
        matrix          = make_matrix()
        engine          = make_engine(matrix)
        original_roles  = list(matrix.agent_roles.keys())
        original_budget = matrix.budget_policy.max_cost_per_workflow_usd

        proposal = make_proposal()
        engine.evaluate(proposal, matrix)

        assert list(matrix.agent_roles.keys()) == original_roles
        assert matrix.budget_policy.max_cost_per_workflow_usd == original_budget


# ── Malformed Proposals Cannot Produce Approval ──────────────

class TestMalformedProposalHandling:
    """
    Malformed or adversarial proposals must be rejected or handled
    without producing incorrect approvals.
    """

    def test_empty_sub_tasks_approved_with_no_violations(self):
        """
        A proposal with no sub-tasks is approved vacuously.
        This is not a security issue — an empty plan executes nothing.
        The ExecutionOrchestrator handles the no-tasks case.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[], total_estimated_cost=0.0)

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "APPROVED"
        assert result.approval_grant.gated_tasks == []

    def test_unknown_agent_role_rejected(self):
        """
        A sub-task with an agent role not in the PolicyMatrix
        is always rejected — regardless of other fields.

        SECURITY: An attacker cannot invent a new agent role
        to gain permissions that don't exist in the matrix.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-01",
            task_type="llm_extraction",
            agent_required="admin_agent",  # not in matrix
            tools_required=[],
            data_required=[],
            estimated_cost=0.01,
            reversible=True,
            rationale="test",
        )])

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"

    def test_forbidden_tool_rejected_regardless_of_other_fields(self):
        """
        A task requesting an unpermitted tool is always rejected.
        No other field (confidence, rationale, cost) can override this.

        SECURITY: Tool permission is a hard check, not a heuristic.
        """
        matrix = make_matrix()
        engine = make_engine(matrix)
        for tool in ["write_db", "delete_record", "send_email",
                     "admin_access", "execute_code"]:
            proposal = make_proposal(sub_tasks=[SubTask(
                task_id="ST-01",
                task_type="llm_extraction",
                agent_required="test_agent",
                tools_required=[tool],    # forbidden
                data_required=["test_data"],
                estimated_cost=0.001,     # very cheap
                reversible=True,
                rationale="critical business need",  # compelling rationale
            )],
            confidence=0.999)             # very high confidence

            result = engine.evaluate(proposal, matrix)
            assert result.verdict == "REJECTED", (
                f"Tool '{tool}' should be rejected but was approved"
            )

    def test_zero_cost_task_still_evaluated_for_permissions(self):
        """
        A zero-cost task with forbidden tools is still rejected.

        SECURITY: Cost cannot be used to bypass permission checks.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-01",
            task_type="llm_extraction",
            agent_required="test_agent",
            tools_required=["admin_tool"],  # forbidden
            data_required=[],
            estimated_cost=0.0,             # free — should not bypass checks
            reversible=True,
            rationale="test",
        )])

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"

    def test_high_confidence_does_not_bypass_tool_permission(self):
        """
        High confidence cannot override tool permission violations.

        SECURITY: Confidence is only relevant for risk thresholds
        on irreversible actions. It does not affect permission checks.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal(
            confidence=1.0,  # maximum confidence
            sub_tasks=[SubTask(
                task_id="ST-01",
                task_type="llm_extraction",
                agent_required="test_agent",
                tools_required=["forbidden_tool"],
                data_required=["test_data"],
                estimated_cost=0.01,
                reversible=True,
                rationale="high confidence plan",
            )]
        )

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"


# ── Budget Cannot Be Bypassed ────────────────────────────────

class TestBudgetCannotBeBypassed:
    """
    Budget limits must be enforced regardless of proposal content.
    """

    def test_workflow_over_budget_rejected_regardless_of_confidence(self):
        """
        A workflow exceeding the budget limit is always rejected.
        High confidence cannot override budget enforcement.
        """
        matrix = make_matrix(
            budget_policy=BudgetPolicyConfig(
                max_cost_per_step_usd=0.10,
                max_cost_per_workflow_usd=0.10,
            )
        )
        engine   = make_engine(matrix)
        proposal = make_proposal(
            confidence=0.99,
            total_estimated_cost=0.99,  # way over $0.10 limit
        )

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        budget_v = next(
            v for v in result.violation_report.violations
            if v.dimension == "budget"
        )
        assert budget_v.severity == "blocking"

    def test_step_over_budget_rejected(self):
        """
        A single step exceeding per-step budget is rejected.
        """
        matrix = make_matrix(
            budget_policy=BudgetPolicyConfig(
                max_cost_per_step_usd=0.01,
                max_cost_per_workflow_usd=1.00,
            )
        )
        engine   = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-01",
            task_type="llm_extraction",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=["test_data"],
            estimated_cost=0.99,    # over $0.01 per-step limit
            reversible=True,
            rationale="test",
        )])

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        assert any(
            v.dimension == "budget"
            for v in result.violation_report.violations
        )


# ── Violation Report Cannot Be Forged ────────────────────────

class TestViolationReportIntegrity:
    """
    ViolationReports are produced by the Policy Engine.
    They cannot be forged to look like approvals.
    """

    def test_rejected_outcome_has_no_approval_grant(self):
        """
        A REJECTED evaluation never has an ApprovalGrant.

        SECURITY: If a rejected evaluation had an ApprovalGrant,
        the ExecutionOrchestrator could be tricked into executing
        a rejected plan.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-01",
            task_type="llm_extraction",
            agent_required="test_agent",
            tools_required=["forbidden_tool"],
            data_required=["test_data"],
            estimated_cost=0.01,
            reversible=True,
            rationale="test",
        )])

        result = engine.evaluate(proposal, matrix)
        assert result.verdict    == "REJECTED"
        assert result.approval_grant is None

    def test_approved_outcome_has_no_violation_report(self):
        """
        An APPROVED evaluation never has a ViolationReport.

        SECURITY: If an approved evaluation had a ViolationReport,
        the GovernedAgenticLoop could be confused into re-planning
        an already-approved plan.
        """
        matrix   = make_matrix()
        engine   = make_engine(matrix)
        proposal = make_proposal()

        result = engine.evaluate(proposal, matrix)
        assert result.verdict         == "APPROVED"
        assert result.violation_report is None

    def test_all_blocking_violations_included_in_report(self):
        """
        All blocking violations are included in the ViolationReport.
        Short-circuiting after the first violation would hide others.

        SECURITY: Hidden violations could allow an attacker to
        address violations one at a time to gradually escalate.
        """
        matrix = make_matrix()
        engine = make_engine(matrix)

        # Two separate violations: forbidden tool AND forbidden data
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-01",
            task_type="llm_extraction",
            agent_required="test_agent",
            tools_required=["forbidden_tool"],     # violation 1
            data_required=["forbidden_data"],       # violation 2
            estimated_cost=0.01,
            reversible=True,
            rationale="test",
        )])

        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        dims = {v.dimension for v in result.violation_report.violations}
        assert "tool_permission" in dims
        assert "data_access"     in dims


# ── Compliance Rules Cannot Be Bypassed ──────────────────────

class TestComplianceRulesBypass:
    """
    Compliance rules with action=block cannot be bypassed
    by any content in the proposal.
    """

    def test_block_rule_cannot_be_bypassed_by_any_field(self):
        """
        A compliance rule with action=block always rejects,
        regardless of confidence, cost, or rationale.
        """
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="BLOCK-PII",
                condition=Condition(
                    field="data_required",
                    operator="contains",
                    value="pii_data",
                ),
                action=ComplianceAction.BLOCK,
                remediation_hint="Do not access PII directly",
            )
        ], agent_roles={
            "test_agent": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["test_data", "pii_data"],
                permitted_task_types=["llm_extraction"],
            )
        })
        engine = make_engine(matrix)

        for confidence in [0.5, 0.9, 0.99, 1.0]:
            proposal = make_proposal(
                confidence=confidence,
                sub_tasks=[SubTask(
                    task_id="ST-01",
                    task_type="llm_extraction",
                    agent_required="test_agent",
                    tools_required=["read_db"],
                    data_required=["pii_data"],   # triggers block rule
                    estimated_cost=0.001,
                    reversible=True,
                    rationale=f"critical compliance bypass attempt ({confidence})",
                )]
            )
            result = engine.evaluate(proposal, matrix)
            assert result.verdict == "REJECTED", (
                f"Block rule bypassed at confidence={confidence}"
            )
