"""
Adversarial tests — Layer 4: Execution Invariants.

These tests verify that execution constraints cannot be bypassed
through agent result manipulation, HITL response forgery,
or direct registry manipulation.

ALL TESTS MUST PASS. Any failure is a security regression.
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from daf.agents.stub_agent import StubAgent
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.models.human_review import HumanReviewResponse, TaskDecision
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.runtime.agent import AgentResult, AgentExecutionError
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.scoped_context import ScopedContext
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


# ── Fixtures ─────────────────────────────────────────────────

def make_grant(
    agent_role: str = "reader",
    tools:      list[str] = None,
) -> ApprovalGrant:
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        approved_plan=None,
        agent_permissions={
            agent_role: AgentPermissions(
                tools=tools or ["read_db"],
                data_sources=["test_data"],
                access_level="read_only",
                max_calls=3,
            )
        },
        gated_tasks=[],
        execution_constraints={"max_cost_usd": 0.50},
    )


def make_registry(*tools: str) -> ToolRegistry:
    reg = ToolRegistry()
    for t in (tools or ["read_db"]):
        reg.register(StubTool(t))
    return reg


# ── AgentResult Cannot Override Policy ───────────────────────

class TestAgentResultCannotOverridePolicy:
    """
    An agent's output cannot influence policy decisions.
    Policy is evaluated before execution — not during.
    """

    @pytest.mark.asyncio
    async def test_agent_failure_does_not_affect_other_agents(self):
        """
        A failed agent result does not affect other agents'
        ScopedContexts or permissions.

        SECURITY: Agent failures must be isolated at step boundary.
        """
        # Agent A fails
        class FailAgent(StubAgent):
            role = "reader"
            def __init__(self):
                super().__init__(role="reader", should_fail=True)

        reg    = AgentRegistry()
        reg.register(FailAgent)
        grant  = make_grant("reader", ["read_db"])
        treg   = make_registry("read_db")
        ctx_a  = ScopedContext("reader", grant, treg)

        agent_a = reg.instantiate("reader", ctx_a)
        task    = SubTask(
            task_id="ST-01", name="test",
            task_type="llm_extraction",
            agent_required="reader",
            tools_required=["read_db"],
            data_required=[],
            estimated_cost=0.01,
            reversible=True,
            rationale="test",
        )

        result_a = await agent_a.run(task=task, context=ctx_a)
        assert result_a.success is False

        # Agent B should still work with its own context (not affected by A)
        ctx_b   = ScopedContext("reader", grant, treg)
        assert ctx_b.tools.has("read_db")  # permissions unchanged

    def test_scoped_context_permissions_fixed_at_instantiation(self):
        """
        Agent permissions are fixed when ScopedContext is created.
        An agent cannot request additional permissions at runtime.

        SECURITY: This is the core execution invariant.
        """
        grant  = make_grant("reader", ["read_db"])
        treg   = make_registry("read_db", "write_db", "admin_tool")
        ctx    = ScopedContext("reader", grant, treg)

        # Only read_db is permitted — write_db and admin_tool do not exist
        from daf.runtime.tool import ToolNotFoundError
        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("write_db")
        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("admin_tool")

        # Confirm read_db still works
        assert ctx.tools.has("read_db")


# ── HITL Response Integrity ───────────────────────────────────

class TestHITLResponseIntegrity:
    """
    HITL responses are frozen (immutable) after creation.
    A forged or modified approval cannot bypass the HITL gate.
    """

    def test_human_review_response_is_frozen(self):
        """
        HumanReviewResponse is a frozen Pydantic model.
        Attempting to modify it raises an exception.

        SECURITY: A forged response approval cannot be injected
        by modifying an existing rejection.
        """
        response = HumanReviewResponse.rejected_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
            reason="Not authorised",
        )

        assert response.has_rejections() is True
        # Attempt to change top-level frozen field
        with pytest.raises(Exception):
            response.reviewer_id = "attacker"  # type: ignore
        assert response.reviewer_id == "alice"  # unchanged

    def test_forged_approval_response_detected(self):
        """
        A response claiming all_approved for tasks not in the request
        returns empty approved list for those tasks.

        SECURITY: decision_for() returns None for unknown task_ids.
        """
        response = HumanReviewResponse.approved_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
        )

        # ST-99 was not in the review request
        decision = response.decision_for("ST-99")
        assert decision is None

    def test_timeout_response_cannot_be_changed_to_approved(self):
        """
        A timeout response is frozen and cannot be mutated to approved.
        """
        response = HumanReviewResponse.timeout_response(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            task_ids=["ST-03"],
        )
        assert response.timed_out   is True
        assert response.has_rejections() is True

        # Cannot mutate
        with pytest.raises(Exception):
            response.timed_out = False  # type: ignore


# ── AgentRegistry Cannot Be Poisoned ─────────────────────────

class TestAgentRegistryPoisoning:
    """
    The AgentRegistry maps roles to classes.
    After instantiation, the agent cannot expand its permissions.
    """

    def test_registering_duplicate_role_raises(self):
        """
        Registering a second agent class for the same role raises.
        Silent overwriting would allow a poisoned agent to replace
        a legitimate one.

        SECURITY: Duplicate registration protection is a safety gate.
        """
        from daf.runtime.agent import AgentAlreadyRegisteredError

        reg = AgentRegistry()

        class AgentA(StubAgent):
            role = "target_role"
            def __init__(self):
                super().__init__(role="target_role")

        class AgentB(StubAgent):
            role = "target_role"
            def __init__(self):
                super().__init__(role="target_role")

        reg.register(AgentA)
        with pytest.raises(AgentAlreadyRegisteredError):
            reg.register(AgentB)

    def test_non_agent_class_registration_raises(self):
        """
        Registering a non-BaseAgent class raises TypeError.
        A malicious callable cannot be registered as an agent.
        """
        reg = AgentRegistry()
        with pytest.raises(TypeError):
            reg.register(lambda: None)  # type: ignore

    def test_instantiate_unknown_role_raises(self):
        """
        Instantiating an unknown role raises AgentNotFoundError.
        It does not silently return None or a default agent.

        SECURITY: Silent failures here could allow privilege escalation.
        """
        from daf.runtime.agent import AgentNotFoundError
        reg = AgentRegistry()
        with pytest.raises(AgentNotFoundError):
            reg.instantiate("admin_agent", None)


# ── Audit Record Integrity ────────────────────────────────────

class TestAuditRecordIntegrity:
    """
    Audit records are immutable after creation.
    """

    def test_audit_record_is_frozen(self):
        """
        AuditRecord is a frozen Pydantic model.
        Attempting to modify it after creation raises.

        SECURITY: Immutable audit records are the foundation
        of the trustworthy audit trail.
        """
        from daf.models.audit_record import AuditRecord, AuditEventType

        record = AuditRecord.make(
            request_id=uuid.uuid4(),
            tenant_id="test",
            user_id="user",
            event_type=AuditEventType.WORKFLOW_STARTED,
            payload={"task": "original task"},
        )

        with pytest.raises(Exception):
            record.event_type = "modified_event"  # type: ignore

    @pytest.mark.asyncio
    async def test_duplicate_audit_id_rejected(self):
        """
        Writing two records with the same audit_id raises AuditStoreError.
        The second write cannot silently replace the first.

        SECURITY: Preventing silent overwrites ensures the audit trail
        cannot be altered after the fact.
        """
        from daf.models.audit_record import AuditRecord, AuditEventType
        from daf.runtime.audit_store import InMemoryAuditStore, AuditStoreError

        store  = InMemoryAuditStore()
        record = AuditRecord.make(
            request_id=uuid.uuid4(),
            tenant_id="test", user_id="user",
            event_type=AuditEventType.WORKFLOW_STARTED,
        )

        await store.write(record)  # first write succeeds

        with pytest.raises(AuditStoreError, match="already exists"):
            await store.write(record)  # duplicate fails
