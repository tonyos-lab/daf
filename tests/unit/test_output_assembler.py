"""
Unit tests for OutputAssembler.

Coverage:
  - assemble(): completed outcome, audit record written, result summary
  - assemble(): partial outcome from partial execution
  - escalate(): outcome, violation history in context, audit record
  - invalid_input(): outcome, escalation context, no request
  - audit_summary populated from AuditStore
  - No audit_store: methods still work, no audit written
  - loop.py integration: InputValidationError handled gracefully
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from daf.components.output_assembler import OutputAssembler
from daf.models.audit_record import AuditEventType
from daf.models.execution_result import ExecutionResult
from daf.models.final_response import FinalResponse
from daf.models.violation_report import ViolationReport, Violation
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.agent import AgentResult
from daf.runtime.audit_store import InMemoryAuditStore


# ── Fixtures ─────────────────────────────────────────────────

def make_workflow_request(
    task: str = "Test task",
) -> WorkflowRequest:
    return WorkflowRequest(
        request_id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        user_id="test-user",
        tenant_id="test-tenant",
        task_description=task,
    )


def make_exec_result(
    outcome:       str = "completed",
    step_results:  list[AgentResult] | None = None,
    cost_usd:      float = 0.05,
    duration_ms:   int = 1200,
) -> ExecutionResult:
    return ExecutionResult(
        grant_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        outcome=outcome,
        step_results=step_results or [
            AgentResult.ok(task_id="ST-01", output={"data": "result"},
                          cost_usd=0.03),
            AgentResult.ok(task_id="ST-02", output={"data": "result2"},
                          cost_usd=0.02),
        ],
        total_cost_usd=cost_usd,
        total_duration_ms=duration_ms,
        completed_at=datetime.now(timezone.utc),
    )


def make_violation_report(iteration: int = 1) -> ViolationReport:
    return ViolationReport(
        proposal_id=uuid.uuid4(),
        violations=[Violation(
            task_id="ST-01",
            dimension="tool_permission",
            severity="blocking",
            detail="Tool not permitted",
            suggestion="Use read_db",
        )],
        approvable_task_ids=[],
        escalate_to_human=False,
    )


# ── assemble() ────────────────────────────────────────────────

class TestOutputAssemblerAssemble:

    @pytest.mark.asyncio
    async def test_assemble_returns_final_response(self):
        """assemble() returns a FinalResponse."""
        assembler = OutputAssembler()
        req       = make_workflow_request()
        result    = make_exec_result()

        response = await assembler.assemble(
            workflow_request=req,
            exec_result=result,
            loop_iterations=1,
        )

        assert isinstance(response, FinalResponse)

    @pytest.mark.asyncio
    async def test_assemble_completed_outcome(self):
        """assemble() with completed ExecutionResult returns 'completed'."""
        assembler = OutputAssembler()
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(outcome="completed"),
            loop_iterations=1,
        )
        assert response.outcome == "completed"

    @pytest.mark.asyncio
    async def test_assemble_partial_outcome(self):
        """assemble() with partial ExecutionResult returns 'partial'."""
        assembler = OutputAssembler()
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(outcome="partial"),
            loop_iterations=2,
        )
        assert response.outcome == "partial"

    @pytest.mark.asyncio
    async def test_assemble_request_id_matches(self):
        """FinalResponse.request_id matches the WorkflowRequest."""
        assembler = OutputAssembler()
        req       = make_workflow_request()
        response  = await assembler.assemble(
            workflow_request=req,
            exec_result=make_exec_result(),
            loop_iterations=1,
        )
        assert response.request_id == req.request_id

    @pytest.mark.asyncio
    async def test_assemble_loop_iterations_stored(self):
        """loop_iterations is stored correctly."""
        assembler = OutputAssembler()
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(),
            loop_iterations=3,
        )
        assert response.loop_iterations == 3

    @pytest.mark.asyncio
    async def test_assemble_cost_from_exec_result(self):
        """total_cost_usd comes from ExecutionResult."""
        assembler = OutputAssembler()
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(cost_usd=0.147),
            loop_iterations=1,
        )
        assert response.total_cost_usd == pytest.approx(0.147)

    @pytest.mark.asyncio
    async def test_assemble_result_includes_step_summary(self):
        """result field contains step summaries."""
        assembler = OutputAssembler()
        steps     = [
            AgentResult.ok(task_id="ST-01", output={"x": 1}, cost_usd=0.02),
            AgentResult.ok(task_id="ST-02", output={"y": 2}, cost_usd=0.03),
        ]
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(step_results=steps),
            loop_iterations=1,
        )
        assert isinstance(response.result, list)
        assert len(response.result) == 2
        assert response.result[0]["task_id"] == "ST-01"
        assert response.result[0]["success"] is True

    @pytest.mark.asyncio
    async def test_assemble_failed_step_includes_error(self):
        """Failed step in result includes error message."""
        assembler = OutputAssembler()
        steps     = [
            AgentResult.fail(task_id="ST-01", error="extraction failed"),
        ]
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(
                outcome="partial", step_results=steps, cost_usd=0.0
            ),
            loop_iterations=1,
        )
        assert response.result[0]["error"] == "extraction failed"

    @pytest.mark.asyncio
    async def test_assemble_writes_workflow_completed_audit(self):
        """WORKFLOW_COMPLETED audit record is written."""
        store     = InMemoryAuditStore()
        assembler = OutputAssembler(audit_store=store)
        req       = make_workflow_request()

        await assembler.assemble(
            workflow_request=req,
            exec_result=make_exec_result(),
            loop_iterations=1,
        )

        records    = await store.query(req.request_id)
        event_types = [r.event_type for r in records]
        assert AuditEventType.WORKFLOW_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_assemble_audit_payload_includes_outcome(self):
        """WORKFLOW_COMPLETED audit payload includes outcome and cost."""
        store     = InMemoryAuditStore()
        assembler = OutputAssembler(audit_store=store)
        req       = make_workflow_request()

        await assembler.assemble(
            workflow_request=req,
            exec_result=make_exec_result(outcome="completed", cost_usd=0.08),
            loop_iterations=1,
        )

        records  = await store.query(
            req.request_id,
            event_type=AuditEventType.WORKFLOW_COMPLETED,
        )
        payload = records[0].payload
        assert payload["outcome"]        == "completed"
        assert payload["total_cost_usd"] == pytest.approx(0.08)

    @pytest.mark.asyncio
    async def test_assemble_no_audit_store_does_not_raise(self):
        """assemble() works without an AuditStore."""
        assembler = OutputAssembler(audit_store=None)
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(),
            loop_iterations=1,
        )
        assert response.outcome == "completed"
        assert response.audit_summary == {}


# ── escalate() ───────────────────────────────────────────────

class TestOutputAssemblerEscalate:

    @pytest.mark.asyncio
    async def test_escalate_returns_escalated_outcome(self):
        """escalate() returns FinalResponse with outcome='escalated'."""
        assembler = OutputAssembler()
        response  = await assembler.escalate(
            workflow_request=make_workflow_request(),
            violation_history=[make_violation_report()],
        )
        assert response.outcome == "escalated"

    @pytest.mark.asyncio
    async def test_escalate_iterations_from_history_length(self):
        """loop_iterations equals len(violation_history)."""
        assembler = OutputAssembler()
        history   = [make_violation_report(), make_violation_report()]
        response  = await assembler.escalate(
            workflow_request=make_workflow_request(),
            violation_history=history,
        )
        assert response.loop_iterations == 2

    @pytest.mark.asyncio
    async def test_escalate_context_includes_violation_history(self):
        """escalation_context contains violation_history."""
        assembler = OutputAssembler()
        response  = await assembler.escalate(
            workflow_request=make_workflow_request(),
            violation_history=[make_violation_report()],
        )
        assert response.escalation_context is not None
        assert "violation_history" in response.escalation_context
        assert len(response.escalation_context["violation_history"]) == 1

    @pytest.mark.asyncio
    async def test_escalate_context_includes_message(self):
        """escalation_context includes a human-readable message."""
        assembler = OutputAssembler()
        response  = await assembler.escalate(
            workflow_request=make_workflow_request(),
            violation_history=[make_violation_report()],
        )
        assert "message" in response.escalation_context
        assert len(response.escalation_context["message"]) > 0

    @pytest.mark.asyncio
    async def test_escalate_zero_cost(self):
        """Escalated response has zero cost."""
        assembler = OutputAssembler()
        response  = await assembler.escalate(
            workflow_request=make_workflow_request(),
            violation_history=[make_violation_report()],
        )
        assert response.total_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_escalate_writes_workflow_escalated_audit(self):
        """WORKFLOW_ESCALATED audit record is written."""
        store     = InMemoryAuditStore()
        assembler = OutputAssembler(audit_store=store)
        req       = make_workflow_request()

        await assembler.escalate(
            workflow_request=req,
            violation_history=[make_violation_report()],
        )

        event_types = [
            r.event_type
            for r in await store.query(req.request_id)
        ]
        assert AuditEventType.WORKFLOW_ESCALATED in event_types

    @pytest.mark.asyncio
    async def test_escalate_empty_history(self):
        """escalate() handles empty violation_history gracefully."""
        assembler = OutputAssembler()
        response  = await assembler.escalate(
            workflow_request=make_workflow_request(),
            violation_history=[],
        )
        assert response.outcome == "escalated"
        assert response.loop_iterations == 0


# ── invalid_input() ──────────────────────────────────────────

class TestOutputAssemblerInvalidInput:

    @pytest.mark.asyncio
    async def test_invalid_input_returns_invalid_input_outcome(self):
        """invalid_input() returns outcome='invalid_input'."""
        assembler = OutputAssembler()
        response  = await assembler.invalid_input(
            workflow_request=make_workflow_request(),
            field="task",
            reason="must not be empty",
        )
        assert response.outcome == "invalid_input"

    @pytest.mark.asyncio
    async def test_invalid_input_zero_iterations(self):
        """invalid_input() returns loop_iterations=0."""
        assembler = OutputAssembler()
        response  = await assembler.invalid_input(
            workflow_request=make_workflow_request(),
            field="task",
            reason="too long",
        )
        assert response.loop_iterations == 0

    @pytest.mark.asyncio
    async def test_invalid_input_context_includes_field_and_reason(self):
        """escalation_context includes field and reason."""
        assembler = OutputAssembler()
        response  = await assembler.invalid_input(
            workflow_request=make_workflow_request(),
            field="constraints.max_cost_usd",
            reason="must be greater than 0",
        )
        ctx = response.escalation_context
        assert ctx["field"]  == "constraints.max_cost_usd"
        assert ctx["reason"] == "must be greater than 0"

    @pytest.mark.asyncio
    async def test_invalid_input_with_no_request(self):
        """invalid_input() works when workflow_request is None."""
        assembler = OutputAssembler()
        response  = await assembler.invalid_input(
            workflow_request=None,
            field="task",
            reason="must not be empty",
        )
        assert response.outcome == "invalid_input"
        assert response.request_id is not None  # generated UUID

    @pytest.mark.asyncio
    async def test_invalid_input_zero_cost(self):
        """invalid_input() has zero cost."""
        assembler = OutputAssembler()
        response  = await assembler.invalid_input(
            workflow_request=make_workflow_request(),
            field="task",
            reason="empty",
        )
        assert response.total_cost_usd == 0.0


# ── audit_summary ─────────────────────────────────────────────

class TestOutputAssemblerAuditSummary:

    @pytest.mark.asyncio
    async def test_audit_summary_populated_when_store_available(self):
        """audit_summary is populated from AuditStore records."""
        from daf.models.audit_record import AuditRecord
        store     = InMemoryAuditStore()
        assembler = OutputAssembler(audit_store=store)
        req       = make_workflow_request()

        # Pre-populate store with some events
        for event_type in [
            AuditEventType.WORKFLOW_STARTED,
            AuditEventType.PLAN_PROPOSED,
            AuditEventType.PLAN_EVALUATED,
        ]:
            await store.write(AuditRecord.make(
                request_id=req.request_id,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                event_type=event_type,
            ))

        response = await assembler.assemble(
            workflow_request=req,
            exec_result=make_exec_result(),
            loop_iterations=1,
        )

        summary = response.audit_summary
        assert summary.get("total_events", 0) > 0
        assert "event_counts" in summary

    @pytest.mark.asyncio
    async def test_audit_summary_empty_without_store(self):
        """audit_summary is {} when no AuditStore configured."""
        assembler = OutputAssembler(audit_store=None)
        response  = await assembler.assemble(
            workflow_request=make_workflow_request(),
            exec_result=make_exec_result(),
            loop_iterations=1,
        )
        assert response.audit_summary == {}


# ── loop.py integration ───────────────────────────────────────

class TestLoopInputValidationHandling:
    """
    Verify the GovernedAgenticLoop handles InputValidationError
    correctly by returning FinalResponse(outcome="invalid_input")
    instead of raising.
    """

    @pytest.mark.asyncio
    async def test_empty_task_returns_invalid_input_response(self):
        """Empty task → FinalResponse(outcome='invalid_input')."""
        from unittest.mock import AsyncMock
        from daf.loop import GovernedAgenticLoop
        from daf.runtime.llm_client import LLMClient
        import tempfile, yaml

        # Minimal policy matrix
        matrix_data = {
            "version": "1.0.0", "tenant_id": "test",
            "effective": "2026-01-01T00:00:00Z",
            "agent_roles": {"test_agent": {
                "permitted_tools": ["read_db"],
                "permitted_data_sources": [],
                "permitted_task_types": ["llm_extraction"],
                "max_llm_calls_per_step": 3,
            }}
        }
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", delete=False, mode="w"
        ) as f:
            yaml.dump(matrix_data, f)
            tmp = f.name

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.model_id = "test-model"

        loop = GovernedAgenticLoop(
            llm_client=mock_llm,
            policy_matrix=tmp,
        )

        response = await loop.run({"task": ""})

        assert isinstance(response, FinalResponse)
        assert response.outcome == "invalid_input"
        assert response.loop_iterations == 0
        # LLM should never be called for invalid input
        mock_llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_task_returns_invalid_input_response(self):
        """Missing task key → FinalResponse(outcome='invalid_input')."""
        from unittest.mock import AsyncMock
        from daf.loop import GovernedAgenticLoop
        from daf.runtime.llm_client import LLMClient
        import tempfile, yaml

        matrix_data = {
            "version": "1.0.0", "tenant_id": "test",
            "effective": "2026-01-01T00:00:00Z",
            "agent_roles": {}
        }
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", delete=False, mode="w"
        ) as f:
            yaml.dump(matrix_data, f)
            tmp = f.name

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.model_id = "test-model"

        loop = GovernedAgenticLoop(
            llm_client=mock_llm,
            policy_matrix=tmp,
        )

        response = await loop.run({})  # no task key

        assert response.outcome == "invalid_input"
