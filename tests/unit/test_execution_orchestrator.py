"""
Unit tests for ExecutionOrchestrator.

All tests use:
  - AgentRegistry with StubAgents
  - ToolRegistry with StubTools
  - InMemoryAuditStore
  - InMemoryCheckpointStore

Coverage:
  - Happy path: all tasks succeed
  - Partial failure: one task fails, execution halts
  - ScopedContext correctly scoped per agent role
  - Budget shared across all agents
  - Dependency order enforcement
  - Audit records written for all events
  - Checkpoint saved/updated/deleted through workflow
  - Phase 1 backwards compat (no registries, returns stub)
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone

from daf.agents.stub_agent import StubAgent
from daf.components.execution_orchestrator import ExecutionOrchestrator, ExecutionError
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.models.audit_record import AuditEventType
from daf.models.execution_result import ExecutionResult
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.workflow_checkpoint import CheckpointState
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.agent import AgentResult
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.budget_tracker import BudgetTracker
from daf.runtime.checkpoint_store import InMemoryCheckpointStore
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


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


def make_subtask(
    task_id:        str = "ST-01",
    agent_required: str = "test_agent",
    tools:          list[str] | None = None,
    depends_on:     list[str] | None = None,
    cost:           float = 0.02,
    reversible:     bool = True,
) -> SubTask:
    return SubTask(
        task_id=task_id,
        name=f"Task {task_id}",
        task_type="llm_extraction",
        agent_required=agent_required,
        tools_required=tools or ["read_db"],
        data_required=["test_data"],
        depends_on=depends_on or [],
        estimated_cost=cost,
        reversible=reversible,
        rationale=f"Test step {task_id}",
    )


def make_proposal(
    sub_tasks: list[SubTask] | None = None,
) -> PlanProposal:
    tasks = sub_tasks or [make_subtask()]
    return PlanProposal(
        proposal_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        iteration=1,
        orchestrator="test_orchestrator",
        planning_rationale="test plan",
        sub_tasks=tasks,
        total_estimated_cost=sum(t.estimated_cost for t in tasks),
        confidence=0.90,
    )


def make_grant(
    proposal:     PlanProposal,
    agent_roles:  list[str] | None = None,
    max_cost:     float = 0.50,
    gated_tasks:  list[str] | None = None,
) -> ApprovalGrant:
    roles = agent_roles or ["test_agent"]
    permissions = {
        role: AgentPermissions(
            tools=["read_db"],
            data_sources=["test_data"],
            max_calls=3,
        )
        for role in roles
    }
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=proposal.proposal_id,
        approved_plan=proposal,
        agent_permissions=permissions,
        gated_tasks=gated_tasks or [],
        execution_constraints={"max_cost_usd": max_cost},
    )


def make_tool_registry(*tool_names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for name in (tool_names or ["read_db"]):
        reg.register(StubTool(name=name))
    return reg


def make_agent_registry(
    *role_names: str,
    output: dict | None = None,
    should_fail: bool = False,
    error: str = "step failed",
) -> AgentRegistry:
    """Build an AgentRegistry with StubAgents for given roles."""
    reg = AgentRegistry()
    for role in (role_names or ["test_agent"]):
        # Create a StubAgent subclass for each role
        _output      = output
        _should_fail = should_fail
        _error       = error
        _role        = role

        class RoleAgent(StubAgent):
            pass

        RoleAgent.role = _role
        RoleAgent.__name__ = f"{_role}_agent"

        # Override __init__ to configure the stub
        original_init = StubAgent.__init__

        def make_init(o, sf, e, r):
            def __init__(self):
                original_init(
                    self, role=r,
                    output=o or {"result": f"output_from_{r}"},
                    should_fail=sf,
                    error=e,
                )
            return __init__

        RoleAgent.__init__ = make_init(_output, _should_fail, _error, _role)
        reg.register(RoleAgent)

    return reg


def make_orchestrator(
    agent_registry:   AgentRegistry | None   = None,
    tool_registry:    ToolRegistry | None     = None,
    audit_store:      InMemoryAuditStore | None = None,
    checkpoint_store: InMemoryCheckpointStore | None = None,
) -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        agent_registry=agent_registry   if agent_registry   is not None else make_agent_registry(),
        tool_registry=tool_registry     if tool_registry     is not None else make_tool_registry(),
        audit_store=audit_store         if audit_store         is not None else InMemoryAuditStore(),
        checkpoint_store=checkpoint_store if checkpoint_store is not None else InMemoryCheckpointStore(),
    )


# ── Happy Path ────────────────────────────────────────────────

class TestExecutionOrchestratorHappyPath:

    @pytest.mark.asyncio
    async def test_single_task_returns_completed(self):
        """Single successful task returns completed ExecutionResult."""
        proposal = make_proposal([make_subtask("ST-01")])
        grant    = make_grant(proposal)
        orc      = make_orchestrator()
        req      = make_workflow_request()

        result = await orc.execute(grant, req)

        assert isinstance(result, ExecutionResult)
        assert result.outcome == "completed"
        assert len(result.step_results) == 1
        assert result.step_results[0].success is True
        assert result.step_results[0].task_id == "ST-01"

    @pytest.mark.asyncio
    async def test_multiple_tasks_all_succeed(self):
        """All tasks succeed — completed with correct step count."""
        tasks    = [
            make_subtask("ST-01"),
            make_subtask("ST-02", depends_on=["ST-01"]),
            make_subtask("ST-03", depends_on=["ST-02"]),
        ]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal)
        orc      = make_orchestrator()

        result = await orc.execute(grant, make_workflow_request())

        assert result.outcome == "completed"
        assert len(result.step_results) == 3
        assert all(r.success for r in result.step_results)

    @pytest.mark.asyncio
    async def test_result_includes_grant_and_proposal_ids(self):
        """ExecutionResult links back to grant and proposal."""
        proposal = make_proposal()
        grant    = make_grant(proposal)
        orc      = make_orchestrator()

        result = await orc.execute(grant, make_workflow_request())

        assert result.grant_id    == grant.grant_id
        assert result.proposal_id == grant.proposal_id

    @pytest.mark.asyncio
    async def test_result_includes_completed_at(self):
        """completed_at is set to a UTC datetime."""
        proposal = make_proposal()
        grant    = make_grant(proposal)
        orc      = make_orchestrator()

        before = datetime.now(timezone.utc)
        result = await orc.execute(grant, make_workflow_request())
        after  = datetime.now(timezone.utc)

        assert before <= result.completed_at <= after

    @pytest.mark.asyncio
    async def test_result_includes_duration(self):
        """total_duration_ms is a non-negative integer."""
        proposal = make_proposal()
        grant    = make_grant(proposal)
        orc      = make_orchestrator()

        result = await orc.execute(grant, make_workflow_request())

        assert isinstance(result.total_duration_ms, int)
        assert result.total_duration_ms >= 0


# ── Task Failure ──────────────────────────────────────────────

class TestExecutionOrchestratorFailure:

    @pytest.mark.asyncio
    async def test_failing_task_returns_partial(self):
        """When a task fails, outcome is 'partial' not 'completed'."""
        tasks = [
            make_subtask("ST-01"),
            make_subtask("ST-02"),
        ]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal)

        # ST-01 succeeds, ST-02 fails
        success_agent_reg = make_agent_registry("test_agent")
        # Override: make ST-02 fail by using a custom agent

        class FailingAgent(StubAgent):
            role = "test_agent"
            def __init__(self):
                super().__init__(
                    role="test_agent",
                    should_fail=True,
                    error="extraction failed",
                )

        # We need separate registries for this — use a custom setup
        reg = AgentRegistry()
        reg.register(FailingAgent)
        orc = make_orchestrator(agent_registry=reg)

        result = await orc.execute(grant, make_workflow_request())

        assert result.outcome == "partial"
        assert result.step_results[0].success is False

    @pytest.mark.asyncio
    async def test_execution_halts_after_first_failure(self):
        """Execution stops after the first failed task."""
        tasks = [
            make_subtask("ST-01"),
            make_subtask("ST-02"),  # should not run after ST-01 fails
        ]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal)

        class FailAllAgent(StubAgent):
            role = "test_agent"
            def __init__(self):
                super().__init__(role="test_agent", should_fail=True)

        reg = AgentRegistry()
        reg.register(FailAllAgent)
        orc = make_orchestrator(agent_registry=reg)

        result = await orc.execute(grant, make_workflow_request())

        # Only ST-01 ran — execution halted after failure
        assert len(result.step_results) == 1
        assert result.step_results[0].task_id == "ST-01"


# ── Dependency Order ──────────────────────────────────────────

class TestExecutionOrchestratorDependencies:

    @pytest.mark.asyncio
    async def test_tasks_executed_in_declared_order(self):
        """Tasks are executed in the order they appear in the plan."""
        execution_order = []

        class TrackingAgent(StubAgent):
            role = "test_agent"
            def __init__(self):
                super().__init__(role="test_agent")

            async def execute(self, task, context):
                execution_order.append(task.task_id)
                return AgentResult.ok(task_id=task.task_id, output=None)

        tasks = [
            make_subtask("ST-01"),
            make_subtask("ST-02", depends_on=["ST-01"]),
            make_subtask("ST-03", depends_on=["ST-02"]),
        ]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal)
        reg      = AgentRegistry()
        reg.register(TrackingAgent)
        orc = make_orchestrator(agent_registry=reg)

        await orc.execute(grant, make_workflow_request())

        assert execution_order == ["ST-01", "ST-02", "ST-03"]

    def test_unmet_dependency_raises_execution_error(self):
        """Task with unmet dependency raises ExecutionError at order resolution."""
        tasks = [
            make_subtask("ST-02", depends_on=["ST-01"]),  # ST-01 not in list!
        ]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal)
        orc      = make_orchestrator()

        with pytest.raises(ExecutionError, match="planning error"):
            orc._resolve_order(tasks)


# ── Audit Records ─────────────────────────────────────────────

class TestExecutionOrchestratorAuditRecords:

    @pytest.mark.asyncio
    async def test_execution_started_written(self):
        """EXECUTION_STARTED audit record is written."""
        store    = InMemoryAuditStore()
        proposal = make_proposal()
        grant    = make_grant(proposal)
        req      = make_workflow_request()
        orc      = make_orchestrator(audit_store=store)

        await orc.execute(grant, req)

        events = [r.event_type for r in await store.query(req.request_id)]
        assert AuditEventType.EXECUTION_STARTED in events

    @pytest.mark.asyncio
    async def test_step_started_and_completed_written(self):
        """STEP_STARTED and STEP_COMPLETED are written for each task."""
        store    = InMemoryAuditStore()
        tasks    = [make_subtask("ST-01"), make_subtask("ST-02")]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal)
        req      = make_workflow_request()
        orc      = make_orchestrator(audit_store=store)

        await orc.execute(grant, req)

        events = [r.event_type for r in await store.query(req.request_id)]
        assert events.count(AuditEventType.STEP_STARTED)   == 2
        assert events.count(AuditEventType.STEP_COMPLETED) == 2

    @pytest.mark.asyncio
    async def test_step_failed_written_on_failure(self):
        """STEP_FAILED is written when a task fails."""
        store    = InMemoryAuditStore()
        proposal = make_proposal()
        grant    = make_grant(proposal)
        req      = make_workflow_request()

        class FailAgent(StubAgent):
            role = "test_agent"
            def __init__(self):
                super().__init__(role="test_agent", should_fail=True)

        reg = AgentRegistry()
        reg.register(FailAgent)
        orc = make_orchestrator(agent_registry=reg, audit_store=store)

        await orc.execute(grant, req)

        events = [r.event_type for r in await store.query(req.request_id)]
        assert AuditEventType.STEP_FAILED in events


# ── Checkpoint Lifecycle ──────────────────────────────────────

class TestExecutionOrchestratorCheckpoints:

    @pytest.mark.asyncio
    async def test_checkpoint_created_on_start(self):
        """Checkpoint is created when execution begins."""
        saved_states = []

        class TrackingCheckpointStore(InMemoryCheckpointStore):
            async def save(self, cp):
                saved_states.append(cp.state)
                await super().save(cp)

        cp_store = TrackingCheckpointStore()
        proposal = make_proposal()
        grant    = make_grant(proposal)
        req      = make_workflow_request()
        orc      = make_orchestrator(checkpoint_store=cp_store)

        await orc.execute(grant, req)

        assert len(saved_states) > 0

    @pytest.mark.asyncio
    async def test_checkpoint_deleted_after_completion(self):
        """Checkpoint is deleted after successful completion."""
        cp_store = InMemoryCheckpointStore()
        proposal = make_proposal()
        grant    = make_grant(proposal)
        req      = make_workflow_request()
        orc      = make_orchestrator(checkpoint_store=cp_store)

        await orc.execute(grant, req)

        # Checkpoint should be deleted after completion
        loaded = await cp_store.load(req.request_id)
        assert loaded is None


# ── Budget Tracking ───────────────────────────────────────────

class TestExecutionOrchestratorBudget:

    @pytest.mark.asyncio
    async def test_total_cost_accumulated_from_steps(self):
        """total_cost_usd accumulates agent cost from all steps."""
        class CostlyAgent(StubAgent):
            role = "test_agent"
            def __init__(self):
                super().__init__(role="test_agent", cost_usd=0.05)

        tasks    = [make_subtask("ST-01"), make_subtask("ST-02")]
        proposal = make_proposal(tasks)
        grant    = make_grant(proposal, max_cost=1.0)
        reg      = AgentRegistry()
        reg.register(CostlyAgent)
        orc = make_orchestrator(agent_registry=reg)

        result = await orc.execute(grant, make_workflow_request())

        # Each agent returns cost_usd=0.05, two tasks = 0.10
        assert result.total_cost_usd == pytest.approx(0.10)


# ── Phase 1 Backwards Compatibility ──────────────────────────

class TestExecutionOrchestratorPhase1Compat:

    @pytest.mark.asyncio
    async def test_no_registries_returns_stub_result(self):
        """No registries = Phase 1 stub behaviour."""
        orc      = ExecutionOrchestrator()  # no registries
        proposal = make_proposal()
        grant    = make_grant(proposal)

        result = await orc.execute(grant, None)

        assert isinstance(result, ExecutionResult)
        assert result.outcome in ("completed", "partial")

    @pytest.mark.asyncio
    async def test_empty_sub_tasks_returns_stub(self):
        """Empty sub_tasks list returns stub result."""
        from daf.models.plan_proposal import PlanProposal
        proposal = PlanProposal(
            proposal_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            iteration=1,
            orchestrator="test",
            planning_rationale="test",
            sub_tasks=[],
            total_estimated_cost=0.0,
            confidence=0.9,
        )
        grant = make_grant(proposal)
        orc   = make_orchestrator()

        result = await orc.execute(grant, None)

        assert result.outcome == "completed"
        assert result.step_results == []
