"""
Unit tests for BaseTool, ToolResult, ToolRegistry,
ScopedToolRegistry, and StubTool.

Coverage:
  - ToolResult.ok() and .fail() constructors
  - BaseTool subclass enforcement (name + idempotent required)
  - ToolRegistry register, get, has, names, scoped
  - ToolRegistry error cases (not found, duplicate)
  - ScopedToolRegistry immutability and access
  - StubTool call, failure, call history, reset
"""
from __future__ import annotations

import pytest

from daf.runtime.tool import (
    BaseTool, ToolResult, ToolNotFoundError, ToolCallError,
)
from daf.runtime.tool_registry import (
    ToolRegistry, ScopedToolRegistry, ToolAlreadyRegisteredError,
)
from daf.tools.stub_tool import StubTool


# ── ToolResult ───────────────────────────────────────────────

class TestToolResult:

    def test_ok_sets_success_true(self):
        result = ToolResult.ok(output={"rows": [1, 2, 3]})
        assert result.success is True
        assert result.output == {"rows": [1, 2, 3]}
        assert result.error is None

    def test_fail_sets_success_false(self):
        result = ToolResult.fail(error="DB unavailable")
        assert result.success is False
        assert result.error == "DB unavailable"
        assert result.output is None

    def test_ok_accepts_metadata(self):
        result = ToolResult.ok(output="data", source="test_db", rows=5)
        assert result.metadata["source"] == "test_db"
        assert result.metadata["rows"] == 5

    def test_fail_accepts_metadata(self):
        result = ToolResult.fail(error="timeout", latency_ms=5000)
        assert result.metadata["latency_ms"] == 5000

    def test_ok_with_none_output(self):
        """None output is valid for tools that return nothing."""
        result = ToolResult.ok(output=None)
        assert result.success is True
        assert result.output is None

    def test_ok_with_various_output_types(self):
        """ToolResult accepts any output type."""
        assert ToolResult.ok(output=42).output == 42
        assert ToolResult.ok(output="text").output == "text"
        assert ToolResult.ok(output=[1, 2]).output == [1, 2]
        assert ToolResult.ok(output={"k": "v"}).output == {"k": "v"}


# ── BaseTool Enforcement ─────────────────────────────────────

class TestBaseToolEnforcement:
    """BaseTool subclass must declare name and idempotent."""

    def test_concrete_subclass_without_name_raises(self):
        """Concrete subclass missing name raises TypeError."""
        with pytest.raises(TypeError, match="name"):
            class BadTool(BaseTool):
                idempotent = True
                async def call(self, **kwargs): ...

    def test_concrete_subclass_without_idempotent_raises(self):
        """Concrete subclass missing idempotent raises TypeError."""
        with pytest.raises(TypeError, match="idempotent"):
            class BadTool(BaseTool):
                name = "bad_tool"
                async def call(self, **kwargs): ...

    def test_concrete_subclass_with_both_attributes_ok(self):
        """Concrete subclass with both attributes constructs without error."""
        class GoodTool(BaseTool):
            name       = "good_tool"
            idempotent = True
            async def call(self, **kwargs): return ToolResult.ok(output=None)

        tool = GoodTool()
        assert tool.name == "good_tool"
        assert tool.idempotent is True

    def test_abstract_subclass_not_enforced(self):
        """Abstract intermediate classes are not enforced."""
        class AbstractTool(BaseTool):
            """Intermediate abstract — no name/idempotent required."""
            pass
        # No error raised for abstract intermediaries

    def test_basettool_repr(self):
        """BaseTool __repr__ includes name and idempotent."""
        tool = StubTool("test_tool", idempotent=False)
        assert "test_tool" in repr(tool)
        assert "False" in repr(tool)


# ── StubTool ─────────────────────────────────────────────────

class TestStubTool:

    @pytest.mark.asyncio
    async def test_call_returns_configured_output(self):
        """StubTool returns the configured output on success."""
        tool = StubTool("read_db", output={"rows": [{"id": 1}]})
        result = await tool.call(query="SELECT 1")
        assert result.success is True
        assert result.output == {"rows": [{"id": 1}]}

    @pytest.mark.asyncio
    async def test_call_returns_none_output_by_default(self):
        """Default output is None."""
        tool = StubTool("read_db")
        result = await tool.call()
        assert result.success is True
        assert result.output is None

    @pytest.mark.asyncio
    async def test_call_fails_when_configured(self):
        """StubTool returns failure when should_fail=True."""
        tool = StubTool("write_db", should_fail=True, error="DB locked")
        result = await tool.call(data={"key": "value"})
        assert result.success is False
        assert result.error == "DB locked"

    @pytest.mark.asyncio
    async def test_call_records_history(self):
        """Every call is recorded in self.calls."""
        tool = StubTool("read_db")
        await tool.call(query="SELECT 1")
        await tool.call(query="SELECT 2")
        assert len(tool.calls) == 2
        assert tool.calls[0]["query"] == "SELECT 1"
        assert tool.calls[1]["query"] == "SELECT 2"

    @pytest.mark.asyncio
    async def test_reset_clears_call_history(self):
        """reset() clears the call history."""
        tool = StubTool("read_db")
        await tool.call()
        await tool.call()
        assert len(tool.calls) == 2
        tool.reset()
        assert len(tool.calls) == 0

    @pytest.mark.asyncio
    async def test_multiple_calls_after_reset(self):
        """After reset, call numbering restarts."""
        tool = StubTool("read_db")
        await tool.call(q="first")
        tool.reset()
        await tool.call(q="second")
        assert len(tool.calls) == 1
        assert tool.calls[0]["q"] == "second"

    def test_stub_tool_name_and_idempotent_set(self):
        """Constructor sets name and idempotent correctly."""
        tool = StubTool("write_file", idempotent=False)
        assert tool.name == "write_file"
        assert tool.idempotent is False

    def test_stub_tool_repr(self):
        """StubTool repr includes name and call count."""
        tool = StubTool("test_tool")
        assert "test_tool" in repr(tool)
        assert "0" in repr(tool)  # 0 calls


# ── ToolRegistry ─────────────────────────────────────────────

class TestToolRegistry:

    def make_registry_with_tools(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(StubTool("read_db", idempotent=True))
        registry.register(StubTool("write_file", idempotent=False))
        return registry

    def test_register_and_get(self):
        """Registered tool can be retrieved by name."""
        registry = ToolRegistry()
        tool = StubTool("read_db")
        registry.register(tool)
        retrieved = registry.get("read_db")
        assert retrieved is tool

    def test_get_unregistered_raises_tool_not_found(self):
        """get() raises ToolNotFoundError for unregistered tool."""
        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError) as exc_info:
            registry.get("nonexistent_tool")
        assert "nonexistent_tool" in str(exc_info.value)

    def test_duplicate_registration_raises(self):
        """Registering the same name twice raises ToolAlreadyRegisteredError."""
        registry = ToolRegistry()
        registry.register(StubTool("read_db"))
        with pytest.raises(ToolAlreadyRegisteredError) as exc_info:
            registry.register(StubTool("read_db"))
        assert "read_db" in str(exc_info.value)

    def test_replace_allows_override(self):
        """replace=True allows overriding an existing registration."""
        registry = ToolRegistry()
        tool_a = StubTool("read_db", output="original")
        tool_b = StubTool("read_db", output="replacement")
        registry.register(tool_a)
        registry.register(tool_b, replace=True)
        assert registry.get("read_db") is tool_b

    def test_has_returns_true_for_registered(self):
        """has() returns True for registered tool."""
        registry = self.make_registry_with_tools()
        assert registry.has("read_db") is True

    def test_has_returns_false_for_unregistered(self):
        """has() returns False for unregistered tool."""
        registry = self.make_registry_with_tools()
        assert registry.has("nonexistent") is False

    def test_names_returns_all_registered(self):
        """names() returns all registered tool names."""
        registry = self.make_registry_with_tools()
        names = registry.names()
        assert "read_db" in names
        assert "write_file" in names
        assert len(names) == 2

    def test_len_returns_count(self):
        """len() returns number of registered tools."""
        registry = self.make_registry_with_tools()
        assert len(registry) == 2

    def test_repr_includes_tool_names(self):
        """repr() includes registered tool names."""
        registry = self.make_registry_with_tools()
        r = repr(registry)
        assert "read_db" in r
        assert "write_file" in r

    def test_scoped_returns_subset(self):
        """scoped() returns a ScopedToolRegistry with only permitted tools."""
        registry = self.make_registry_with_tools()
        scoped = registry.scoped(["read_db"])
        assert scoped.has("read_db") is True
        assert scoped.has("write_file") is False

    def test_scoped_raises_on_unregistered_permitted_tool(self):
        """scoped() raises ToolNotFoundError if a permitted tool is unregistered."""
        registry = self.make_registry_with_tools()
        with pytest.raises(ToolNotFoundError):
            registry.scoped(["read_db", "nonexistent_tool"])

    def test_scoped_empty_list_returns_empty_registry(self):
        """scoped([]) returns a ScopedToolRegistry with no tools."""
        registry = self.make_registry_with_tools()
        scoped = registry.scoped([])
        assert len(scoped) == 0


# ── ScopedToolRegistry ───────────────────────────────────────

class TestScopedToolRegistry:

    def make_scoped(self) -> ScopedToolRegistry:
        read_tool  = StubTool("read_db",   idempotent=True)
        write_tool = StubTool("write_file", idempotent=False)
        return ScopedToolRegistry({
            "read_db":    read_tool,
            "write_file": write_tool,
        })

    def test_get_permitted_tool(self):
        """get() returns the tool for a permitted name."""
        scoped = self.make_scoped()
        tool = scoped.get("read_db")
        assert tool.name == "read_db"

    def test_get_unpermitted_raises(self):
        """get() raises ToolNotFoundError for tool not in permitted set."""
        scoped = self.make_scoped()
        with pytest.raises(ToolNotFoundError):
            scoped.get("send_email")

    def test_has_permitted_returns_true(self):
        scoped = self.make_scoped()
        assert scoped.has("read_db") is True

    def test_has_unpermitted_returns_false(self):
        scoped = self.make_scoped()
        assert scoped.has("send_email") is False

    def test_names_returns_permitted_only(self):
        scoped = self.make_scoped()
        names = scoped.names()
        assert set(names) == {"read_db", "write_file"}

    def test_contains_operator(self):
        scoped = self.make_scoped()
        assert "read_db" in scoped
        assert "send_email" not in scoped

    def test_iter_returns_all_tools(self):
        scoped = self.make_scoped()
        tools = list(scoped)
        assert len(tools) == 2

    def test_len_returns_count(self):
        scoped = self.make_scoped()
        assert len(scoped) == 2

    def test_scoped_registry_is_independent_of_source(self):
        """
        ScopedToolRegistry is a snapshot.
        Adding tools to the source registry after scoping
        does not affect the scoped view.
        """
        registry = ToolRegistry()
        registry.register(StubTool("read_db"))
        scoped = registry.scoped(["read_db"])

        # Add a new tool to the original registry
        registry.register(StubTool("write_db"))

        # Scoped view should not see the new tool
        assert scoped.has("write_db") is False
        assert len(scoped) == 1

    def test_repr_includes_permitted_names(self):
        scoped = self.make_scoped()
        r = repr(scoped)
        assert "read_db" in r
        assert "write_file" in r


# ── ToolNotFoundError + ToolCallError ────────────────────────

class TestToolExceptions:

    def test_tool_not_found_error_message(self):
        err = ToolNotFoundError("mystery_tool")
        assert "mystery_tool" in str(err)
        assert err.tool_name == "mystery_tool"

    def test_tool_call_error_message(self):
        err = ToolCallError("read_db", "connection refused")
        assert "read_db" in str(err)
        assert "connection refused" in str(err)
        assert err.tool_name == "read_db"
        assert err.reason == "connection refused"

    def test_tool_not_found_is_exception(self):
        assert issubclass(ToolNotFoundError, Exception)

    def test_tool_call_error_is_exception(self):
        assert issubclass(ToolCallError, Exception)
