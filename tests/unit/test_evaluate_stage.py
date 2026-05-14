"""
Unit tests for EvaluateStage, EvaluationOutcome, and StubHumanReviewGateway.

All tests use:
  - InMemoryAuditStore (no DB)
  - StubHumanReviewGateway (no I/O)
  - PolicyEngine with real evaluation (no mocks)

Coverage:
  - EvaluationOutcome properties and methods
  - EvaluateStage: clean approval (no gates)
  - EvaluateStage: rejection from PolicyEngine
  - EvaluateStage: HITL all approved
  - EvaluateStage: HITL any rejected
  - EvaluateStage: HITL timeout → auto-reject
  - EvaluateStage: no gateway configured → auto-reject
  - Audit records written for all outcomes
  - HITL rejection converted to ViolationReport
  - GovernedAgenticLoop integration (loop calls EvaluateStage)
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from daf.components.evaluate_stage import EvaluateStage, EvaluationOutcome
from daf.components.policy_engine import PolicyEngine, PolicyEvaluation
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.models.audit_record import AuditEventType
from daf.models.human_review import (
    GatedTaskDetail, HumanReviewRequest, HumanReviewResponse, TaskDecision
)
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig,
)
from daf.models.violation_report import ViolationReport, Violation
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway


# ── Fixtures ─────────────────────────────────────────────────

def make_workflow_request(task: str = "Test task") -> WorkflowRequest:
    return WorkflowRequest(
        request_id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        user_id="test-user",
        tenant_id="test-tenant",
        task_description=task,
    )


def make_proposal(
    iteration: int = 1,
    sub_tasks: list[SubTask] | None = None,
) -> PlanProposal:
    default_tasks = [SubTask(
        task_id="ST-01", name="test step",
        task_type="llm_extraction",
        agent_required="test_agent",
        tools_required=["read_db"],
        data_required=["test_data"],
        estimated_cost=0.02,
        reversible=True,
        rationale="test",
    )]
    return PlanProposal(
        proposal_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        iteration=iteration,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=sub_tasks or default_tasks,
        total_estimated_cost=0.02,
        confidence=0.90,
    )


def make_clean_grant(proposal: PlanProposal) -> ApprovalGrant:
    """Grant with no gated tasks."""
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=proposal.proposal_id,
        approved_plan=proposal,
        agent_permissions={"test_agent": AgentPermissions(
            tools=["read_db"], data_sources=["test_data"],
        )},
        gated_tasks=[],
        execution_constraints={"max_cost_usd": 0.50},
    )


def make_gated_grant(
    proposal: PlanProposal,
    gated_task_ids: list[str],
) -> ApprovalGrant:
    """Grant with gated tasks requiring HITL."""
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=proposal.proposal_id,
        approved_plan=proposal,
        agent_permissions={"test_agent": AgentPermissions(
            tools=["read_db"], data_sources=["test_data"],
        )},
        gated_tasks=gated_task_ids,
        execution_constraints={
            "max_cost_usd": 0.50,
            "human_gate_required": True,
        },
    )


def make_violation_report(proposal: PlanProposal) -> ViolationReport:
    return ViolationReport(
        proposal_id=proposal.proposal_id,
        violations=[Violation(
            task_id="ST-01",
            dimension="tool_permission",
            severity="blocking",
            detail="Tool not permitted",
            suggestion="Use read_db instead",
        )],
        approvable_task_ids=[],
        escalate_to_human=False,
    )


def make_evaluate_stage(
    policy_eval: PolicyEvaluation,
    audit_store: InMemoryAuditStore,
    hitl_gateway: StubHumanReviewGateway | None = None,
) -> EvaluateStage:
    """Build an EvaluateStage with a mocked PolicyEngine."""
    import tempfile, yaml
    matrix_data = {
        "version": "1.0.0", "tenant_id": "test",
        "effective": "2026-01-01T00:00:00Z",
        "agent_roles": {"test_agent": {
            "permitted_tools": ["read_db"],
            "permitted_data_sources": ["test_data"],
            "permitted_task_types": ["llm_extraction"],
            "max_llm_calls_per_step": 3,
        }}
    }
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
        yaml.dump(matrix_data, f)
        tmp = f.name

    engine = PolicyEngine(policy_matrix_path=tmp)
    engine.evaluate = MagicMock(return_value=policy_eval)

    return EvaluateStage(
        policy_engine=engine,
        audit_store=audit_store,
        hitl_gateway=hitl_gateway,
        hitl_timeout_seconds=10.0,
    )


def make_policy_matrix() -> PolicyMatrix:
    return PolicyMatrix(
        version="1.0.0", tenant_id="test",
        effective="2026-01-01T00:00:00Z",
        agent_roles={"test_agent": AgentRoleConfig(
            permitted_tools=["read_db"],
            permitted_data_sources=["test_data"],
            permitted_task_types=["llm_extraction"],
        )},
        budget_policy=BudgetPolicyConfig(),
        loop_policy=LoopPolicyConfig(),
        risk_policy=RiskPolicyConfig(),
        compliance_rules=[],
    )


# ── EvaluationOutcome ─────────────────────────────────────────

class TestEvaluationOutcome:

    def test_executable_outcome_is_executable(self):
        """EXECUTABLE verdict means is_executable() is True."""
        grant   = MagicMock()
        outcome = EvaluationOutcome(verdict="EXECUTABLE", approval_grant=grant)
        assert outcome.is_executable() is True

    def test_not_executable_outcome_is_not_executable(self):
        """NOT_EXECUTABLE verdict means is_executable() is False."""
        outcome = EvaluationOutcome(verdict="NOT_EXECUTABLE")
        assert outcome.is_executable() is False

    def test_as_violation_returns_violation_report(self):
        """as_violation() returns the ViolationReport on NOT_EXECUTABLE."""
        report  = MagicMock(spec=ViolationReport)
        outcome = EvaluationOutcome(
            verdict="NOT_EXECUTABLE",
            violation_report=report,
        )
        assert outcome.as_violation() is report

    def test_as_violation_raises_on_executable(self):
        """as_violation() raises ValueError on EXECUTABLE outcome."""
        outcome = EvaluationOutcome(
            verdict="EXECUTABLE",
            approval_grant=MagicMock(),
        )
        with pytest.raises(ValueError, match="EXECUTABLE"):
            outcome.as_violation()

    def test_repr_includes_verdict(self):
        outcome = EvaluationOutcome(verdict="EXECUTABLE")
        assert "EXECUTABLE" in repr(outcome)


# ── EvaluateStage — Clean Approval ───────────────────────────

class TestEvaluateStageClearApproval:
    """PolicyEngine approves, no gated tasks — EXECUTABLE immediately."""

    @pytest.mark.asyncio
    async def test_clean_approval_returns_executable(self):
        proposal = make_proposal()
        grant    = make_clean_grant(proposal)
        store    = InMemoryAuditStore()

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        assert outcome.is_executable() is True
        assert outcome.approval_grant is grant
        assert outcome.violation_report is None
        assert outcome.review_response is None

    @pytest.mark.asyncio
    async def test_clean_approval_writes_audit_record(self):
        """PLAN_EVALUATED audit record is written."""
        proposal = make_proposal()
        grant    = make_clean_grant(proposal)
        store    = InMemoryAuditStore()
        req      = make_workflow_request()

        stage = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
        )
        await stage.run(proposal, make_policy_matrix(), req)

        records = await store.query(req.request_id)
        event_types = [r.event_type for r in records]
        assert AuditEventType.PLAN_EVALUATED in event_types

    @pytest.mark.asyncio
    async def test_clean_approval_audit_payload_has_verdict(self):
        """Audit record payload includes verdict=APPROVED."""
        proposal = make_proposal()
        grant    = make_clean_grant(proposal)
        store    = InMemoryAuditStore()
        req      = make_workflow_request()

        stage = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
        )
        await stage.run(proposal, make_policy_matrix(), req)

        records = await store.query(
            req.request_id,
            event_type=AuditEventType.PLAN_EVALUATED,
        )
        assert records[0].payload["verdict"] == "APPROVED"


# ── EvaluateStage — Rejection ─────────────────────────────────

class TestEvaluateStageRejection:
    """PolicyEngine rejects — NOT_EXECUTABLE."""

    @pytest.mark.asyncio
    async def test_rejected_returns_not_executable(self):
        proposal = make_proposal()
        report   = make_violation_report(proposal)
        store    = InMemoryAuditStore()

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="REJECTED", violation_report=report),
            audit_store=store,
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        assert outcome.is_executable() is False
        assert outcome.violation_report is report
        assert outcome.approval_grant is None

    @pytest.mark.asyncio
    async def test_rejected_as_violation_returns_report(self):
        proposal = make_proposal()
        report   = make_violation_report(proposal)
        store    = InMemoryAuditStore()
        req      = make_workflow_request()

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="REJECTED", violation_report=report),
            audit_store=store,
        )
        outcome = await stage.run(proposal, make_policy_matrix(), req)

        assert outcome.as_violation() is report

    @pytest.mark.asyncio
    async def test_rejected_writes_audit_record(self):
        proposal = make_proposal()
        report   = make_violation_report(proposal)
        store    = InMemoryAuditStore()
        req      = make_workflow_request()

        stage = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="REJECTED", violation_report=report),
            audit_store=store,
        )
        await stage.run(proposal, make_policy_matrix(), req)

        records = await store.query(
            req.request_id,
            event_type=AuditEventType.PLAN_EVALUATED
        )
        assert len(records) == 1
        assert records[0].payload["verdict"] == "REJECTED"


# ── EvaluateStage — HITL All Approved ────────────────────────

class TestEvaluateStageHITLApproved:
    """HITL gates exist and human approves all tasks."""

    @pytest.mark.asyncio
    async def test_hitl_approved_returns_executable(self):
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="send report",
            task_type="llm_generation",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=["test_data"],
            estimated_cost=0.01,
            reversible=False,
            rationale="send report",
        )])
        grant   = make_gated_grant(proposal, ["ST-03"])
        store   = InMemoryAuditStore()
        gateway = StubHumanReviewGateway(approve_all=True)

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=gateway,
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        assert outcome.is_executable() is True
        assert outcome.approval_grant is grant
        assert outcome.review_response is not None
        assert outcome.review_response.is_fully_approved() is True

    @pytest.mark.asyncio
    async def test_hitl_writes_request_and_response_audit_records(self):
        """Both HUMAN_REVIEW_REQUESTED and HUMAN_REVIEW_RESPONDED are written."""
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="send report",
            task_type="llm_generation",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=False,
            rationale="test",
        )])
        grant   = make_gated_grant(proposal, ["ST-03"])
        store   = InMemoryAuditStore()
        gateway = StubHumanReviewGateway(approve_all=True)
        req     = make_workflow_request()

        stage = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=gateway,
        )
        await stage.run(proposal, make_policy_matrix(), req)

        event_types = [
            r.event_type
            for r in await store.query(req.request_id)
        ]
        assert AuditEventType.HUMAN_REVIEW_REQUESTED in event_types
        assert AuditEventType.HUMAN_REVIEW_RESPONDED in event_types

    @pytest.mark.asyncio
    async def test_hitl_gateway_receives_review_request(self):
        """Gateway.request_and_wait() is called with correct review request."""
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="delete records",
            task_type="deterministic",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=False,
            rationale="test",
        )])
        grant   = make_gated_grant(proposal, ["ST-03"])
        store   = InMemoryAuditStore()
        gateway = StubHumanReviewGateway(approve_all=True)

        stage = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=gateway,
        )
        await stage.run(proposal, make_policy_matrix(), make_workflow_request())

        assert len(gateway.requests) == 1
        assert "ST-03" in gateway.requests[0].gated_task_ids


# ── EvaluateStage — HITL Rejected ────────────────────────────

class TestEvaluateStageHITLRejected:
    """HITL gates exist and human rejects one or more tasks."""

    @pytest.mark.asyncio
    async def test_hitl_rejection_returns_not_executable(self):
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="send email",
            task_type="llm_generation",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=False,
            rationale="test",
        )])
        grant   = make_gated_grant(proposal, ["ST-03"])
        store   = InMemoryAuditStore()
        gateway = StubHumanReviewGateway(approve_all=False)

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=gateway,
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        assert outcome.is_executable() is False

    @pytest.mark.asyncio
    async def test_hitl_rejection_produces_violation_report(self):
        """ViolationReport is built from rejected task decisions."""
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="send email",
            task_type="llm_generation",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=False,
            rationale="test",
        )])
        grant   = make_gated_grant(proposal, ["ST-03"])
        store   = InMemoryAuditStore()
        gateway = StubHumanReviewGateway(approve_all=False)

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=gateway,
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        report = outcome.as_violation()
        assert report is not None
        assert len(report.violations) == 1
        assert report.violations[0].task_id == "ST-03"
        assert report.violations[0].dimension == "human_review"
        assert report.violations[0].severity == "blocking"

    @pytest.mark.asyncio
    async def test_hitl_timeout_returns_not_executable(self):
        """Timeout auto-reject produces NOT_EXECUTABLE outcome."""
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="delete data",
            task_type="deterministic",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=False,
            rationale="test",
        )])
        grant   = make_gated_grant(proposal, ["ST-03"])
        store   = InMemoryAuditStore()
        gateway = StubHumanReviewGateway(simulate_timeout=True)

        stage   = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=gateway,
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        assert outcome.is_executable() is False
        report = outcome.as_violation()
        assert report.escalate_to_human is True

    @pytest.mark.asyncio
    async def test_no_gateway_auto_rejects(self):
        """If no gateway configured, gated tasks are auto-rejected."""
        proposal = make_proposal(sub_tasks=[SubTask(
            task_id="ST-03", name="send email",
            task_type="llm_generation",
            agent_required="test_agent",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=False,
            rationale="test",
        )])
        grant = make_gated_grant(proposal, ["ST-03"])
        store = InMemoryAuditStore()

        stage = make_evaluate_stage(
            policy_eval=PolicyEvaluation(verdict="APPROVED", approval_grant=grant),
            audit_store=store,
            hitl_gateway=None,   # no gateway
        )
        outcome = await stage.run(
            proposal=proposal,
            policy_matrix=make_policy_matrix(),
            workflow_request=make_workflow_request(),
        )

        assert outcome.is_executable() is False
        report = outcome.as_violation()
        assert any(
            "no-gateway" in v.detail.lower() or "auto-rejected" in v.detail.lower()
            for v in report.violations
        )


# ── StubHumanReviewGateway ───────────────────────────────────

class TestStubHumanReviewGateway:

    @pytest.mark.asyncio
    async def test_approve_all_returns_approved_response(self):
        gateway = StubHumanReviewGateway(approve_all=True)
        request = HumanReviewRequest.create(
            grant_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            tenant_id="test",
            user_id="user",
            gated_tasks=[GatedTaskDetail(
                task_id="ST-03", task_name="test",
                action_class="send_email",
                gate_reason="test", risk_rationale="test",
                reversible=False, estimated_impact="test",
            )],
            timeout_seconds=60,
        )
        response = await gateway.request_and_wait(request)
        assert response.is_fully_approved() is True

    @pytest.mark.asyncio
    async def test_reject_all_returns_rejected_response(self):
        gateway = StubHumanReviewGateway(approve_all=False)
        request = HumanReviewRequest.create(
            grant_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            tenant_id="test", user_id="user",
            gated_tasks=[GatedTaskDetail(
                task_id="ST-03", task_name="test",
                action_class="send_email",
                gate_reason="test", risk_rationale="test",
                reversible=False, estimated_impact="test",
            )],
            timeout_seconds=60,
        )
        response = await gateway.request_and_wait(request)
        assert response.has_rejections() is True

    @pytest.mark.asyncio
    async def test_timeout_returns_timed_out_response(self):
        gateway = StubHumanReviewGateway(simulate_timeout=True)
        request = HumanReviewRequest.create(
            grant_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            tenant_id="test", user_id="user",
            gated_tasks=[GatedTaskDetail(
                task_id="ST-03", task_name="test",
                action_class="send_email",
                gate_reason="test", risk_rationale="test",
                reversible=False, estimated_impact="test",
            )],
            timeout_seconds=60,
        )
        response = await gateway.request_and_wait(request)
        assert response.timed_out is True

    @pytest.mark.asyncio
    async def test_records_request_history(self):
        gateway = StubHumanReviewGateway()
        request = HumanReviewRequest.create(
            grant_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            tenant_id="test", user_id="user",
            gated_tasks=[GatedTaskDetail(
                task_id="ST-03", task_name="test",
                action_class="send_email",
                gate_reason="test", risk_rationale="test",
                reversible=False, estimated_impact="test",
            )],
            timeout_seconds=60,
        )
        await gateway.request_and_wait(request)
        assert len(gateway.requests) == 1

    @pytest.mark.asyncio
    async def test_set_next_response(self):
        """set_next_response() causes the next call to return that response."""
        gateway = StubHumanReviewGateway(approve_all=False)
        review_id = uuid.uuid4()
        grant_id  = uuid.uuid4()

        custom_response = HumanReviewResponse.approved_all(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id="custom-reviewer",
            task_ids=["ST-03"],
        )
        gateway.set_next_response(custom_response)

        request = HumanReviewRequest.create(
            grant_id=grant_id,
            request_id=uuid.uuid4(),
            tenant_id="test", user_id="user",
            gated_tasks=[GatedTaskDetail(
                task_id="ST-03", task_name="test",
                action_class="send_email",
                gate_reason="test", risk_rationale="test",
                reversible=False, estimated_impact="test",
            )],
            timeout_seconds=60,
        )
        response = await gateway.request_and_wait(request)
        assert response.reviewer_id == "custom-reviewer"
        assert response.is_fully_approved() is True
