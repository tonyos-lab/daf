"""
OutputAssembler — assembles FinalResponses and writes terminal audit records.

The last component called in the GovernedAgenticLoop.
Responsible for:
  1. Writing terminal audit records (workflow_completed / workflow_escalated)
  2. Building the FinalResponse returned to the caller
  3. Including cost summaries and audit event counts

DESIGN:
  OutputAssembler is injected with an AuditStore.
  It writes terminal events — the loop itself writes
  intermediate events (via EvaluateStage and ExecutionOrchestrator).

  If no AuditStore is configured (backwards compat),
  terminal events are silently skipped.
"""
from __future__ import annotations

import logging
from typing import Any

from daf.models.audit_record import AuditRecord, AuditEventType
from daf.models.execution_result import ExecutionResult
from daf.models.final_response import FinalResponse
from daf.models.violation_report import ViolationReport
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.audit_store import AuditStore

logger = logging.getLogger(__name__)


class OutputAssembler:
    """
    Assembles FinalResponses and writes terminal audit records.

    Injected with an AuditStore for writing WORKFLOW_COMPLETED
    and WORKFLOW_ESCALATED audit records.
    """

    def __init__(self, audit_store: AuditStore | None = None) -> None:
        self._audit_store = audit_store

    async def assemble(
        self,
        workflow_request: WorkflowRequest,
        exec_result:      ExecutionResult,
        loop_iterations:  int,
    ) -> FinalResponse:
        """
        Assemble a FinalResponse for a completed or partial workflow.

        Writes WORKFLOW_COMPLETED audit record.

        Args:
            workflow_request: The original request
            exec_result:      The ExecutionResult from ExecutionOrchestrator
            loop_iterations:  Number of plan/evaluate iterations

        Returns:
            FinalResponse with outcome "completed" or "partial"
        """
        outcome = exec_result.outcome  # "completed" or "partial"

        # Build result summary from step results
        step_summary = [
            {
                "task_id": r.task_id,
                "success": r.success,
                "cost_usd": r.cost_usd,
                **({"error": r.error} if not r.success else {}),
            }
            for r in exec_result.step_results
        ]

        # Write terminal audit record
        await self._write_audit(
            workflow_request=workflow_request,
            event_type=AuditEventType.WORKFLOW_COMPLETED,
            payload={
                "outcome":         outcome,
                "loop_iterations": loop_iterations,
                "total_cost_usd":  exec_result.total_cost_usd,
                "duration_ms":     exec_result.total_duration_ms,
                "step_count":      len(exec_result.step_results),
                "steps_succeeded": sum(
                    1 for r in exec_result.step_results if r.success
                ),
                "steps_failed":    sum(
                    1 for r in exec_result.step_results if not r.success
                ),
            },
        )

        # Build audit summary
        audit_summary = await self._build_audit_summary(workflow_request)

        logger.info(
            f"OutputAssembler: assembled {outcome} response "
            f"(iterations={loop_iterations}, "
            f"cost=${exec_result.total_cost_usd:.4f})"
        )

        return FinalResponse(
            request_id=workflow_request.request_id,
            outcome=outcome,
            loop_iterations=loop_iterations,
            total_cost_usd=exec_result.total_cost_usd,
            result=step_summary if step_summary else None,
            audit_summary=audit_summary,
        )

    async def escalate(
        self,
        workflow_request:  WorkflowRequest,
        violation_history: list[ViolationReport],
    ) -> FinalResponse:
        """
        Assemble a FinalResponse for an escalated workflow.

        Writes WORKFLOW_ESCALATED audit record.

        Args:
            workflow_request:  The original request
            violation_history: All ViolationReports from the loop

        Returns:
            FinalResponse with outcome "escalated"
        """
        # Summarise violations for escalation context
        violation_summaries = []
        for i, report in enumerate(violation_history):
            violation_summaries.append({
                "iteration": i + 1,
                "violations": [
                    {
                        "task_id":   v.task_id,
                        "dimension": v.dimension,
                        "detail":    v.detail,
                        "suggestion": v.suggestion,
                    }
                    for v in report.violations
                ],
                "escalate_to_human": report.escalate_to_human,
            })

        escalation_context = {
            "message":           "No compliant plan found. Human review required.",
            "total_iterations":  len(violation_history),
            "violation_history": violation_summaries,
        }

        # Write terminal audit record
        await self._write_audit(
            workflow_request=workflow_request,
            event_type=AuditEventType.WORKFLOW_ESCALATED,
            payload={
                "outcome":          "escalated",
                "total_iterations": len(violation_history),
                "total_violations": sum(
                    len(r.violations) for r in violation_history
                ),
                "escalate_to_human": (
                    violation_history[-1].escalate_to_human
                    if violation_history else False
                ),
            },
        )

        audit_summary = await self._build_audit_summary(workflow_request)

        logger.warning(
            f"OutputAssembler: escalated after "
            f"{len(violation_history)} iteration(s)"
        )

        return FinalResponse(
            request_id=workflow_request.request_id,
            outcome="escalated",
            loop_iterations=len(violation_history),
            total_cost_usd=0.0,
            result=None,
            escalation_context=escalation_context,
            audit_summary=audit_summary,
        )

    async def invalid_input(
        self,
        workflow_request: WorkflowRequest | None,
        field:            str,
        reason:           str,
    ) -> FinalResponse:
        """
        Assemble a FinalResponse for an invalid input.

        Called when InputProcessor raises InputValidationError.
        Writes WORKFLOW_ESCALATED audit record (closest semantic fit).

        Args:
            workflow_request: May be None if InputProcessor failed before
                              building a WorkflowRequest
            field:            The invalid field name
            reason:           Why the field is invalid

        Returns:
            FinalResponse with outcome "invalid_input"
        """
        # Generate a minimal request_id if we have no request
        import uuid
        req_id = (
            workflow_request.request_id
            if workflow_request else uuid.uuid4()
        )

        if workflow_request is not None:
            await self._write_audit(
                workflow_request=workflow_request,
                event_type=AuditEventType.WORKFLOW_ESCALATED,
                payload={
                    "outcome":          "invalid_input",
                    "validation_field": field,
                    "validation_error": reason,
                },
            )

        logger.warning(
            f"OutputAssembler: invalid_input "
            f"field={field!r} reason={reason!r}"
        )

        return FinalResponse(
            request_id=req_id,
            outcome="invalid_input",
            loop_iterations=0,
            total_cost_usd=0.0,
            result=None,
            escalation_context={
                "message": f"Invalid input: field '{field}' — {reason}",
                "field":   field,
                "reason":  reason,
            },
        )

    # ── Private helpers ──────────────────────────────────────

    async def _write_audit(
        self,
        workflow_request: WorkflowRequest,
        event_type:       str,
        payload:          dict[str, Any],
    ) -> None:
        """Write audit record if audit_store is configured."""
        if self._audit_store is None:
            return
        await self._audit_store.write(AuditRecord.make(
            request_id=workflow_request.request_id,
            tenant_id=workflow_request.tenant_id,
            user_id=workflow_request.user_id,
            event_type=event_type,
            payload=payload,
        ))

    async def _build_audit_summary(
        self,
        workflow_request: WorkflowRequest,
    ) -> dict[str, Any]:
        """
        Build a summary of audit events for this workflow.
        Returns empty dict if no audit_store configured.
        """
        if self._audit_store is None:
            return {}

        try:
            records = await self._audit_store.query(
                workflow_request.request_id
            )
            from collections import Counter
            event_counts = dict(Counter(r.event_type for r in records))
            return {
                "total_events": len(records),
                "event_counts": event_counts,
            }
        except Exception as e:
            logger.warning(f"Failed to build audit summary: {e}")
            return {}
