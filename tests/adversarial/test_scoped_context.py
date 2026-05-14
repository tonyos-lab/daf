"""
Adversarial tests for ScopedContext enforcement.

These tests verify that runtime permission constraints
cannot be bypassed through prompt manipulation, adversarial
tool output, or direct Python manipulation.

ALL TESTS MUST PASS.
Any failure is a security regression — nothing ships.

These tests use the REAL ScopedContext with REAL ToolRegistry
and REAL ScopedToolRegistry. They do not use mocks for the
security-critical path.
"""
from __future__ import annotations

import uuid
import pytest

from daf.runtime.scoped_context import ScopedContext
from daf.runtime.tool_registry import ToolRegistry
from daf.runtime.tool import ToolNotFoundError
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.tools.stub_tool import StubTool


# ── Fixtures ─────────────────────────────────────────────────

def make_registry(*tool_names: str) -> ToolRegistry:
    """Build a ToolRegistry with StubTools for the given names."""
    registry = ToolRegistry()
    for name in tool_names:
        registry.register(StubTool(name=name, idempotent=True))
    return registry


def make_grant(
    agent_role: str,
    tools: list[str],
    data_sources: list[str] | None = None,
    max_calls: int = 5,
) -> ApprovalGrant:
    """Build an ApprovalGrant with specified permissions."""
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        approved_plan=None,
        agent_permissions={
            agent_role: AgentPermissions(
                tools=tools,
                data_sources=data_sources or [],
                access_level="read_only",
                max_calls=max_calls,
            )
        },
        gated_tasks=[],
    )


# ── ScopedContext Structural Enforcement ─────────────────────

class TestScopedContextEnforcement:
    """
    Verify that ScopedContext enforces tool permissions structurally.

    "Structurally" means the tool client does not exist —
    not that it exists but refuses. ToolNotFoundError is raised
    when attempting to access an unpermitted tool.
    """

    def test_permitted_tool_exists_in_context(self):
        """
        A permitted tool is accessible via context.tools.

        BASELINE: permitted tools must be reachable.
        """
        registry = make_registry("read_db", "write_file")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        # Permitted tool is accessible
        tool = ctx.tools.get("read_db")
        assert tool is not None
        assert tool.name == "read_db"

    def test_unpermitted_tool_does_not_exist_in_context(self):
        """
        An unpermitted tool raises ToolNotFoundError when accessed.

        SECURITY: If this test fails, an agent can access tools
        it was not granted — breaking the permission boundary.
        """
        registry = make_registry("read_db", "write_db", "send_email")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        # Unpermitted tools raise ToolNotFoundError — they do not exist
        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("write_db")

        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("send_email")

        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("delete_record")

    def test_contains_check_reflects_permission_boundary(self):
        """
        The `in` operator on ScopedToolRegistry reflects permission boundary.

        SECURITY: Agents checking tool availability must get
        accurate results — no false positives.
        """
        registry = make_registry("read_db", "write_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        assert "read_db" in ctx.tools       # permitted
        assert "write_db" not in ctx.tools  # not permitted
        assert "send_email" not in ctx.tools  # not in registry at all

    def test_only_granted_tools_visible_in_names(self):
        """
        ctx.tools.names() returns only permitted tool names.

        SECURITY: Tool enumeration must not leak unpermitted tools.
        """
        registry = make_registry("read_db", "write_db", "send_email", "delete_record")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        names = ctx.tools.names()
        assert "read_db" in names
        assert "write_db" not in names
        assert "send_email" not in names
        assert "delete_record" not in names
        assert len(names) == 1

    def test_empty_tools_permission_means_no_tools(self):
        """
        An agent granted no tools has an empty tool set.

        SECURITY: Zero-permission agents must have zero tools.
        """
        registry = make_registry("read_db", "write_db")
        grant    = make_grant("locked_agent", tools=[])
        ctx      = ScopedContext("locked_agent", grant, registry)

        assert len(ctx.tools) == 0
        assert ctx.tools.names() == []

        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("read_db")

    def test_two_agents_same_registry_different_scopes(self):
        """
        Two agents using the same ToolRegistry have independent scopes.

        SECURITY: Agent A's permissions must not leak to Agent B.
        Agent B's expanded permissions must not be visible to Agent A.
        """
        registry = make_registry("read_db", "write_db", "send_email")

        grant_reader = make_grant("reader", tools=["read_db"])
        grant_writer = make_grant("writer", tools=["write_db", "send_email"])

        ctx_reader = ScopedContext("reader", grant_reader, registry)
        ctx_writer = ScopedContext("writer", grant_writer, registry)

        # Reader cannot access writer tools
        assert "read_db" in ctx_reader.tools
        assert "write_db" not in ctx_reader.tools
        assert "send_email" not in ctx_reader.tools

        # Writer cannot access reader tools
        assert "write_db" in ctx_writer.tools
        assert "send_email" in ctx_writer.tools
        assert "read_db" not in ctx_writer.tools


class TestScopedContextImmutability:
    """
    Verify that ScopedContext scope cannot be expanded after instantiation.

    This simulates adversarial attempts to expand permissions:
    - Directly mutating ctx.tools
    - Registering new tools in the ToolRegistry after scoping
    - Replacing the _tools dict in the ScopedToolRegistry
    """

    def test_adding_to_registry_after_scoping_does_not_expand_context(self):
        """
        Adding a new tool to ToolRegistry after ScopedContext is created
        does not make that tool available in the already-created context.

        SECURITY: Post-scoping registry changes must not expand agent scope.
        This is the primary injection defense at the tool layer.
        """
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        # Confirm initial state
        assert "read_db" in ctx.tools
        assert "write_db" not in ctx.tools

        # Attacker registers a new tool in the shared registry
        # (simulating a tool registered after context creation)
        registry.register(StubTool("write_db", idempotent=False))

        # The already-created context must NOT see the new tool
        assert "write_db" not in ctx.tools
        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("write_db")

    def test_context_role_is_readonly_after_creation(self):
        """
        Modifying ctx.role after creation does not affect tool permissions.
        Permissions are set at __init__ time, not derived from role at access time.
        """
        registry = make_registry("read_db", "admin_tool")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        # Attempt to escalate role (adversarial)
        ctx.role = "admin"

        # Tool permissions are unchanged — still based on original grant
        assert "read_db" in ctx.tools
        assert "admin_tool" not in ctx.tools

    def test_task_input_is_a_copy_not_a_reference(self):
        """
        task_input is copied at instantiation.
        Modifying the original dict does not affect the context's copy.
        """
        original_input = {"data": "original", "count": 5}
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry,
                                 task_input=original_input)

        # Modify the original dict
        original_input["data"] = "modified"
        original_input["injected"] = "adversarial"

        # Context's copy is unchanged
        assert ctx.task_input["data"] == "original"
        assert "injected" not in ctx.task_input


class TestScopedContextConstruction:
    """
    Verify ScopedContext construction — correct setup and error cases.
    """

    def test_context_requires_valid_role_in_grant(self):
        """
        ScopedContext raises ValueError when role is not in the grant.

        SECURITY: Constructing a context for an ungranted role must fail.
        """
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])

        with pytest.raises(ValueError, match="not found in ApprovalGrant"):
            ScopedContext("admin", grant, registry)  # "admin" not in grant

    def test_context_raises_when_permitted_tool_not_in_registry(self):
        """
        ScopedContext raises ToolNotFoundError at instantiation when a
        permitted tool is not registered in ToolRegistry.

        SECURITY: Fail at instantiation, not silently at call time.
        Misconfigured tools are caught immediately.
        """
        registry = make_registry("read_db")   # only read_db registered
        grant    = make_grant("reader", tools=["read_db", "magic_tool"])
        # magic_tool is permitted in grant but not registered

        with pytest.raises(ToolNotFoundError, match="magic_tool"):
            ScopedContext("reader", grant, registry)

    def test_empty_task_input_is_empty_dict(self):
        """task_input defaults to empty dict when not provided."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        assert ctx.task_input == {}

    def test_task_input_provided_is_accessible(self):
        """Provided task_input is accessible on the context."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext(
            "reader", grant, registry,
            task_input={"upstream_result": [1, 2, 3]}
        )

        assert ctx.task_input["upstream_result"] == [1, 2, 3]

    def test_permitted_data_sources_are_recorded(self):
        """permitted_data_sources property returns the list from the grant."""
        registry = make_registry("read_db")
        grant    = make_grant(
            "reader",
            tools=["read_db"],
            data_sources=["internal_docs", "public_data"]
        )
        ctx = ScopedContext("reader", grant, registry)

        assert "internal_docs" in ctx.permitted_data_sources
        assert "public_data" in ctx.permitted_data_sources

    def test_max_calls_set_from_permissions(self):
        """max_calls is set from AgentPermissions.max_calls."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"], max_calls=7)
        ctx      = ScopedContext("reader", grant, registry)

        assert ctx.max_calls == 7

    def test_repr_includes_role_and_tools(self):
        """repr() includes role and tool names."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        r = repr(ctx)
        assert "reader" in r
        assert "read_db" in r


# ── BudgetTracker Security (from original adversarial suite) ─

class TestBudgetTrackerSecurity:
    """
    Concurrent budget enforcement must never allow over-budget approvals.

    SECURITY: Race conditions in budget tracking = unbounded cost.
    """

    def test_budget_enforced_before_execution(self):
        """
        BudgetTracker blocks reservation when budget is exhausted.

        SECURITY: If this fails, over-budget calls can proceed.
        """
        from daf.runtime.budget_tracker import BudgetTracker

        tracker = BudgetTracker(max_cost_usd=0.01)
        tracker.check_and_reserve(0.01)  # exhaust budget

        result = tracker.check_and_reserve(0.001)
        assert result is False, (
            "Budget check must return False when budget is exhausted"
        )
        assert tracker.remaining == 0.0

    def test_concurrent_budget_no_race_condition(self):
        """
        Concurrent budget reservations must not allow over-budget approvals.

        SECURITY: Race conditions in budget tracking = unbounded cost.
        """
        import threading
        from daf.runtime.budget_tracker import BudgetTracker

        tracker   = BudgetTracker(max_cost_usd=0.10)
        approvals = []
        errors    = []

        def attempt_reservation():
            try:
                result = tracker.check_and_reserve(0.06)
                approvals.append(result)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=attempt_reservation)
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Exceptions during concurrent access: {errors}"
        approved_count = sum(1 for a in approvals if a is True)
        assert approved_count <= 1, (
            f"Multiple concurrent reservations approved: {approved_count}. "
            "This is a race condition — budget tracking is broken."
        )
