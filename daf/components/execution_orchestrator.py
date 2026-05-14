"""
ExecutionOrchestrator — runs approved plans with scoped permissions.

Receives an ApprovalGrant from EvaluateStage.
Executes every sub-task in dependency order.
Each agent runs inside a ScopedContext built from the grant.

WHAT IT DOES:
  1. Creates initial WorkflowCheckpoint
  2. Creates shared BudgetTracker from grant
  3. Executes sub-tasks in dependency order
  4. Each agent runs with ScopedContext (scoped tools + budget)
  5. Checkpoints after every completed step
  6. Writes audit records throughout
  7. Returns ExecutionResult

CRITICAL INVARIANT (from design-philosophy.md, Principle 7):
  Agents are instantiated from ApprovalGrant permissions only.
  No agent can request additional permissions after instantiation.
  The ScopedContext is built once and is immutable.

WHAT IT DOES NOT DO:
  - Does not call the LLM (that is PlanningOrchestrator only)
  - Does not evaluate policy (that is PolicyEngine + EvaluateStage)
  - Does not expand permissions at runtime
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from daf.models.approval_grant import ApprovalGrant
from daf.models.audit_record import AuditRecord, AuditEventType
from daf.models.execution_result import ExecutionResult
from daf.models.plan_proposal import SubTask
from daf.models.workflow_checkpoint import WorkflowCheckpoint
from daf.runtime.agent import AgentResult, AgentExecutionError
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.audit_store import AuditStore
from daf.runtime.budget_tracker import BudgetTracker
from daf.runtime.checkpoint_store import CheckpointStore
from daf.runtime.scoped_context import ScopedContext
from daf.runtime.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """
    Raised when execution cannot continue due to an unrecoverable error.

    Distinct from a failed AgentResult (which is a task-level failure).
    ExecutionError means the ExecutionOrchestrator itself has encountered
    an infrastructure problem (missing agent, dependency not met, etc.)
    """
    def __init__(self, reason: str, task_id: str | None = None) -> None:
        super().__init__(
            f"Execution failed"
            + (f" at task '{task_id}'" if task_id else "")
            + f": {reason}"
        )
        self.reason  = reason
        self.task_id = task_id


class ExecutionOrchestrator:
    """
    Executes approved plans with runtime-scoped agent permissions.

    Requires:
      agent_registry:    AgentRegistry with all agent classes registered
      tool_registry:     ToolRegistry with all tool instances registered
      audit_store:       AuditStore for writing step events
      checkpoint_store:  CheckpointStore for saving execution state

    Usage (from GovernedAgenticLoop):
        orchestrator = ExecutionOrchestrator(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            audit_store=audit_store,
            checkpoint_store=checkpoint_store,
        )
        result = await orchestrator.execute(approval_grant, workflow_request)
    """

    def __init__(
        self,
        agent_registry:   AgentRegistry | None   = None,
        tool_registry:    ToolRegistry | None     = None,
        audit_store:      AuditStore | None       = None,
        checkpoint_store: CheckpointStore | None  = None,
    ) -> None:
        self._agent_registry   = agent_registry
        self._tool_registry    = tool_registry
        self._audit_store      = audit_store
        self._checkpoint_store = checkpoint_store

    async def execute(
        self,
        approval_grant:   ApprovalGrant,
        workflow_request: Any | None = None,  # WorkflowRequest
    ) -> ExecutionResult:
        """
        Execute an approved plan.

        Args:
            approval_grant:   The ApprovalGrant from EvaluateStage
            workflow_request: WorkflowRequest for audit context
                              (None for backwards compatibility with Phase 1)

        Returns:
            ExecutionResult with outcome, step results, cost, duration

        Raises:
            ExecutionError: unrecoverable infrastructure failure
        """
        plan       = approval_grant.approved_plan
        start_time = time.monotonic()

        # Handle Phase 1 backwards compatibility (no plan = stub behaviour)
        if plan is None or not plan.sub_tasks:
            return self._stub_result(approval_grant)

        # Build shared budget tracker for this workflow
        budget_tracker = BudgetTracker.from_grant(approval_grant)

        # Determine execution order
        ordered_tasks = self._resolve_order(plan.sub_tasks)

        # Create initial checkpoint
        checkpoint = WorkflowCheckpoint.create(
            request_id=getattr(
                workflow_request, "request_id", uuid.uuid4()
            ),
            grant_id=approval_grant.grant_id,
            pending_tasks=[t.task_id for t in ordered_tasks],
        )
        if self._checkpoint_store is not None:
            await self._checkpoint_store.save(checkpoint)

        # Write execution_started audit record
        req_id    = getattr(workflow_request, "request_id", uuid.uuid4())
        tenant_id = getattr(workflow_request, "tenant_id", "unknown")
        user_id   = getattr(workflow_request, "user_id", "unknown")

        await self._write_audit(req_id, tenant_id, user_id,
            AuditEventType.EXECUTION_STARTED, {
                "grant_id":   str(approval_grant.grant_id),
                "task_count": len(ordered_tasks),
                "max_cost":   budget_tracker.max_cost,
            }
        )

        # Execute tasks
        step_results: list[AgentResult] = []
        completed:    dict[str, AgentResult] = {}

        for task in ordered_tasks:
            # Collect dependency outputs
            task_input = {
                dep_id: (
                    completed[dep_id].output
                    if dep_id in completed else None
                )
                for dep_id in task.depends_on
            }

            # Write step_started
            await self._write_audit(req_id, tenant_id, user_id,
                AuditEventType.STEP_STARTED, {
                    "task_id":        task.task_id,
                    "agent_required": task.agent_required,
                    "tools_required": task.tools_required,
                    "estimated_cost": task.estimated_cost,
                }
            )

            # Execute the step
            result = await self._execute_step(
                task=task,
                grant=approval_grant,
                budget_tracker=budget_tracker,
                task_input=task_input,
                req_id=req_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            step_results.append(result)
            completed[task.task_id] = result

            # Record actual cost in budget tracker
            if result.cost_usd > 0:
                budget_tracker.record_actual(
                    actual_cost=result.cost_usd,
                    reserved_cost=0.0,
                )

            # Update checkpoint
            checkpoint = checkpoint.mark_task_complete(
                task_id=task.task_id,
                agent_result=result,
                cost_usd=result.cost_usd,
            )
            if self._checkpoint_store is not None:
                await self._checkpoint_store.save(checkpoint)

            # Write step_completed or step_failed
            if result.success:
                await self._write_audit(req_id, tenant_id, user_id,
                    AuditEventType.STEP_COMPLETED, {
                        "task_id":  task.task_id,
                        "cost_usd": result.cost_usd,
                        "success":  True,
                    }
                )
            else:
                await self._write_audit(req_id, tenant_id, user_id,
                    AuditEventType.STEP_FAILED, {
                        "task_id": task.task_id,
                        "error":   result.error,
                        "success": False,
                    }
                )
                # Halt on task failure
                logger.warning(
                    f"ExecutionOrchestrator: task {task.task_id} failed — "
                    f"halting execution: {result.error}"
                )
                break

        # Mark checkpoint complete and delete
        checkpoint = checkpoint.mark_completed()
        if self._checkpoint_store is not None:
            await self._checkpoint_store.save(checkpoint)
            await self._checkpoint_store.delete(checkpoint.request_id)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        all_success = all(r.success for r in step_results)

        return ExecutionResult(
            grant_id=approval_grant.grant_id,
            proposal_id=approval_grant.proposal_id,
            outcome="completed" if all_success else "partial",
            step_results=step_results,
            total_cost_usd=budget_tracker.spent,
            total_duration_ms=duration_ms,
            completed_at=datetime.now(timezone.utc),
        )

    async def _execute_step(
        self,
        task:          SubTask,
        grant:         ApprovalGrant,
        budget_tracker: BudgetTracker,
        task_input:    dict[str, Any],
        req_id:        uuid.UUID,
        tenant_id:     str,
        user_id:       str,
    ) -> AgentResult:
        """
        Execute a single sub-task.

        Instantiates the agent, builds ScopedContext, calls agent.run().
        Returns AgentResult — never raises (errors become failed results).
        """
        # If no registries configured (Phase 1 backwards compat)
        # return a stub successful result
        if self._agent_registry is None or self._tool_registry is None:
            return AgentResult.ok(
                task_id=task.task_id,
                output={"stub": True, "task": task.task_id},
                cost_usd=0.0,
            )

        # Build ScopedContext
        try:
            context = ScopedContext(
                agent_role=task.agent_required,
                grant=grant,
                tool_registry=self._tool_registry,
                task_input=task_input,
                budget_tracker=budget_tracker,
            )
        except Exception as e:
            logger.error(
                f"Failed to build ScopedContext for task {task.task_id}: {e}"
            )
            return AgentResult.fail(
                task_id=task.task_id,
                error=f"ScopedContext construction failed: {e}",
            )

        # Instantiate and run agent
        try:
            agent  = self._agent_registry.instantiate(
                role=task.agent_required,
                context=context,
            )
            result = await agent.run(task=task, context=context)
            return result
        except AgentExecutionError as e:
            logger.error(
                f"AgentExecutionError on task {task.task_id}: {e}"
            )
            return AgentResult.fail(
                task_id=task.task_id,
                error=str(e),
            )
        except Exception as e:
            logger.error(
                f"Unexpected error on task {task.task_id}: {e}"
            )
            return AgentResult.fail(
                task_id=task.task_id,
                error=f"Unexpected error: {e}",
            )

    def _resolve_order(self, tasks: list[SubTask]) -> list[SubTask]:
        """
        Determine task execution order respecting dependencies.

        Simple sequential approach for Phase 2:
        Tasks are executed in the order they appear in the plan.
        A task with depends_on is only executed after all dependencies
        appear earlier in the list.

        Raises ExecutionError if a dependency is not satisfied
        by the preceding tasks (planning error).
        """
        seen:    set[str] = set()
        ordered: list[SubTask] = []

        for task in tasks:
            # Check all dependencies appear before this task
            unmet = [d for d in task.depends_on if d not in seen]
            if unmet:
                raise ExecutionError(
                    reason=(
                        f"Task {task.task_id} depends on {unmet} "
                        f"but those tasks have not been executed yet. "
                        f"This is a planning error — check sub-task ordering."
                    ),
                    task_id=task.task_id,
                )
            ordered.append(task)
            seen.add(task.task_id)

        return ordered

    async def _write_audit(
        self,
        request_id: uuid.UUID,
        tenant_id:  str,
        user_id:    str,
        event_type: str,
        payload:    dict[str, Any],
    ) -> None:
        """Write an audit record if audit_store is configured."""
        if self._audit_store is None:
            return
        await self._audit_store.write(AuditRecord.make(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            payload=payload,
        ))

    def _stub_result(self, grant: ApprovalGrant) -> ExecutionResult:
        """Return a stub result for Phase 1 backwards compatibility."""
        logger.info(
            f"ExecutionOrchestrator: no sub-tasks in plan — "
            f"returning stub result"
        )
        return ExecutionResult(
            grant_id=grant.grant_id,
            proposal_id=grant.proposal_id,
            outcome="completed",
            step_results=[],
            total_cost_usd=0.0,
            total_duration_ms=0,
            completed_at=datetime.now(timezone.utc),
        )
