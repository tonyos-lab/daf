"""
Unit tests for PolicyEngine — compliance rule evaluation.

These tests cover:
  - Condition model validation
  - _rule_applies() for all three operators
  - _collect_gated_tasks() for all three gate conditions
  - Full evaluate() with compliance blocking, warning, and gating
  - 100% coverage on compliance-related code paths
"""
from __future__ import annotations

import uuid
import tempfile
import os
import yaml
import pytest

from daf.components.policy_engine import PolicyEngine, PolicyEvaluation
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig, ComplianceRule,
    ComplianceAction, Condition, ConditionOperator,
    OrchestratorRoutingConfig,
)
from daf.models.approval_grant import ApprovalGrant


# ── Fixtures ─────────────────────────────────────────────────

def make_subtask(**overrides) -> SubTask:
    """Build a SubTask with safe test defaults."""
    defaults = dict(
        task_id="ST-01",
        name="test step",
        task_type="llm_extraction",
        agent_required="test_agent",
        tools_required=["read_db"],
        data_required=["test_data"],
        depends_on=[],
        estimated_cost=0.05,
        reversible=True,
        rationale="test rationale",
    )
    defaults.update(overrides)
    return SubTask(**defaults)


def make_matrix(**overrides) -> PolicyMatrix:
    """Build a PolicyMatrix with safe test defaults."""
    defaults = dict(
        version="1.0.0",
        tenant_id="test",
        effective="2026-01-01T00:00:00Z",
        agent_roles={
            "test_agent": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["test_data"],
                permitted_task_types=["llm_extraction", "deterministic"],
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
            always_gate_action_classes=[],
            auto_approve_action_classes=[],
        ),
        compliance_rules=[],
    )
    defaults.update(overrides)
    return PolicyMatrix(**defaults)


def make_proposal(**overrides) -> PlanProposal:
    """Build a PlanProposal with safe test defaults."""
    defaults = dict(
        request_id=uuid.uuid4(),
        iteration=1,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=[make_subtask()],
        total_estimated_cost=0.05,
        confidence=0.95,
        requires_human_gate=False,
    )
    defaults.update(overrides)
    return PlanProposal(**defaults)


def make_engine(matrix: PolicyMatrix | None = None) -> PolicyEngine:
    """Build a PolicyEngine with an optional pre-loaded matrix."""
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._policy_matrix_path = None
    engine._cached_matrix = matrix or make_matrix()
    return engine


# ── Condition Model Validation ───────────────────────────────

class TestConditionModelValidation:
    """Condition model must enforce value requirements per operator."""

    def test_contains_requires_value(self):
        """CONTAINS operator must have 'value' set."""
        with pytest.raises(ValueError, match="requires 'value'"):
            Condition(field="data_required", operator="contains")

    def test_equals_requires_value(self):
        """EQUALS operator must have 'value' set."""
        with pytest.raises(ValueError, match="requires 'value'"):
            Condition(field="agent_required", operator="equals")

    def test_in_list_requires_values(self):
        """IN_LIST operator must have non-empty 'values' set."""
        with pytest.raises(ValueError, match="requires 'values'"):
            Condition(field="task_type", operator="in_list")

    def test_in_list_requires_nonempty_values(self):
        """IN_LIST operator rejects empty values list."""
        with pytest.raises(ValueError, match="requires 'values'"):
            Condition(field="task_type", operator="in_list", values=[])

    def test_contains_valid(self):
        """Valid CONTAINS condition constructs without error."""
        c = Condition(field="data_required", operator="contains", value="pii")
        assert c.operator == ConditionOperator.CONTAINS
        assert c.value == "pii"

    def test_equals_valid(self):
        """Valid EQUALS condition constructs without error."""
        c = Condition(field="agent_required", operator="equals", value="finance_agent")
        assert c.operator == ConditionOperator.EQUALS

    def test_in_list_valid(self):
        """Valid IN_LIST condition constructs without error."""
        c = Condition(field="task_type", operator="in_list", values=["a", "b"])
        assert c.operator == ConditionOperator.IN_LIST
        assert c.values == ["a", "b"]


# ── _rule_applies() — CONTAINS operator ─────────────────────

class TestRuleAppliesContains:
    """Tests for _rule_applies() with CONTAINS operator."""

    def test_contains_matches_when_value_in_list(self):
        """Rule applies when field list contains the value."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-001",
            condition=Condition(
                field="data_required",
                operator="contains",
                value="pii_data"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(data_required=["test_data", "pii_data"])
        assert engine._rule_applies(rule, task) is True

    def test_contains_no_match_when_value_not_in_list(self):
        """Rule does not apply when field list does not contain value."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-001",
            condition=Condition(
                field="data_required",
                operator="contains",
                value="pii_data"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(data_required=["test_data", "public_data"])
        assert engine._rule_applies(rule, task) is False

    def test_contains_no_match_empty_list(self):
        """Rule does not apply when field list is empty."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-001",
            condition=Condition(
                field="data_required",
                operator="contains",
                value="pii_data"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(data_required=[])
        assert engine._rule_applies(rule, task) is False

    def test_contains_on_tools_required(self):
        """CONTAINS works on tools_required field."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-002",
            condition=Condition(
                field="tools_required",
                operator="contains",
                value="delete_db"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(tools_required=["read_db", "delete_db"])
        assert engine._rule_applies(rule, task) is True

    def test_contains_on_str_field_returns_false(self):
        """CONTAINS on a string field (not a list) returns False."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-003",
            condition=Condition(
                field="agent_required",   # str, not list
                operator="contains",
                value="finance"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(agent_required="finance_agent")
        # agent_required is a str, not a list — contains cannot apply
        assert engine._rule_applies(rule, task) is False


# ── _rule_applies() — EQUALS operator ───────────────────────

class TestRuleAppliesEquals:
    """Tests for _rule_applies() with EQUALS operator."""

    def test_equals_matches_exact_string(self):
        """Rule applies when field exactly equals value."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-004",
            condition=Condition(
                field="agent_required",
                operator="equals",
                value="finance_agent"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(agent_required="finance_agent")
        assert engine._rule_applies(rule, task) is True

    def test_equals_no_match_different_string(self):
        """Rule does not apply when field differs from value."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-004",
            condition=Condition(
                field="agent_required",
                operator="equals",
                value="finance_agent"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(agent_required="document_reader")
        assert engine._rule_applies(rule, task) is False

    def test_equals_case_sensitive(self):
        """EQUALS comparison is case-sensitive."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-005",
            condition=Condition(
                field="task_type",
                operator="equals",
                value="llm_extraction"
            ),
            action=ComplianceAction.WARN,
        )
        task_match    = make_subtask(task_type="llm_extraction")
        task_no_match = make_subtask(task_type="LLM_EXTRACTION")
        assert engine._rule_applies(rule, task_match)    is True
        assert engine._rule_applies(rule, task_no_match) is False

    def test_equals_on_list_field_returns_false(self):
        """EQUALS on a list field returns False."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-006",
            condition=Condition(
                field="data_required",  # list, not str
                operator="equals",
                value="pii_data"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(data_required=["pii_data"])
        assert engine._rule_applies(rule, task) is False


# ── _rule_applies() — IN_LIST operator ──────────────────────

class TestRuleAppliesInList:
    """Tests for _rule_applies() with IN_LIST operator."""

    def test_in_list_matches_when_field_in_values(self):
        """Rule applies when field value is in the condition values list."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-007",
            condition=Condition(
                field="task_type",
                operator="in_list",
                values=["llm_generation", "deterministic"]
            ),
            action=ComplianceAction.REQUIRE_HUMAN_GATE,
        )
        task = make_subtask(task_type="llm_generation")
        assert engine._rule_applies(rule, task) is True

    def test_in_list_no_match_when_field_not_in_values(self):
        """Rule does not apply when field value is not in the values list."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-007",
            condition=Condition(
                field="task_type",
                operator="in_list",
                values=["llm_generation", "deterministic"]
            ),
            action=ComplianceAction.REQUIRE_HUMAN_GATE,
        )
        task = make_subtask(task_type="llm_extraction")
        assert engine._rule_applies(rule, task) is False

    def test_in_list_single_value(self):
        """IN_LIST works with a single-element values list."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-008",
            condition=Condition(
                field="agent_required",
                operator="in_list",
                values=["admin_agent"]
            ),
            action=ComplianceAction.BLOCK,
        )
        task_match    = make_subtask(agent_required="admin_agent")
        task_no_match = make_subtask(agent_required="document_reader")
        assert engine._rule_applies(rule, task_match)    is True
        assert engine._rule_applies(rule, task_no_match) is False

    def test_in_list_on_list_field_returns_false(self):
        """IN_LIST on a list field (not a string) returns False."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-009",
            condition=Condition(
                field="data_required",  # list, not str
                operator="in_list",
                values=["pii_data"]
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(data_required=["pii_data"])
        assert engine._rule_applies(rule, task) is False


# ── _rule_applies() — edge cases ────────────────────────────

class TestRuleAppliesEdgeCases:
    """Edge cases for _rule_applies()."""

    def test_unknown_field_returns_false(self):
        """Unknown field name returns False conservatively."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-010",
            condition=Condition(
                field="nonexistent_field",
                operator="equals",
                value="something"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask()
        assert engine._rule_applies(rule, task) is False

    def test_rule_applies_does_not_raise_on_edge_input(self):
        """_rule_applies() never raises — always returns bool."""
        engine = make_engine()
        rule = ComplianceRule(
            rule_ref="TEST-011",
            condition=Condition(
                field="estimated_cost",   # float field
                operator="equals",
                value="0.05"
            ),
            action=ComplianceAction.BLOCK,
        )
        task = make_subtask(estimated_cost=0.05)
        # float field with equals operator — type mismatch returns False
        result = engine._rule_applies(rule, task)
        assert isinstance(result, bool)


# ── _collect_gated_tasks() ───────────────────────────────────

class TestCollectGatedTasks:
    """Tests for _collect_gated_tasks()."""

    def test_no_gates_when_no_rules_and_no_risk(self):
        """No gates when no compliance rules and no risk triggers."""
        engine = make_engine()
        matrix = make_matrix()
        proposal = make_proposal()
        gated = engine._collect_gated_tasks(
            proposal, matrix, [t.task_id for t in proposal.sub_tasks]
        )
        assert gated == []

    def test_gate_from_compliance_require_human_gate(self):
        """Task is gated when compliance rule action=require_human_gate matches."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="GATE-001",
                condition=Condition(
                    field="data_required",
                    operator="contains",
                    value="sensitive_data"
                ),
                action=ComplianceAction.REQUIRE_HUMAN_GATE,
                remediation_hint="Requires human review",
            )
        ])
        engine = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(task_id="ST-01", data_required=["sensitive_data"])
        ])
        gated = engine._collect_gated_tasks(
            proposal, matrix, ["ST-01"]
        )
        assert "ST-01" in gated

    def test_gate_from_always_gate_action_class(self):
        """Task is gated when task_type is in always_gate_action_classes."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(
                irreversible_min_confidence=0.90,
                always_gate_action_classes=["llm_generation"],
            )
        )
        engine = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(task_id="ST-01", task_type="llm_generation")
        ])
        gated = engine._collect_gated_tasks(
            proposal, matrix, ["ST-01"]
        )
        assert "ST-01" in gated

    def test_gate_from_irreversible_low_confidence(self):
        """Task is gated when irreversible and confidence below threshold."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(
                irreversible_min_confidence=0.90,
            )
        )
        engine = make_engine(matrix)
        proposal = make_proposal(
            confidence=0.75,  # below 0.90
            sub_tasks=[
                make_subtask(task_id="ST-01", reversible=False)
            ]
        )
        gated = engine._collect_gated_tasks(
            proposal, matrix, ["ST-01"]
        )
        assert "ST-01" in gated

    def test_no_gate_from_irreversible_high_confidence(self):
        """Irreversible task is NOT gated when confidence is above threshold."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(
                irreversible_min_confidence=0.90,
            )
        )
        engine = make_engine(matrix)
        proposal = make_proposal(
            confidence=0.95,  # above 0.90
            sub_tasks=[
                make_subtask(task_id="ST-01", reversible=False)
            ]
        )
        gated = engine._collect_gated_tasks(
            proposal, matrix, ["ST-01"]
        )
        assert "ST-01" not in gated

    def test_non_approvable_tasks_never_gated(self):
        """Tasks not in approvable_task_ids are never added to gated."""
        matrix = make_matrix(
            risk_policy=RiskPolicyConfig(
                always_gate_action_classes=["llm_generation"]
            )
        )
        engine = make_engine(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(task_id="ST-01", task_type="llm_generation")
        ])
        # ST-01 has a blocking violation — not in approvable set
        gated = engine._collect_gated_tasks(
            proposal, matrix, []  # empty approvable set
        )
        assert gated == []

    def test_task_gated_only_once_even_if_multiple_conditions(self):
        """Task appears in gated_tasks only once even if multiple conditions trigger."""
        matrix = make_matrix(
            compliance_rules=[
                ComplianceRule(
                    rule_ref="GATE-001",
                    condition=Condition(
                        field="data_required",
                        operator="contains",
                        value="sensitive_data"
                    ),
                    action=ComplianceAction.REQUIRE_HUMAN_GATE,
                )
            ],
            risk_policy=RiskPolicyConfig(
                always_gate_action_classes=["llm_extraction"],
                irreversible_min_confidence=0.90,
            )
        )
        engine = make_engine(matrix)
        proposal = make_proposal(
            confidence=0.75,
            sub_tasks=[
                make_subtask(
                    task_id="ST-01",
                    task_type="llm_extraction",      # triggers always_gate
                    data_required=["sensitive_data"], # triggers compliance gate
                    reversible=False                  # triggers irreversible gate
                )
            ]
        )
        gated = engine._collect_gated_tasks(
            proposal, matrix, ["ST-01"]
        )
        # Should appear exactly once
        assert gated.count("ST-01") == 1
        assert len(gated) == 1


# ── Full evaluate() with compliance ─────────────────────────

class TestFullEvaluateCompliance:
    """
    Integration tests for evaluate() covering compliance-related paths.
    """

    def _engine_from_matrix(self, matrix: PolicyMatrix) -> PolicyEngine:
        """Create a PolicyEngine with the given matrix cached."""
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", delete=False, mode="w"
        ) as f:
            data = matrix.model_dump()
            # Convert enums to values for YAML serialization
            yaml.dump(data, f, default_flow_style=False)
            tmp = f.name
        engine = PolicyEngine(policy_matrix_path=tmp)
        engine._cached_matrix = matrix
        return engine

    def test_evaluate_compliance_block_returns_rejected(self):
        """evaluate() returns REJECTED when compliance block rule matches."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="BLOCK-001",
                condition=Condition(
                    field="data_required",
                    operator="contains",
                    value="forbidden_data"
                ),
                action=ComplianceAction.BLOCK,
                remediation_hint="Do not access forbidden_data",
            )
        ])
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(data_required=["forbidden_data"])
        ])
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        violations = result.violation_report.violations
        assert any(v.dimension == "compliance" for v in violations)
        assert any(v.rule_ref == "BLOCK-001" for v in violations)
        assert any("forbidden_data" in v.detail or "BLOCK-001" in v.detail
                   for v in violations)

    def test_evaluate_compliance_block_includes_remediation(self):
        """Compliance block violation includes the remediation hint."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="BLOCK-002",
                condition=Condition(
                    field="agent_required",
                    operator="equals",
                    value="forbidden_agent"
                ),
                action=ComplianceAction.BLOCK,
                remediation_hint="Use approved_agent instead",
            )
        ])
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(agent_required="forbidden_agent")
        ])
        # Override agent_roles to allow the agent to pass permission check
        matrix.agent_roles["forbidden_agent"] = AgentRoleConfig(
            permitted_tools=["read_db"],
            permitted_data_sources=["test_data"],
            permitted_task_types=["llm_extraction"],
            max_llm_calls_per_step=3,
        )
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        v = next(
            v for v in result.violation_report.violations
            if v.dimension == "compliance"
        )
        assert "Use approved_agent instead" in v.suggestion

    def test_evaluate_compliance_warn_does_not_block(self):
        """Compliance warn rule does not cause REJECTED verdict."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="WARN-001",
                condition=Condition(
                    field="task_type",
                    operator="equals",
                    value="llm_extraction"
                ),
                action=ComplianceAction.WARN,
            )
        ])
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(task_type="llm_extraction")
        ])
        result = engine.evaluate(proposal, matrix)
        # WARN does not block — should be APPROVED
        assert result.verdict == "APPROVED"

    def test_evaluate_compliance_gate_produces_gated_tasks(self):
        """require_human_gate produces non-empty gated_tasks in ApprovalGrant."""
        matrix = make_matrix(
            agent_roles={
                "test_agent": AgentRoleConfig(
                    permitted_tools=["read_db"],
                    # sensitive_data is permitted — data access check passes
                    permitted_data_sources=["test_data", "sensitive_data"],
                    permitted_task_types=["llm_extraction"],
                    max_llm_calls_per_step=3,
                )
            },
            compliance_rules=[
                ComplianceRule(
                    rule_ref="GATE-001",
                    condition=Condition(
                        field="data_required",
                        operator="contains",
                        value="sensitive_data"
                    ),
                    action=ComplianceAction.REQUIRE_HUMAN_GATE,
                )
            ]
        )
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(task_id="ST-01", data_required=["sensitive_data"])
        ])
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "APPROVED"
        assert "ST-01" in result.approval_grant.gated_tasks

    def test_evaluate_clean_proposal_has_empty_gated_tasks(self):
        """Clean proposal with no gate conditions produces empty gated_tasks."""
        matrix = make_matrix()
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal()
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "APPROVED"
        assert result.approval_grant.gated_tasks == []

    def test_evaluate_multiple_rules_all_evaluated(self):
        """All compliance rules are evaluated — first match does not short-circuit."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="RULE-A",
                condition=Condition(
                    field="data_required",
                    operator="contains",
                    value="forbidden_a"
                ),
                action=ComplianceAction.BLOCK,
            ),
            ComplianceRule(
                rule_ref="RULE-B",
                condition=Condition(
                    field="data_required",
                    operator="contains",
                    value="forbidden_b"
                ),
                action=ComplianceAction.BLOCK,
            ),
        ])
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal(sub_tasks=[
            make_subtask(data_required=["forbidden_a", "forbidden_b"])
        ])
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "REJECTED"
        rule_refs = {v.rule_ref for v in result.violation_report.violations
                     if v.dimension == "compliance"}
        assert "RULE-A" in rule_refs
        assert "RULE-B" in rule_refs

    def test_evaluate_non_matching_rule_does_not_affect_result(self):
        """A rule that does not match has no effect on the outcome."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="NO-MATCH",
                condition=Condition(
                    field="data_required",
                    operator="contains",
                    value="this_does_not_exist"
                ),
                action=ComplianceAction.BLOCK,
            )
        ])
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal()  # does not have "this_does_not_exist"
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "APPROVED"

    def test_evaluate_approval_grant_human_gate_required_flag(self):
        """ApprovalGrant.execution_constraints includes human_gate_required=True."""
        matrix = make_matrix(compliance_rules=[
            ComplianceRule(
                rule_ref="GATE-002",
                condition=Condition(
                    field="agent_required",
                    operator="equals",
                    value="test_agent"
                ),
                action=ComplianceAction.REQUIRE_HUMAN_GATE,
            )
        ])
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal()
        result = engine.evaluate(proposal, matrix)
        assert result.verdict == "APPROVED"
        assert result.approval_grant.execution_constraints[
            "human_gate_required"
        ] is True

    def test_evaluate_clean_approval_human_gate_required_false(self):
        """ApprovalGrant.execution_constraints has human_gate_required=False."""
        matrix = make_matrix()
        engine = self._engine_from_matrix(matrix)
        proposal = make_proposal()
        result = engine.evaluate(proposal, matrix)
        assert result.approval_grant.execution_constraints[
            "human_gate_required"
        ] is False
