"""
StubTool — a configurable stub tool for testing and development.

Used in:
  - Unit tests that need tool instances without real I/O
  - Phase 1 examples before real tool implementations exist
  - Development environments without database/API access

The StubTool returns configurable output and can be set to
succeed or fail on demand. It records all calls for inspection.

USAGE:
    # Always succeeds with fixed output
    tool = StubTool("read_db", output={"rows": [{"id": 1}]})
    result = await tool.call(query="SELECT * FROM contracts")
    assert result.success is True
    assert result.output == {"rows": [{"id": 1}]}

    # Fails on demand
    tool = StubTool("read_db", should_fail=True, error="DB unavailable")
    result = await tool.call()
    assert result.success is False
    assert result.error == "DB unavailable"

    # Inspect call history
    tool = StubTool("read_db")
    await tool.call(query="SELECT 1")
    await tool.call(query="SELECT 2")
    assert len(tool.calls) == 2
    assert tool.calls[0]["query"] == "SELECT 1"
"""
from __future__ import annotations

from typing import Any

from daf.runtime.tool import BaseTool, ToolResult


class StubTool(BaseTool):
    """
    A configurable stub tool for testing and development.

    Unlike real tools, StubTool:
    - Has no external dependencies
    - Returns configurable output
    - Records all calls for test inspection
    - Can be set to fail on demand

    This is NOT a production tool. It is for testing only.
    """

    # These are set dynamically in __init__ rather than as class attributes
    # because StubTool is parameterized at construction time.
    # The __init_subclass__ validator is bypassed for stub tools
    # by setting the class attributes at the class level below.
    name:       str  = "stub"   # overridden in __init__
    idempotent: bool = True     # stubs are always safe to retry

    def __init__(
        self,
        name:        str  = "stub",
        idempotent:  bool = True,
        output:      Any  = None,
        should_fail: bool = False,
        error:       str  = "StubTool configured to fail",
    ) -> None:
        """
        Args:
            name:        Tool name (should match a PolicyMatrix tool name)
            idempotent:  Whether this tool is safe to retry
            output:      Output to return on success
            should_fail: If True, returns ToolResult.fail() on every call
            error:       Error message when should_fail=True
        """
        # Set instance attributes (override class attributes)
        self.name        = name
        self.idempotent  = idempotent
        self._output     = output
        self._should_fail = should_fail
        self._error      = error
        self.calls: list[dict[str, Any]] = []  # call history for test inspection

    async def call(self, **kwargs: Any) -> ToolResult:
        """
        Return configured output or failure.
        Records every call in self.calls for inspection.
        """
        # Record the call
        self.calls.append(dict(kwargs))

        if self._should_fail:
            return ToolResult.fail(
                error=self._error,
                call_number=len(self.calls),
            )

        return ToolResult.ok(
            output=self._output,
            call_number=len(self.calls),
        )

    def reset(self) -> None:
        """Clear call history. Useful between test assertions."""
        self.calls.clear()

    def __repr__(self) -> str:
        return (
            f"StubTool("
            f"name={self.name!r}, "
            f"idempotent={self.idempotent}, "
            f"calls={len(self.calls)})"
        )
