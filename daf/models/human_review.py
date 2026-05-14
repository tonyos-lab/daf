"""
HumanReview models — data contracts for the HITL stage.

When the Policy Engine identifies tasks requiring human approval,
the EvaluateStage builds a HumanReviewRequest containing all
gated tasks, sends it to the HumanReviewGateway, and waits for
a HumanReviewResponse with a per-task decision.

DESIGN DECISIONS:
  - One request per workflow evaluation (not one per task)
  - Human reviews ALL gated tasks at once — single interaction point
  - Per-task decision in the response
  - Any rejection → EvaluateStage returns violation → re-plan
  - Timeout → auto-reject (safest default, configured in PolicyMatrix)
  - Both request and response are written to AuditStore

FLOW:
  PolicyEngine.evaluate()
    → ApprovalGrant with gated_tasks=["ST-03", "ST-05"]
    ↓
  EvaluateStage._resolve_hitl()
    → builds HumanReviewRequest (one request, all gated tasks)
    → writes request to AuditStore
    → calls HumanReviewGateway.request_and_wait()
    → receives HumanReviewResponse
    → writes response to AuditStore
    → if response.is_fully_approved() → return grant
    → else → build ViolationReport from rejections → re-plan
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── GatedTaskDetail ──────────────────────────────────────────

class GatedTaskDetail(BaseModel):
    """
    Details of one gated sub-task.

    Contains enough context for a human reviewer to make
    an informed approval/rejection decision without needing
    to read the full plan.

    Fields:
        task_id:          The sub-task identifier (e.g. "ST-03")
        task_name:        Human-readable name of the task
        action_class:     Type of action (e.g. "send_email", "delete_record")
        gate_reason:      Why this task requires human review
        risk_rationale:   What risk assessment triggered the gate
        reversible:       Whether this action can be undone
        estimated_impact: Plain language description of what will happen
        estimated_cost:   Estimated USD cost of this task
    """
    task_id:          str
    task_name:        str
    action_class:     str
    gate_reason:      str
    risk_rationale:   str
    reversible:       bool
    estimated_impact: str
    estimated_cost:   float = 0.0


# ── HumanReviewRequest ───────────────────────────────────────

class HumanReviewRequest(BaseModel):
    """
    A request for human review of one or more gated sub-tasks.

    Sent by EvaluateStage to the HumanReviewGateway.
    Written to AuditStore before being sent.
    Contains ALL gated tasks from one ApprovalGrant evaluation —
    human reviews everything at once, single interaction point.

    Fields:
        review_id:    Unique identifier for this review request
        grant_id:     The ApprovalGrant that triggered this review
        request_id:   Links to the WorkflowRequest
        tenant_id:    Organisation identifier
        user_id:      User who initiated the workflow
        requested_at: When the review was requested
        expires_at:   Auto-reject after this time (configurable timeout)
        gated_tasks:  All tasks requiring human approval
        workflow_task: The original user task description (context for reviewer)
        context:      Additional context for the reviewer
    """
    review_id:     uuid.UUID     = Field(default_factory=uuid.uuid4)
    grant_id:      uuid.UUID
    request_id:    uuid.UUID
    tenant_id:     str
    user_id:       str
    requested_at:  datetime      = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at:    datetime
    gated_tasks:   list[GatedTaskDetail]
    workflow_task: str           = ""  # original user task description
    context:       dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        grant_id:       uuid.UUID,
        request_id:     uuid.UUID,
        tenant_id:      str,
        user_id:        str,
        gated_tasks:    list[GatedTaskDetail],
        timeout_seconds: float = 3600.0,  # 1 hour default
        workflow_task:  str = "",
        context:        dict[str, Any] | None = None,
    ) -> HumanReviewRequest:
        """
        Create a review request with calculated expiry time.

        Args:
            grant_id:        ApprovalGrant that triggered this review
            request_id:      WorkflowRequest UUID
            tenant_id:       Organisation identifier
            user_id:         User who initiated the workflow
            gated_tasks:     List of tasks requiring human approval
            timeout_seconds: Seconds before auto-reject (default: 3600)
            workflow_task:   Original user task description
            context:         Additional context for the reviewer

        Returns:
            New HumanReviewRequest with expires_at set
        """
        now        = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=timeout_seconds)

        return cls(
            grant_id=grant_id,
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            requested_at=now,
            expires_at=expires_at,
            gated_tasks=gated_tasks,
            workflow_task=workflow_task,
            context=context or {},
        )

    @property
    def is_expired(self) -> bool:
        """True if the review request has passed its expiry time."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def gated_task_ids(self) -> list[str]:
        """Convenience: list of task_ids requiring review."""
        return [t.task_id for t in self.gated_tasks]

    @property
    def task_count(self) -> int:
        """Number of tasks requiring human review."""
        return len(self.gated_tasks)


# ── TaskDecision ─────────────────────────────────────────────

class TaskDecision(BaseModel):
    """
    A human reviewer's decision on a single gated task.

    Part of HumanReviewResponse.task_decisions.

    Fields:
        task_id:   The task being decided on (must be in HumanReviewRequest)
        decision:  "approved" or "rejected"
        reason:    Optional explanation from the reviewer
    """
    task_id:   str
    decision:  Literal["approved", "rejected"]
    reason:    str = ""

    @property
    def is_approved(self) -> bool:
        return self.decision == "approved"

    @property
    def is_rejected(self) -> bool:
        return self.decision == "rejected"


# ── HumanReviewResponse ──────────────────────────────────────

class HumanReviewResponse(BaseModel):
    """
    A human reviewer's response to a HumanReviewRequest.

    Contains a per-task decision for every task in the request.
    Written to AuditStore immediately on receipt.
    Immutable after creation — model is frozen.

    Fields:
        review_id:      Links to the HumanReviewRequest
        grant_id:       The ApprovalGrant being reviewed
        reviewer_id:    Identity of the human reviewer
        responded_at:   When the response was submitted
        task_decisions: Per-task decisions (one per gated task)
        notes:          Optional reviewer notes (applies to all tasks)
        timed_out:      True when this response was auto-generated on timeout
    """
    review_id:      uuid.UUID
    grant_id:       uuid.UUID
    reviewer_id:    str
    responded_at:   datetime     = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    task_decisions: list[TaskDecision]
    notes:          str          = ""
    timed_out:      bool         = False

    model_config = {"frozen": True}  # immutable after creation

    @classmethod
    def approved_all(
        cls,
        review_id:   uuid.UUID,
        grant_id:    uuid.UUID,
        reviewer_id: str,
        task_ids:    list[str],
        notes:       str = "",
    ) -> HumanReviewResponse:
        """Convenience constructor: approve all tasks."""
        return cls(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id=reviewer_id,
            task_decisions=[
                TaskDecision(task_id=tid, decision="approved")
                for tid in task_ids
            ],
            notes=notes,
        )

    @classmethod
    def rejected_all(
        cls,
        review_id:   uuid.UUID,
        grant_id:    uuid.UUID,
        reviewer_id: str,
        task_ids:    list[str],
        reason:      str = "",
        notes:       str = "",
    ) -> HumanReviewResponse:
        """Convenience constructor: reject all tasks."""
        return cls(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id=reviewer_id,
            task_decisions=[
                TaskDecision(task_id=tid, decision="rejected", reason=reason)
                for tid in task_ids
            ],
            notes=notes,
        )

    @classmethod
    def timeout_response(
        cls,
        review_id: uuid.UUID,
        grant_id:  uuid.UUID,
        task_ids:  list[str],
    ) -> HumanReviewResponse:
        """
        Auto-generated response when the review request times out.
        All tasks are rejected. reviewer_id is "system:timeout".
        """
        return cls(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id="system:timeout",
            task_decisions=[
                TaskDecision(
                    task_id=tid,
                    decision="rejected",
                    reason="Review request timed out — auto-rejected",
                )
                for tid in task_ids
            ],
            notes="Auto-rejected due to review timeout.",
            timed_out=True,
        )

    # ── Convenience properties ───────────────────────────────

    def is_fully_approved(self) -> bool:
        """True if ALL tasks are approved."""
        return all(d.is_approved for d in self.task_decisions)

    def has_rejections(self) -> bool:
        """True if ANY task is rejected."""
        return any(d.is_rejected for d in self.task_decisions)

    def approved_task_ids(self) -> list[str]:
        """List of approved task_ids."""
        return [d.task_id for d in self.task_decisions if d.is_approved]

    def rejected_task_ids(self) -> list[str]:
        """List of rejected task_ids."""
        return [d.task_id for d in self.task_decisions if d.is_rejected]

    def decision_for(self, task_id: str) -> TaskDecision | None:
        """Return the decision for a specific task_id, or None if not found."""
        for d in self.task_decisions:
            if d.task_id == task_id:
                return d
        return None
