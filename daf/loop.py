"""
GovernedAgenticLoop — the central mechanism of DAF.

The model proposes. The system governs. The system acts.

PLAN → EVALUATE → EXECUTE
  ↑         |
  └─────────┘
  (on NOT_EXECUTABLE — re-plan with context)

Phase 2: EvaluateStage replaces direct PolicyEngine call.
         Full audit trail via AuditStore.
         All five components are now wired.
"""
from __future__ import annotations

import logging
from typing import Any

from daf.components.evaluate_stage import EvaluateStage
from daf.components.execution_orchestrator import ExecutionOrchestrator
from daf.components.input_processor import InputProcessor, InputValidationError
from daf.components.output_assembler import OutputAssembler
from daf.components.planning_orchestrator import PlanningOrchestrator
from daf.components.policy_engine import PolicyEngine
from daf.models.audit_record import AuditRecord, AuditEventType
from daf.models.final_response import FinalResponse
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.audit_store import AuditStore, InMemoryAuditStore
from daf.runtime.checkpoint_store import CheckpointStore, InMemoryCheckpointStore
from daf.runtime.human_review_gateway import BaseHumanReviewGateway
from daf.runtime.llm_client import LLMClient, LLMClientError, LLMOutputError
from daf.runtime.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class GovernedAgenticLoop:
    """
    The Governed Agentic Loop: Propose → Evaluate → Execute.

    Phase 2 wiring:
      - EvaluateStage owns evaluate phase (PolicyEngine + HITL)
      - OutputAssembler writes terminal audit records
      - InputValidationError handled gracefully
      - AuditStore + CheckpointStore injectable

    Usage:
        from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage

        class MyClient(LLMClient):
            async def complete(self, system, user, schema) -> LLMResponse: ...
            def estimate_cost(self, input_tokens, output_tokens) -> float: ...
            @property
            def model_id(self) -> str: ...

        loop = GovernedAgenticLoop(
            llm_client=MyClient(),
            policy_matrix="policies/default.yaml",
        )
        result = await loop.run({"task": "Analyse the contracts"})

    DAF is provider-agnostic. Implement LLMClient for any model backend.
    """

    def __init__(
        self,
        llm_client:           LLMClient,
        policy_matrix:        str                          = "policy/matrix/example.yaml",
        audit_store:          AuditStore | None            = None,
        checkpoint_store:     CheckpointStore | None       = None,
        hitl_gateway:         BaseHumanReviewGateway | None = None,
        hitl_timeout_seconds: float                        = 3600.0,
        agent_registry:       AgentRegistry | None         = None,
        tool_registry:        ToolRegistry | None           = None,
    ) -> None:
        # Infrastructure
        _audit_store      = audit_store      if audit_store      is not None else InMemoryAuditStore()
        _checkpoint_store = checkpoint_store if checkpoint_store is not None else InMemoryCheckpointStore()

        # Core components
        self.policy_engine           = PolicyEngine(policy_matrix_path=policy_matrix)
        self.input_processor         = InputProcessor(policy_engine=self.policy_engine)
        self.planning_orchestrator   = PlanningOrchestrator(llm_client=llm_client)
        self.evaluate_stage          = EvaluateStage(
            policy_engine=self.policy_engine,
            audit_store=_audit_store,
            hitl_gateway=hitl_gateway,
            hitl_timeout_seconds=hitl_timeout_seconds,
        )
        self.execution_orchestrator  = ExecutionOrchestrator(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            audit_store=_audit_store,
            checkpoint_store=_checkpoint_store,
        )
        self.output_assembler        = OutputAssembler(audit_store=_audit_store)

        # Store for direct access in run()
        self._audit_store = _audit_store

    async def run(self, raw_request: dict[str, Any]) -> FinalResponse:
        """
        Run a workflow through the Governed Agentic Loop.

        Returns FinalResponse for all expected outcomes:
          "completed"     — workflow finished successfully
          "partial"       — some tasks failed
          "escalated"     — no compliant plan or HITL forced escalation
          "invalid_input" — input validation failed

        Raises:
          LLMClientError:  LLM API failure (network, auth, rate limit)
          LLMOutputError:  LLM schema validation failure after retries
        """
        # ── Stage 1: Input validation ────────────────────────
        try:
            workflow_request = self.input_processor.process(raw_request)
        except InputValidationError as e:
            return await self.output_assembler.invalid_input(
                workflow_request=None,
                field=e.field,
                reason=e.reason,
            )

        policy_matrix     = self.policy_engine.load_matrix(
            tenant_id=workflow_request.tenant_id
        )
        violation_history = []
        iteration         = 0
        max_attempts      = policy_matrix.loop_policy.max_replan_attempts

        # Write workflow_started audit record
        await self._audit_store.write(AuditRecord.make(
            request_id=workflow_request.request_id,
            tenant_id=workflow_request.tenant_id,
            user_id=workflow_request.user_id,
            event_type=AuditEventType.WORKFLOW_STARTED,
            payload={
                "task_description": workflow_request.task_description[:200],
                "intent_class":     workflow_request.intent_class,
                "tenant_id":        workflow_request.tenant_id,
            },
        ))

        logger.info(
            "GovernedAgenticLoop started",
            extra={
                "request_id": str(workflow_request.request_id),
                "tenant_id":  workflow_request.tenant_id,
                "user_id":    workflow_request.user_id,
            },
        )

        # ── The Governed Agentic Loop ────────────────────────
        while iteration < max_attempts:
            iteration += 1

            # ── Stage 2: Plan ────────────────────────────────
            logger.debug(f"Planning iteration {iteration}/{max_attempts}")

            proposal = await self.planning_orchestrator.plan(
                workflow_request=workflow_request,
                policy_matrix=policy_matrix,
                violation_history=violation_history,
                iteration=iteration,
            )

            # Write plan_proposed audit record
            await self._audit_store.write(AuditRecord.make(
                request_id=workflow_request.request_id,
                tenant_id=workflow_request.tenant_id,
                user_id=workflow_request.user_id,
                event_type=AuditEventType.PLAN_PROPOSED,
                payload={
                    "proposal_id":   str(proposal.proposal_id),
                    "iteration":     iteration,
                    "sub_task_count": len(proposal.sub_tasks),
                    "estimated_cost": proposal.total_estimated_cost,
                    "confidence":    proposal.confidence,
                },
            ))

            # ── Stage 3: Evaluate (PolicyEngine + HITL) ──────
            outcome = await self.evaluate_stage.run(
                proposal=proposal,
                policy_matrix=policy_matrix,
                workflow_request=workflow_request,
            )

            if outcome.is_executable():
                # ── Stage 4: Execute ──────────────────────────
                logger.info(
                    f"Plan executable on iteration {iteration}",
                    extra={
                        "proposal_id":  str(proposal.proposal_id),
                        "gated_tasks":  outcome.approval_grant.gated_tasks,
                    },
                )

                exec_result = await self.execution_orchestrator.execute(
                    approval_grant=outcome.approval_grant,
                    workflow_request=workflow_request,
                )

                return await self.output_assembler.assemble(
                    workflow_request=workflow_request,
                    exec_result=exec_result,
                    loop_iterations=iteration,
                )

            # NOT_EXECUTABLE — collect violation for re-planning
            violation = outcome.as_violation()
            violation_history.append(violation)

            logger.info(
                f"Plan not executable on iteration {iteration}: "
                f"{len(violation.violations)} violation(s)",
                extra={"proposal_id": str(proposal.proposal_id)},
            )

            if violation.escalate_to_human:
                logger.warning("Escalation triggered — no compliant plan found")
                break

        # ── Loop exhausted ────────────────────────────────────
        return await self.output_assembler.escalate(
            workflow_request=workflow_request,
            violation_history=violation_history,
        )
