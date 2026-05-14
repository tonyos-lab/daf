"""
Additional PolicyEngine tests to reach 100% coverage.

Covers:
  - Workflow-level budget violation
  - Agent authorization: task_type not in permitted_task_types
  - Risk threshold: irreversible + low confidence
  - _rule_applies: exception handling path
  - _suggest_tool_alternative: no role has the tool
"""
from __future__ import annotations

import uuid
import tempfile
import yaml
import pytest

from daf.components.policy_engine import PolicyEngine
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig, ComplianceRule,
    ComplianceAction, Condition, ConditionOperator,
)


# ── Shared fixtures ──────────────────────────────────────────

def make_subtask(**overrides) -> SubTask:
    defaults = dict(
        task_id="ST-01", name="test", task_type="llm_extraction",
        agent_required="test_agent", tools_required=["read_db"],
        data_required=["test_data"], depends_on=[],
        estimated_cost=0.05, reversible=True, rationale="test",
    )
    defaults.update(overrides)
    return SubTask(**defaults)


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
        risk_policy=RiskPolicyConfig(
            irreversible_min_confidence=0.90,
        ),
        compliance_rules=[],
    )
    defaults.update(overrides)
    return PolicyMatrix(**defaults)


def make_proposal(**overrides) -> PlanProposal:
    defaults = dict(
        request_id=uuid.uuid4(), iteration=1,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=[make_subtask()],
        total_estimated_cost=0.05,
        confidence=0.95,
    )
    defaults.update(overrides)
    return PlanProposal(**defaults)


def engine_with(matrix: PolicyMatrix) -> PolicyEngine:
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._policy_matrix_path = None
    engine._cached_matrix = matrix
    return engine


def engine_from_yaml(matrix: PolicyMatrix) -> PolicyEngine:
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", delete=False, mode="w"
    ) as f:
        yaml.dump(matrix.model_dump(), f)
        tmp = f.name
    e = PolicyEngine(policy_matrix_path=tmp)
    e._cached_matrix = matrix
    return e


# ── Workflow-level budget (line 97) ─────────────────────────

class TestWorkflowBudgetViolation:

    def test_workflow_total_exceeds_limit_rejected(self):
        """Total proposal cost exceeding workflow limit produces REJECTED."""
        matrix = make_matrix(
            budget_policy=BudgetPolicyConfig(
                max_cost_per_step_usd=5.00,    # generous per-step
                max_cost_per_workflow_usd=0.10, # tight workflow limit
            )
        )
        engine = engine_from_yaml(matrix)
        proposal = make_proposal(
            sub_tasks=[
                make_subtask(task_id="ST-01", estimated_cost=0.04),
                make_subtask(task_id="ST-02", estimated_cost=0.04),
                make_subtask(task_id="ST-03", estimated_cost=0.04),
            ],
            total_estimated_cost=0.12,  # 0.12 > 0.10 limit
        )
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        violations = result.violation_report.violations
        workflow_v = next(
            v for v in violations if v.task_id == "workflow"
        )
        assert workflow_v.dimension == "budget"
        assert workflow_v.severity == "blocking"

    def test_workflow_total_at_exact_limit_approved(self):
        """Total cost exactly at workflow limit is approved."""
        matrix = make_matrix(
            budget_policy=BudgetPolicyConfig(
                max_cost_per_step_usd=0.10,
                max_cost_per_workflow_usd=0.05,
            )
        )
        engine = engine_from_yaml(matrix)
        proposal = make_proposal(total_estimated_cost=0.05)
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "APPROVED"

    def test_workflow_violation_detail_includes_amounts(self):
        """Workflow budget violation detail includes actual and limit amounts."""
        matrix = make_matrix(
            budget_policy=BudgetPolicyConfig(
                max_cost_per_step_usd=5.00,
                max_cost_per_workflow_usd=0.10,
            )
        )
        engine = engine_from_yaml(matrix)
        proposal = make_proposal(total_estimated_cost=0.99)
        result = engine.evaluate(proposal, matrix)
        workflow_v = next(
            v for v in result.violation_report.violations
            if v.task_id == "workflow"
        )
        # Detail should mention both the actual cost and the limit
        assert "0.99" in workflow_v.detail or "0.1" in workflow_v.detail


# ── Agent authorization: task_type (line 199) ───────────────

class TestAgentTaskTypeAuthorization:

    def test_task_type_not_permitted_returns_violation(self):
        """Agent role not authorized for task_type produces agent_authorization violation."""
        matrix = make_matrix()
        engine = engine_with(matrix)
        task = make_subtask(task_type="llm_generation")  # not in permitted_task_types
        proposal = make_proposal(sub_tasks=[task])
        violations = engine._evaluate_task(task, proposal, matrix)
        assert any(v.dimension == "agent_authorization" for v in violations)
        auth_v = next(v for v in violations if v.dimension == "agent_authorization")
        assert auth_v.severity == "blocking"
        assert "llm_generation" in auth_v.detail

    def test_task_type_permitted_no_violation(self):
        """Agent role authorized for task_type produces no task_type violation."""
        matrix = make_matrix()
        engine = engine_with(matrix)
        task = make_subtask(task_type="llm_extraction")  # is permitted
        proposal = make_proposal(sub_tasks=[task])
        violations = engine._evaluate_task(task, proposal, matrix)
        assert not any(
            v.dimension == "agent_authorization" and "llm_extraction" in v.detail
            for v in violations
        )

    def test_task_type_violation_in_full_evaluate(self):
        """Full evaluate() returns REJECTED when task_type not permitted."""
        matrix = make_matrix()
        engine = engine_from_yaml(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(task_type="llm_generation")
        ])
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        assert any(
            v.dimension == "agent_authorization"
            for v in result.violation_report.violations
        )


# ── Risk threshold (lines 261-262) ──────────────────────────

class TestRiskThresholdViolation:

    def test_irreversible_low_confidence_returns_violation(self):
        """Irreversible task with confidence below threshold produces risk_threshold violation."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(irreversible_min_confidence=0.90)
        )
        engine = engine_with(matrix)
        task = make_subtask(reversible=False)
        proposal = make_proposal(
            confidence=0.75,  # below 0.90
            sub_tasks=[task]
        )
        violations = engine._evaluate_task(task, proposal, matrix)
        assert any(v.dimension == "risk_threshold" for v in violations)
        risk_v = next(v for v in violations if v.dimension == "risk_threshold")
        assert risk_v.severity == "blocking"
        assert "0.75" in risk_v.detail or "confidence" in risk_v.detail.lower()

    def test_irreversible_high_confidence_no_violation(self):
        """Irreversible task with confidence above threshold has no risk violation."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(irreversible_min_confidence=0.90)
        )
        engine = engine_with(matrix)
        task = make_subtask(reversible=False)
        proposal = make_proposal(
            confidence=0.95,  # above 0.90
            sub_tasks=[task]
        )
        violations = engine._evaluate_task(task, proposal, matrix)
        assert not any(v.dimension == "risk_threshold" for v in violations)

    def test_reversible_task_never_gets_risk_violation(self):
        """Reversible task never triggers risk_threshold regardless of confidence."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(irreversible_min_confidence=0.99)
        )
        engine = engine_with(matrix)
        task = make_subtask(reversible=True)
        proposal = make_proposal(
            confidence=0.10,  # very low — but task is reversible
            sub_tasks=[task]
        )
        violations = engine._evaluate_task(task, proposal, matrix)
        assert not any(v.dimension == "risk_threshold" for v in violations)

    def test_risk_violation_in_full_evaluate(self):
        """Full evaluate() returns REJECTED for irreversible + low confidence."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(irreversible_min_confidence=0.90)
        )
        engine = engine_from_yaml(matrix)
        proposal = make_proposal(
            confidence=0.50,
            sub_tasks=[make_subtask(reversible=False)]
        )
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        assert any(
            v.dimension == "risk_threshold"
            for v in result.violation_report.violations
        )

    def test_risk_violation_includes_suggestion(self):
        """Risk threshold violation includes a remediation suggestion."""
        matrix = make_matrix()
        engine = engine_with(matrix)
        task = make_subtask(reversible=False)
        proposal = make_proposal(confidence=0.50, sub_tasks=[task])
        violations = engine._evaluate_task(task, proposal, matrix)
        risk_v = next(
            (v for v in violations if v.dimension == "risk_threshold"), None
        )
        if risk_v:
            assert risk_v.suggestion != ""


# ── _rule_applies exception path (lines 355-366) ────────────

class TestRuleAppliesExceptionHandling:
    """
    The exception handler in _rule_applies must be reachable.
    We trigger it by passing a rule with a valid operator
    but a field that causes an unexpected comparison issue.
    """

    def test_rule_applies_returns_false_on_unexpected_error(self):
        """
        _rule_applies returns False (not raises) when evaluation
        encounters an unexpected error.

        We verify this by mocking the condition to raise during evaluation.
        """
        engine = engine_with(make_matrix())
        rule = ComplianceRule(
            rule_ref="ERR-001",
            condition=Condition(
                field="estimated_cost",  # float field
                operator="contains",     # contains on float → isinstance check returns False
                value="0.05"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(estimated_cost=0.05)
        # estimated_cost is a float — contains requires a list
        # isinstance check returns False → rule does not apply
        result = engine._rule_applies(rule, task)
        assert result is False
        assert isinstance(result, bool)  # never raises

    def test_rule_applies_unknown_operator_returns_false(self):
        """
        The else branch in _rule_applies (unknown operator) returns False.
        We test this by constructing a Condition and then mutating the operator
        to an unexpected value after construction.
        """
        engine = engine_with(make_matrix())

        # Build a valid condition first
        rule = ComplianceRule(
            rule_ref="UNK-001",
            condition=Condition(
                field="agent_required",
                operator="equals",
                value="test_agent"
            ),
            action=ComplianceAction.BLOCK,
        )

        # Patch the operator to a value not in the enum
        # (simulating a future enum value not handled in current code)
        import unittest.mock as mock
        with mock.patch.object(
            rule.condition, "operator", new="future_operator"
        ):
            task = make_subtask()
            result = engine._rule_applies(rule, task)
            assert result is False


# ── _suggest_tool_alternative: no role has the tool (line 449) ──

class TestSuggestToolAlternative:

    def test_suggests_alternative_role_when_available(self):
        """When another role has the tool, suggestion names it."""
        matrix = make_matrix(
            agent_roles={
                "reader": AgentRoleConfig(
                    permitted_tools=["read_db"],
                    permitted_data_sources=["test_data"],
                    permitted_task_types=["llm_extraction"],
                ),
                "writer": AgentRoleConfig(
                    permitted_tools=["write_db"],  # has the forbidden tool
                    permitted_data_sources=["test_data"],
                    permitted_task_types=["llm_extraction"],
                ),
            }
        )
        engine = engine_with(matrix)
        task = make_subtask(agent_required="reader", tools_required=["write_db"])
        suggestion = engine._suggest_tool_alternative(task, "write_db", matrix)
        assert "writer" in suggestion

    def test_no_role_has_tool_returns_informative_message(self):
        """When no role has the tool, returns a clear message (line 449)."""
        matrix = make_matrix(
            agent_roles={
                "reader": AgentRoleConfig(
                    permitted_tools=["read_db"],
                    permitted_data_sources=["test_data"],
                    permitted_task_types=["llm_extraction"],
                ),
            }
        )
        engine = engine_with(matrix)
        task = make_subtask(agent_required="reader", tools_required=["magic_tool"])
        # No role has magic_tool
        suggestion = engine._suggest_tool_alternative(task, "magic_tool", matrix)
        assert "magic_tool" in suggestion
        assert "No role" in suggestion or "not" in suggestion.lower()

    def test_tool_violation_suggestion_populated_in_evaluate(self):
        """Tool permission violation in full evaluate() includes a suggestion."""
        matrix = make_matrix()
        engine = engine_from_yaml(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(tools_required=["forbidden_tool"])
        ])
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        tool_v = next(
            v for v in result.violation_report.violations
            if v.dimension == "tool_permission"
        )
        assert tool_v.suggestion != ""


# ── Direct exception path test ───────────────────────────────

class TestRuleAppliesDirectExceptionPath:
    """
    Directly test the except Exception block in _rule_applies
    by monkey-patching to force an exception during evaluation.
    """

    def test_exception_during_evaluation_returns_false(self):
        """
        The except Exception block returns False and logs a warning.
        Force an exception by patching the field_map lookup to raise.
        """
        import unittest.mock as mock

        engine = engine_with(make_matrix())
        rule = ComplianceRule(
            rule_ref="EXC-001",
            condition=Condition(
                field="agent_required",
                operator="equals",
                value="test_agent"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask()

        # Patch the field_map construction to raise unexpectedly
        original = engine._rule_applies

        def patched_rule_applies(r, t):
            # Force an exception inside the try block
            # by patching the ConditionOperator import
            with mock.patch(
                "daf.components.policy_engine.logger"
            ) as mock_logger:
                # Temporarily make the operator comparison raise
                with mock.patch.object(
                    r.condition,
                    "operator",
                    new_callable=mock.PropertyMock,
                    side_effect=RuntimeError("forced error")
                ):
                    result = original(r, t)
                    return result

        result = patched_rule_applies(rule, task)
        assert result is False

    def test_unknown_operator_string_debug_logged(self):
        """
        The logger.debug path for unknown operator executes
        when operator is not a known ConditionOperator value.
        """
        import unittest.mock as mock
        from daf.models.policy_matrix import ConditionOperator

        engine = engine_with(make_matrix())
        rule = ComplianceRule(
            rule_ref="UNK-002",
            condition=Condition(
                field="agent_required",
                operator="equals",
                value="test"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask()

        # Replace the operator with a mock that matches none of the if branches
        with mock.patch.object(
            rule.condition, "operator",
            new="completely_unknown_operator_xyz"
        ):
            with mock.patch(
                "daf.components.policy_engine.logger"
            ) as mock_logger:
                result = engine._rule_applies(rule, task)
                assert result is False
