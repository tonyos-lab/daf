"""
Unit tests for the Policy Engine.

The Policy Engine must be tested exhaustively.
Every dimension must have tests for both pass and fail cases.
"""
import uuid
import pytest
from daf.components.policy_engine import PolicyEngine, PolicyEvaluation
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig
)


def make_matrix(**overrides) -> PolicyMatrix:
    """Build a test PolicyMatrix with safe defaults."""
    defaults = dict(
        version="1.0.0",
        tenant_id="test",
        effective="2026-01-01T00:00:00Z",
        agent_roles={
            "test_agent": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["test_data"],
                permitted_task_types=["deterministic", "llm_extraction"],
                max_llm_calls_per_step=3,
            )
        },
        budget_policy=BudgetPolicyConfig(
            max_cost_per_step_usd=0.10,
            max_cost_per_workflow_usd=0.50,
        ),
        loop_policy=LoopPolicyConfig(max_replan_attempts=3),
        risk_policy=RiskPolicyConfig(irreversible_min_confidence=0.90),
    )
    defaults.update(overrides)
    return PolicyMatrix(**defaults)


def make_proposal(**overrides) -> PlanProposal:
    """Build a test PlanProposal with safe defaults."""
    defaults = dict(
        proposal_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        iteration=1,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=[
            SubTask(
                task_id="ST-01",
                task_type="llm_extraction",
                agent_required="test_agent",
                tools_required=["read_db"],
                data_required=["test_data"],
                estimated_cost=0.05,
                reversible=True,
                rationale="test step",
            )
        ],
        total_estimated_cost=0.05,
        confidence=0.95,
    )
    defaults.update(overrides)
    return PlanProposal(**defaults)


class TestPolicyEngineApproval:
    def test_compliant_proposal_approved(self, tmp_path):
        """A fully compliant proposal should be approved."""
        # Write a minimal policy matrix YAML
        import yaml
        matrix_data = {
            "version": "1.0.0",
            "tenant_id": "test",
            "effective": "2026-01-01T00:00:00Z",
            "agent_roles": {
                "test_agent": {
                    "permitted_tools": ["read_db"],
                    "permitted_data_sources": ["test_data"],
                    "permitted_task_types": ["deterministic", "llm_extraction"],
                    "max_llm_calls_per_step": 3,
                }
            }
        }
        matrix_file = tmp_path / "test.yaml"
        matrix_file.write_text(yaml.dump(matrix_data))

        engine = PolicyEngine(policy_matrix_path=str(matrix_file))
        matrix = engine.load_matrix("test")
        proposal = make_proposal()
        result = engine.evaluate(proposal, matrix)

        assert result.verdict == "APPROVED"
        assert result.approval_grant is not None
        assert result.violation_report is None


class TestPolicyEngineViolations:
    def test_tool_permission_violation(self):
        """Agent requesting unpermitted tool should be rejected."""
        matrix = make_matrix()
        proposal = make_proposal()
        # Override sub-task to request a tool not in permitted_tools
        proposal.sub_tasks[0].tools_required = ["write_db"]  # not permitted

        engine = PolicyEngine.__new__(PolicyEngine)
        violations = engine._evaluate_task(
            proposal.sub_tasks[0], proposal, matrix
        )

        assert any(v.dimension == "tool_permission" for v in violations)
        assert any("write_db" in v.detail for v in violations)

    def test_violation_includes_suggestion(self):
        """Every blocking violation must include a remediation suggestion."""
        matrix = make_matrix()
        proposal = make_proposal()
        proposal.sub_tasks[0].tools_required = ["forbidden_tool"]

        engine = PolicyEngine.__new__(PolicyEngine)
        violations = engine._evaluate_task(
            proposal.sub_tasks[0], proposal, matrix
        )

        for v in violations:
            assert v.suggestion, f"Violation {v.dimension} missing suggestion"

    def test_data_access_violation(self):
        """Agent requesting unpermitted data source should be rejected."""
        matrix = make_matrix()
        proposal = make_proposal()
        proposal.sub_tasks[0].data_required = ["customer_pii"]  # not permitted

        engine = PolicyEngine.__new__(PolicyEngine)
        violations = engine._evaluate_task(
            proposal.sub_tasks[0], proposal, matrix
        )

        assert any(v.dimension == "data_access" for v in violations)

    def test_budget_violation(self):
        """Sub-task exceeding per-step budget should be rejected."""
        matrix = make_matrix()
        proposal = make_proposal()
        proposal.sub_tasks[0].estimated_cost = 99.99  # way over limit

        engine = PolicyEngine.__new__(PolicyEngine)
        violations = engine._evaluate_task(
            proposal.sub_tasks[0], proposal, matrix
        )

        assert any(v.dimension == "budget" for v in violations)

    def test_unknown_agent_role_rejected(self):
        """Sub-task with unknown agent role should be rejected."""
        matrix = make_matrix()
        proposal = make_proposal()
        proposal.sub_tasks[0].agent_required = "nonexistent_role"

        engine = PolicyEngine.__new__(PolicyEngine)
        violations = engine._evaluate_task(
            proposal.sub_tasks[0], proposal, matrix
        )

        assert any(v.dimension == "agent_authorization" for v in violations)

    def test_escalation_triggered_at_max_iterations(self):
        """Loop should escalate when max_replan_attempts is reached."""
        matrix = make_matrix()
        proposal = make_proposal()
        proposal.iteration = 3  # at the limit
        proposal.sub_tasks[0].tools_required = ["forbidden"]

        engine = PolicyEngine.__new__(PolicyEngine)
        # Force a violation by using an unpermitted tool
        matrix_for_eval = make_matrix()
        # Direct evaluate call
        import yaml, tempfile, os
        # Write matrix to temp file
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode='w') as f:
            import yaml
            yaml.dump({
                "version": "1.0.0", "tenant_id": "test",
                "effective": "2026-01-01T00:00:00Z",
                "agent_roles": {"test_agent": {
                    "permitted_tools": ["read_db"],
                    "permitted_data_sources": ["test_data"],
                    "permitted_task_types": ["llm_extraction"],
                    "max_llm_calls_per_step": 3
                }}
            }, f)
            tmp = f.name
        try:
            real_engine = PolicyEngine(policy_matrix_path=tmp)
            matrix = real_engine.load_matrix("test")
            result = real_engine.evaluate(proposal, matrix)
            assert result.verdict == "REJECTED"
            assert result.violation_report.escalate_to_human is True
        finally:
            os.unlink(tmp)
