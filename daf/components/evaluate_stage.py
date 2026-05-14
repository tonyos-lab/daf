"""
EvaluateStage — the complete evaluation coordinator.

Owns the full EVALUATE phase of the Governed Agentic Loop.
Calls PolicyEngine (deterministic policy check) and, if gates exist,
resolves HITL before returning a clean EvaluationOutcome.

The GovernedAgenticLoop calls EvaluateStage.run().
It never calls PolicyEngine or HumanReviewGateway directly.

WHAT EVALUATE STAGE OWNS:
  1. Policy Engine evaluation
  2. HITL resolution (if gated tasks exist)
  3. Writing audit records for both
  4. Converting HITL rejections to ViolationReports
     so the loop only handles one result type

THE THREE OUTCOMES:
  EXECUTABLE (clean):
    PolicyEngine: APPROVED, no gated tasks
    → return grant immediately

  EXECUTABLE (HITL resolved):
    PolicyEngine: APPROVED, has gated tasks
    Human reviewed: all approved
    → return grant + review response

  NOT_EXECUTABLE:
    PolicyEngine: REJECTED
    OR HITL has any rejection
    OR HITL timed out
    → return violation report
    → GovernedAgenticLoop re-plans with context
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from daf.components.policy_engine import PolicyEngine
from daf.models.approval_grant import ApprovalGrant
from daf.models.audit_record import AuditRecord, AuditEventType
from daf.models.human_review import (
    GatedTaskDetail,
    HumanReviewRequest,
    HumanReviewResponse,
)
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import PolicyMatrix
from daf.models.violation_report import ViolationReport, Violation
from daf.runtime.audit_store import AuditStore
from daf.runtime.human_review_gateway import BaseHumanReviewGateway

logger = logging.getLogger(__name__)


# ── EvaluationOutcome ─────────────────────────────────────────

class EvaluationOutcome:
    """
    The complete result of one evaluate phase.

    The GovernedAgenticLoop only sees this — not PolicyEvaluation
    or HumanReviewResponse directly.

    verdict:
      "EXECUTABLE"     — loop may proceed to ExecutionOrchestrator
      "NOT_EXECUTABLE" — loop must re-plan or escalate
    """

    def __init__(
        self,
        verdict:          str,
        approval_grant:   ApprovalGrant | None       = None,
        violation_report: ViolationReport | None     = None,
        review_response:  HumanReviewResponse | None = None,
    ) -> None:
        self.verdict          = verdict
        self.approval_grant   = approval_grant
        self.violation_report = violation_report
        self.review_response  = review_response

    def is_executable(self) -> bool:
        """True if the loop can proceed to execution."""
        return self.verdict == "EXECUTABLE"

    def as_violation(self) -> ViolationReport:
        """
        Return the ViolationReport for re-planning.

        Used by GovernedAgenticLoop when is_executable() is False.
        If the outcome is from a HITL rejection, builds a synthetic
        ViolationReport from the rejected task decisions.

        Raises ValueError if called on an EXECUTABLE outcome.
        """
        if self.is_executable():
            raise ValueError(
                "as_violation() called on EXECUTABLE outcome. "
                "Check is_executable() before calling this method."
            )
        if self.violation_report is not None:
            return self.violation_report

        raise ValueError(
            "NOT_EXECUTABLE outcome has no violation_report. "
            "This should not happen — check EvaluateStage logic."
        )

    def __repr__(self) -> str:
        return (
            f"EvaluationOutcome("
            f"verdict={self.verdict!r}, "
            f"has_grant={self.approval_grant is not None}, "
            f"has_violation={self.violation_report is not None})"
        )


# ── EvaluateStage ─────────────────────────────────────────────

class EvaluateStage:
    """
    The complete evaluation phase coordinator.

    Thin coordinator — owns evaluate phase logic but
    delegates to PolicyEngine and HumanReviewGateway.

    Used by GovernedAgenticLoop in Phase 2 onwards.
    Replaces the direct PolicyEngine call in the loop.
    """

    def __init__(
        self,
        policy_engine:        PolicyEngine,
        audit_store:          AuditStore,
        hitl_gateway:         BaseHumanReviewGateway | None = None,
        hitl_timeout_seconds: float = 3600.0,
    ) -> None:
        """
        Args:
            policy_engine:        PolicyEngine instance
            audit_store:          AuditStore for writing evaluation events
            hitl_gateway:         Gateway for HITL reviews. None = no HITL support
                                  (gated tasks auto-rejected if gateway not set)
            hitl_timeout_seconds: Seconds before auto-reject on HITL timeout
        """
        self._policy_engine        = policy_engine
        self._audit_store          = audit_store
        self._hitl_gateway         = hitl_gateway
        self._hitl_timeout_seconds = hitl_timeout_seconds

    async def run(
        self,
        proposal:         PlanProposal,
        policy_matrix:    PolicyMatrix,
        workflow_request: Any,        # WorkflowRequest — avoid circular import
    ) -> EvaluationOutcome:
        """
        Run the complete evaluation phase.

        Steps:
          1. PolicyEngine.evaluate() — deterministic
          2. Write PLAN_EVALUATED audit record
          3. If REJECTED → return NOT_EXECUTABLE
          4. If APPROVED + no gates → return EXECUTABLE
          5. If APPROVED + gates → HITL resolution
             a. Build HumanReviewRequest
             b. Write HUMAN_REVIEW_REQUESTED audit record
             c. Call gateway.request_and_wait()
             d. Write HUMAN_REVIEW_RESPONDED audit record
             e. If all approved → return EXECUTABLE
             f. If any rejected → build ViolationReport → NOT_EXECUTABLE

        Args:
            proposal:         The PlanProposal from PlanningOrchestrator
            policy_matrix:    The PolicyMatrix for evaluation
            workflow_request: The WorkflowRequest (for audit records)

        Returns:
            EvaluationOutcome — EXECUTABLE or NOT_EXECUTABLE
        """
        # Step 1: Policy Engine evaluation (deterministic, never raises)
        policy_eval = self._policy_engine.evaluate(
            proposal=proposal,
            matrix=policy_matrix,
        )

        # Step 2: Write evaluation audit record
        await self._audit_store.write(AuditRecord.make(
            request_id=workflow_request.request_id,
            tenant_id=workflow_request.tenant_id,
            user_id=workflow_request.user_id,
            event_type=AuditEventType.PLAN_EVALUATED,
            payload={
                "proposal_id": str(proposal.proposal_id),
                "iteration":   proposal.iteration,
                "verdict":     policy_eval.verdict,
                "violations":  (
                    len(policy_eval.violation_report.violations)
                    if policy_eval.violation_report else 0
                ),
                "gated_tasks": (
                    policy_eval.approval_grant.gated_tasks
                    if policy_eval.approval_grant else []
                ),
            },
        ))

        # Step 3: Policy rejected — return immediately
        if policy_eval.verdict == "REJECTED":
            logger.info(
                f"EvaluateStage: REJECTED by PolicyEngine "
                f"(iteration={proposal.iteration}, "
                f"violations={len(policy_eval.violation_report.violations)})"
            )
            return EvaluationOutcome(
                verdict="NOT_EXECUTABLE",
                violation_report=policy_eval.violation_report,
            )

        # Step 4: Approved with no gates — execute immediately
        grant = policy_eval.approval_grant
        if not grant.gated_tasks:
            logger.info(
                f"EvaluateStage: APPROVED (no gates, iteration={proposal.iteration})"
            )
            return EvaluationOutcome(
                verdict="EXECUTABLE",
                approval_grant=grant,
            )

        # Step 5: HITL resolution needed
        logger.info(
            f"EvaluateStage: APPROVED with {len(grant.gated_tasks)} gate(s) "
            f"— initiating HITL review"
        )
        return await self._resolve_hitl(
            grant=grant,
            proposal=proposal,
            workflow_request=workflow_request,
        )

    async def _resolve_hitl(
        self,
        grant:            ApprovalGrant,
        proposal:         PlanProposal,
        workflow_request: Any,
    ) -> EvaluationOutcome:
        """
        Resolve HITL gates.

        If no gateway is configured → auto-reject all gated tasks.
        """
        # Build task details for each gated task
        gated_task_details = self._build_gated_task_details(
            grant=grant,
            proposal=proposal,
        )

        # Build review request
        review_request = HumanReviewRequest.create(
            grant_id=grant.grant_id,
            request_id=workflow_request.request_id,
            tenant_id=workflow_request.tenant_id,
            user_id=workflow_request.user_id,
            gated_tasks=gated_task_details,
            timeout_seconds=self._hitl_timeout_seconds,
            workflow_task=workflow_request.task_description,
        )

        # Write request to audit store
        await self._audit_store.write(AuditRecord.make(
            request_id=workflow_request.request_id,
            tenant_id=workflow_request.tenant_id,
            user_id=workflow_request.user_id,
            event_type=AuditEventType.HUMAN_REVIEW_REQUESTED,
            payload={
                "review_id":   str(review_request.review_id),
                "grant_id":    str(grant.grant_id),
                "gated_tasks": grant.gated_tasks,
                "expires_at":  review_request.expires_at.isoformat(),
            },
        ))

        # If no gateway configured — auto-reject (safe default)
        if self._hitl_gateway is None:
            logger.warning(
                "EvaluateStage: no HITL gateway configured — "
                "auto-rejecting all gated tasks"
            )
            review_response = HumanReviewResponse.rejected_all(
                review_id=review_request.review_id,
                grant_id=grant.grant_id,
                reviewer_id="system:no-gateway",
                task_ids=review_request.gated_task_ids,
                reason="No HITL gateway configured — auto-rejected",
            )
        else:
            # Send to gateway and wait for human response
            review_response = await self._hitl_gateway.request_and_wait(
                request=review_request,
            )

        # Write response to audit store
        await self._audit_store.write(AuditRecord.make(
            request_id=workflow_request.request_id,
            tenant_id=workflow_request.tenant_id,
            user_id=workflow_request.user_id,
            event_type=AuditEventType.HUMAN_REVIEW_RESPONDED,
            payload={
                "review_id":    str(review_response.review_id),
                "reviewer_id":  review_response.reviewer_id,
                "timed_out":    review_response.timed_out,
                "approved":     review_response.approved_task_ids(),
                "rejected":     review_response.rejected_task_ids(),
                "fully_approved": review_response.is_fully_approved(),
            },
        ))

        # All approved → EXECUTABLE
        if review_response.is_fully_approved():
            logger.info(
                f"EvaluateStage: HITL fully approved by "
                f"{review_response.reviewer_id}"
            )
            return EvaluationOutcome(
                verdict="EXECUTABLE",
                approval_grant=grant,
                review_response=review_response,
            )

        # Any rejection → build ViolationReport → NOT_EXECUTABLE
        logger.info(
            f"EvaluateStage: HITL rejected "
            f"{len(review_response.rejected_task_ids())} task(s)"
        )
        violation_report = self._build_hitl_violation_report(
            proposal=proposal,
            review_response=review_response,
        )
        return EvaluationOutcome(
            verdict="NOT_EXECUTABLE",
            violation_report=violation_report,
            review_response=review_response,
        )

    def _build_gated_task_details(
        self,
        grant:    ApprovalGrant,
        proposal: PlanProposal,
    ) -> list[GatedTaskDetail]:
        """Build GatedTaskDetail list from gated_tasks in the ApprovalGrant."""
        task_map: dict[str, SubTask] = {
            t.task_id: t for t in proposal.sub_tasks
        }
        details = []
        for task_id in grant.gated_tasks:
            task = task_map.get(task_id)
            if task is None:
                continue
            details.append(GatedTaskDetail(
                task_id=task.task_id,
                task_name=task.name or task.task_id,
                action_class=task.task_type,
                gate_reason=self._gate_reason(task, grant),
                risk_rationale=task.rationale or "Policy gate triggered",
                reversible=task.reversible,
                estimated_impact=(
                    f"Execute {task.task_type} using "
                    f"{', '.join(task.tools_required) or 'no tools'}"
                ),
                estimated_cost=task.estimated_cost,
            ))
        return details

    def _gate_reason(self, task: SubTask, grant: ApprovalGrant) -> str:
        """Determine the reason this task was gated."""
        if not task.reversible:
            return "Irreversible action requires human authorisation"
        if task.task_id in grant.gated_tasks:
            return "Task matches a compliance rule requiring human review"
        return "Policy gate triggered"

    def _build_hitl_violation_report(
        self,
        proposal:        PlanProposal,
        review_response: HumanReviewResponse,
    ) -> ViolationReport:
        """
        Convert HITL rejections into a ViolationReport.

        The GovernedAgenticLoop only handles ViolationReports —
        this ensures it has one consistent result type to pass
        back to the PlanningOrchestrator for re-planning.
        """
        violations = []
        for task_id in review_response.rejected_task_ids():
            decision = review_response.decision_for(task_id)
            reason   = decision.reason if decision else "Rejected by reviewer"

            violations.append(Violation(
                task_id=task_id,
                dimension="human_review",
                severity="blocking",
                detail=(
                    f"Human reviewer rejected task {task_id}: {reason}"
                    if reason
                    else f"Human reviewer rejected task {task_id}"
                ),
                rule_ref="HITL-REJECTION",
                suggestion=(
                    "Revise this sub-task to address the reviewer's concern, "
                    "or remove it from the plan if not strictly necessary"
                ),
            ))

        return ViolationReport(
            proposal_id=proposal.proposal_id,
            violations=violations,
            approvable_task_ids=review_response.approved_task_ids(),
            escalate_to_human=review_response.timed_out,
            escalation_reason=(
                "Review request timed out — no compliant plan reached human."
                if review_response.timed_out else None
            ),
        )
