"""
Unit tests for ScopedContext.

Adversarial tests (security properties) are in tests/adversarial/.
These unit tests cover:
  - Construction with various permission configurations
  - Tool access through ScopedToolRegistry
  - task_input handling
  - permitted_data_sources property
  - budget property (None until Step 9)
  - Logging and repr
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
    registry = ToolRegistry()
    for name in tool_names:
        registry.register(StubTool(name=name, idempotent=True))
    return registry


def make_grant(
    agent_role: str,
    tools: list[str],
    data_sources: list[str] | None = None,
    max_calls: int = 3,
) -> ApprovalGrant:
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


# ── Construction ─────────────────────────────────────────────

class TestScopedContextConstruction:

    def test_basic_construction(self):
        """ScopedContext constructs without error with valid inputs."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)
        assert ctx.role == "reader"

    def test_multiple_permitted_tools(self):
        """All permitted tools are accessible."""
        registry = make_registry("read_db", "read_file", "llm_extraction")
        grant    = make_grant("analyst",
                              tools=["read_db", "read_file", "llm_extraction"])
        ctx      = ScopedContext("analyst", grant, registry)

        assert len(ctx.tools) == 3
        assert ctx.tools.get("read_db").name == "read_db"
        assert ctx.tools.get("read_file").name == "read_file"
        assert ctx.tools.get("llm_extraction").name == "llm_extraction"

    def test_no_permitted_tools(self):
        """Agent with no tools has empty ScopedToolRegistry."""
        registry = make_registry("read_db")
        grant    = make_grant("locked", tools=[])
        ctx      = ScopedContext("locked", grant, registry)
        assert len(ctx.tools) == 0

    def test_invalid_role_raises_value_error(self):
        """ValueError raised when role not in grant."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        with pytest.raises(ValueError, match="not found in ApprovalGrant"):
            ScopedContext("nonexistent_role", grant, registry)

    def test_permitted_tool_not_in_registry_raises(self):
        """ToolNotFoundError at construction when tool not registered."""
        registry = make_registry("read_db")   # only read_db registered
        grant    = make_grant("reader", tools=["read_db", "unregistered_tool"])
        with pytest.raises(ToolNotFoundError, match="unregistered_tool"):
            ScopedContext("reader", grant, registry)


# ── Tool Access ───────────────────────────────────────────────

class TestScopedContextToolAccess:

    def test_get_permitted_tool(self):
        """Permitted tool is retrievable and has correct name."""
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        tool = ctx.tools.get("read_db")
        assert tool.name == "read_db"

    def test_get_unpermitted_tool_raises(self):
        """Unpermitted tool raises ToolNotFoundError."""
        registry = make_registry("read_db", "write_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        with pytest.raises(ToolNotFoundError):
            ctx.tools.get("write_db")

    @pytest.mark.asyncio
    async def test_permitted_tool_is_callable(self):
        """Tool retrieved from ScopedContext can be called."""
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        tool   = ctx.tools.get("read_db")
        result = await tool.call(query="SELECT 1")
        # StubTool returns success by default
        assert result.success is True

    def test_tools_names_returns_permitted_only(self):
        """names() returns only the permitted subset."""
        registry = make_registry("read_db", "write_db", "delete_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        assert ctx.tools.names() == ["read_db"]


# ── task_input ────────────────────────────────────────────────

class TestScopedContextTaskInput:

    def test_task_input_default_empty(self):
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        assert ctx.task_input == {}

    def test_task_input_accessible(self):
        """Provided task_input is accessible."""
        registry   = make_registry("read_db")
        task_input = {"ST-01_output": {"rows": [1, 2, 3]}, "count": 3}
        ctx        = ScopedContext("reader",
                                   make_grant("reader", tools=["read_db"]),
                                   registry,
                                   task_input=task_input)
        assert ctx.task_input["ST-01_output"] == {"rows": [1, 2, 3]}
        assert ctx.task_input["count"] == 3

    def test_task_input_is_independent_copy(self):
        """task_input is a copy — mutating original does not affect context."""
        registry   = make_registry("read_db")
        original   = {"key": "original"}
        ctx        = ScopedContext("reader",
                                   make_grant("reader", tools=["read_db"]),
                                   registry,
                                   task_input=original)
        original["key"] = "mutated"
        assert ctx.task_input["key"] == "original"


# ── Metadata and Properties ───────────────────────────────────

class TestScopedContextProperties:

    def test_role_reflects_agent_role(self):
        registry = make_registry("read_db")
        ctx      = ScopedContext("document_reader",
                                 make_grant("document_reader", tools=["read_db"]),
                                 registry)
        assert ctx.role == "document_reader"

    def test_max_calls_from_permissions(self):
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"],
                                            max_calls=7),
                                 registry)
        assert ctx.max_calls == 7

    def test_permitted_data_sources_property(self):
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"],
                                            data_sources=["docs", "reports"]),
                                 registry)
        assert "docs" in ctx.permitted_data_sources
        assert "reports" in ctx.permitted_data_sources

    def test_budget_is_none_before_step9(self):
        """budget property returns None until BudgetTracker is wired (Step 9)."""
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        assert ctx.budget is None

    def test_repr_includes_key_info(self):
        registry = make_registry("read_db")
        ctx      = ScopedContext("reader",
                                 make_grant("reader", tools=["read_db"]),
                                 registry)
        r = repr(ctx)
        assert "reader" in r
        assert "read_db" in r
