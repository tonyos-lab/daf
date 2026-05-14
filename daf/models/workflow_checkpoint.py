"""
WorkflowCheckpoint — execution state snapshot for a workflow.

Saved after each completed sub-task by the ExecutionOrchestrator.
Enables resumption from the last successful step on failure or
after a HITL gate suspends execution.

Checkpoints are:
  - Mutable: updated as tasks complete (unlike AuditRecord)
  - Temporary: deleted on workflow completion (unlike AuditRecord)
  - One per workflow: identified by request_id

CHECKPOINT STATES:
  running:        normal execution in progress
  awaiting_hitl:  paused at a human gate — waiting for review response
  resuming:       human approved — execution resuming from paused_at_task
  completed:      workflow finished — checkpoint may be deleted
  failed:         unexpected failure — checkpoint preserved for retry
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class CheckpointState:
    """Valid states for a WorkflowCheckpoint."""
    RUNNING        = "running"
    AWAITING_HITL  = "awaiting_hitl"
    RESUMING       = "resuming"
    COMPLETED      = "completed"
    FAILED         = "failed"

    ALL: frozenset[str] = frozenset({
        RUNNING, AWAITING_HITL, RESUMING, COMPLETED, FAILED
    })


class WorkflowCheckpoint(BaseModel):
    """
    Execution state snapshot for a workflow.

    Updated after each completed sub-task.
    Loaded on resume to determine which tasks remain.

    Fields:
        checkpoint_id:   Unique identifier for this checkpoint record
        request_id:      Links to the WorkflowRequest
        grant_id:        Links to the ApprovalGrant authorising execution
        state:           Current execution state (CheckpointState constant)
        completed_tasks: task_id → serialised AgentResult for finished tasks
        pending_tasks:   task_ids that have not yet been executed
        paused_at_task:  task_id where execution is paused (HITL gate)
        budget_spent:    Total cost incurred so far in USD
        created_at:      When this checkpoint was first created
        updated_at:      When this checkpoint was last updated
        metadata:        Optional extra data (e.g. HITL review_id)
    """

    checkpoint_id:   uuid.UUID       = Field(default_factory=uuid.uuid4)
    request_id:      uuid.UUID
    grant_id:        uuid.UUID
    state:           str             = CheckpointState.RUNNING
    completed_tasks: dict[str, Any]  = Field(default_factory=dict)
    # task_id → AgentResult.model_dump() — serialised for storage
    pending_tasks:   list[str]       = Field(default_factory=list)
    paused_at_task:  str | None      = None
    budget_spent:    float           = 0.0
    created_at:      datetime        = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at:      datetime        = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata:        dict[str, Any]  = Field(default_factory=dict)

    def mark_task_complete(
        self,
        task_id:      str,
        agent_result: Any,       # AgentResult
        cost_usd:     float = 0.0,
    ) -> WorkflowCheckpoint:
        """
        Return an updated checkpoint with a task marked complete.

        Does NOT mutate in place — returns a new checkpoint.
        The ExecutionOrchestrator saves the returned checkpoint.

        Args:
            task_id:      The completed task_id
            agent_result: The AgentResult from the agent
            cost_usd:     Cost incurred by this task

        Returns:
            New WorkflowCheckpoint with updated state
        """
        updated_completed = dict(self.completed_tasks)
        updated_completed[task_id] = (
            agent_result.model_dump()
            if hasattr(agent_result, "model_dump")
            else agent_result
        )

        updated_pending = [t for t in self.pending_tasks if t != task_id]

        return self.model_copy(update={
            "completed_tasks": updated_completed,
            "pending_tasks":   updated_pending,
            "budget_spent":    self.budget_spent + cost_usd,
            "updated_at":      datetime.now(timezone.utc),
        })

    def mark_awaiting_hitl(
        self,
        paused_at_task: str,
        review_id:      str | None = None,
    ) -> WorkflowCheckpoint:
        """Return an updated checkpoint paused at a HITL gate."""
        metadata = dict(self.metadata)
        if review_id:
            metadata["review_id"] = review_id

        return self.model_copy(update={
            "state":          CheckpointState.AWAITING_HITL,
            "paused_at_task": paused_at_task,
            "updated_at":     datetime.now(timezone.utc),
            "metadata":       metadata,
        })

    def mark_resuming(self) -> WorkflowCheckpoint:
        """Return an updated checkpoint resuming after HITL approval."""
        return self.model_copy(update={
            "state":      CheckpointState.RESUMING,
            "updated_at": datetime.now(timezone.utc),
        })

    def mark_completed(self) -> WorkflowCheckpoint:
        """Return an updated checkpoint in completed state."""
        return self.model_copy(update={
            "state":         CheckpointState.COMPLETED,
            "pending_tasks": [],
            "updated_at":    datetime.now(timezone.utc),
        })

    def mark_failed(
        self,
        reason: str,
        failed_task: str | None = None,
    ) -> WorkflowCheckpoint:
        """Return an updated checkpoint in failed state."""
        metadata = dict(self.metadata)
        metadata["failure_reason"] = reason
        if failed_task:
            metadata["failed_task"] = failed_task

        return self.model_copy(update={
            "state":      CheckpointState.FAILED,
            "updated_at": datetime.now(timezone.utc),
            "metadata":   metadata,
        })

    @classmethod
    def create(
        cls,
        request_id:    uuid.UUID,
        grant_id:      uuid.UUID,
        pending_tasks: list[str],
    ) -> WorkflowCheckpoint:
        """
        Create an initial checkpoint at the start of execution.

        Args:
            request_id:    The WorkflowRequest UUID
            grant_id:      The ApprovalGrant UUID
            pending_tasks: All task_ids to be executed (in dependency order)

        Returns:
            New WorkflowCheckpoint in RUNNING state
        """
        return cls(
            request_id=request_id,
            grant_id=grant_id,
            state=CheckpointState.RUNNING,
            pending_tasks=pending_tasks,
        )
