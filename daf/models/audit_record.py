"""
AuditRecord — the immutable record of every significant event in a workflow.

Every audit record is:
  - Written once — never modified
  - Linked to a WorkflowRequest via request_id
  - Timestamped at creation
  - Typed by event_type (one of AuditEventType constants)
  - Carries event-specific data in payload (JSONB in PostgreSQL)

The audit trail is what makes DAF trustworthy for compliance.
Without it, there is no proof of what happened, when, why, and by whom.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AuditEventType:
    """
    Constants for all audit event types.

    Using a class of string constants rather than an Enum
    allows downstream code to record custom event types
    (e.g. "custom_step_started") without modifying DAF.
    """
    # Workflow lifecycle
    WORKFLOW_STARTED    = "workflow_started"
    WORKFLOW_COMPLETED  = "workflow_completed"
    WORKFLOW_ESCALATED  = "workflow_escalated"

    # Planning
    PLAN_PROPOSED       = "plan_proposed"
    PLAN_EVALUATED      = "plan_evaluated"   # APPROVED or REJECTED

    # HITL
    HUMAN_REVIEW_REQUESTED = "human_review_requested"
    HUMAN_REVIEW_RESPONDED = "human_review_responded"

    # Execution
    EXECUTION_STARTED   = "execution_started"
    STEP_STARTED        = "step_started"
    STEP_COMPLETED      = "step_completed"
    STEP_FAILED         = "step_failed"

    # All valid types for validation
    ALL: frozenset[str] = frozenset({
        WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_ESCALATED,
        PLAN_PROPOSED, PLAN_EVALUATED,
        HUMAN_REVIEW_REQUESTED, HUMAN_REVIEW_RESPONDED,
        EXECUTION_STARTED, STEP_STARTED, STEP_COMPLETED, STEP_FAILED,
    })


class AuditRecord(BaseModel):
    """
    An immutable record of a single event in a workflow.

    Created by AuditStore.make() helper and written by AuditStore.write().
    Never modified after creation.

    Fields:
        audit_id:    Unique identifier for this record
        request_id:  Links to the WorkflowRequest that produced this event
        tenant_id:   Organisation identifier
        user_id:     User who initiated the workflow
        event_type:  One of AuditEventType constants (or custom string)
        payload:     Event-specific data (structured, serialisable)
        created_at:  UTC timestamp of record creation
    """

    audit_id:   uuid.UUID            = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    tenant_id:  str
    user_id:    str
    event_type: str
    payload:    dict[str, Any]       = Field(default_factory=dict)
    created_at: datetime             = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = {"frozen": True}   # immutable after creation

    @classmethod
    def make(
        cls,
        request_id:  uuid.UUID,
        tenant_id:   str,
        user_id:     str,
        event_type:  str,
        payload:     dict[str, Any] | None = None,
    ) -> AuditRecord:
        """
        Convenience factory method.

        Args:
            request_id: UUID of the WorkflowRequest
            tenant_id:  Organisation identifier
            user_id:    User who initiated the workflow
            event_type: One of AuditEventType constants
            payload:    Event-specific data

        Returns:
            New AuditRecord with generated audit_id and current timestamp
        """
        return cls(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            payload=payload or {},
        )
