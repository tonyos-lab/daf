"""
BaseTool — the contract every tool in DAF must satisfy.

Tools are the only way agents interact with the outside world.
Every tool is:
  - Named: a string identifier matching the PolicyMatrix tool names
  - Classified: idempotent or non-idempotent
  - Stateless: no mutable instance state between calls
  - Typed: call() returns ToolResult, never raw values

Idempotency classification is critical for the ExecutionOrchestrator:
  idempotent=True  → safe to retry on transient failure
                     (read_db, read_file, llm_extraction)
  idempotent=False → NOT safe to retry without verification
                     (write_db, send_email, delete_record)

DESIGN INVARIANT:
  Tools are instantiated by the ToolRegistry.
  They are placed in ScopedContext by the ExecutionOrchestrator.
  An agent only ever sees the tools in its ScopedContext.
  A tool that is not in ScopedContext does not exist for that agent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


# ── Result ───────────────────────────────────────────────────

class ToolResult(BaseModel):
    """
    The return value of every tool call.

    success=True:  output contains the tool's result
    success=False: error contains the failure reason
                   output may be None or partial

    metadata: optional diagnostic data (latency, source, etc.)
    """
    success:  bool
    output:   Any              = None
    error:    str | None       = None
    metadata: dict[str, Any]   = Field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any, **metadata: Any) -> ToolResult:
        """Convenience constructor for a successful result."""
        return cls(success=True, output=output, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> ToolResult:
        """Convenience constructor for a failed result."""
        return cls(success=False, error=error, metadata=metadata)


# ── Exceptions ───────────────────────────────────────────────

class ToolNotFoundError(Exception):
    """
    Raised when a tool name is not registered in the ToolRegistry.

    Never silently return None — fail loud so the misconfiguration
    is caught at instantiation time, not at call time.
    """
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' is not registered in the ToolRegistry. "
            f"Add it to the registry or check the PolicyMatrix tool names."
        )
        self.tool_name = tool_name


class ToolCallError(Exception):
    """
    Raised when a tool call fails in an unrecoverable way.

    Distinct from a ToolResult with success=False:
      - ToolResult(success=False): the tool ran but the operation failed
        (e.g. record not found, file empty) — caller handles gracefully
      - ToolCallError: the tool itself broke (network down, auth failed)
        — caller should not retry without investigating
    """
    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"Tool '{tool_name}' call failed: {reason}")
        self.tool_name = tool_name
        self.reason    = reason


# ── Base class ───────────────────────────────────────────────

class BaseTool(ABC):
    """
    Abstract base class for all DAF tools.

    Every tool implementation must:
    1. Define `name` as a class attribute (str)
    2. Define `idempotent` as a class attribute (bool)
    3. Implement `call(**kwargs) -> ToolResult`

    Tools are stateless. Do not store mutable state in instance
    variables that persists between calls. Each call() is independent.

    Example implementation:
        class ReadDbTool(BaseTool):
            name       = "read_db"
            idempotent = True

            async def call(self, query: str, table: str) -> ToolResult:
                try:
                    rows = await self._db.fetch(query, table)
                    return ToolResult.ok(output=rows)
                except Exception as e:
                    return ToolResult.fail(error=str(e))
    """

    # Subclasses must define these as class attributes
    name:       str   # matches the tool name in PolicyMatrix
    idempotent: bool  # True = safe to retry on failure

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce that concrete subclasses declare name and idempotent."""
        super().__init_subclass__(**kwargs)

        # Detect abstract classes by checking for abstract methods.
        # We check both the class itself and inspect whether it has
        # declared abstract methods via __abstractmethods__ (set by ABC
        # after class creation) or via abstractmethod decorators
        # (visible during __init_subclass__ via __dict__).
        import inspect
        has_abstract_methods = any(
            getattr(getattr(cls, m, None), "__isabstractmethod__", False)
            for m in dir(cls)
        )
        # Also check own dict for abstract methods defined in this class
        has_own_abstract = any(
            getattr(v, "__isabstractmethod__", False)
            for v in cls.__dict__.values()
        )

        if has_abstract_methods or has_own_abstract:
            return  # Abstract class — do not enforce

        # Concrete class — enforce required class attributes
        if not hasattr(cls, "name") or not isinstance(
            getattr(cls, "name", None), str
        ):
            raise TypeError(
                f"Tool class '{cls.__name__}' must define "
                f"`name: str` as a class attribute."
            )
        if not hasattr(cls, "idempotent") or not isinstance(
            getattr(cls, "idempotent", None), bool
        ):
            raise TypeError(
                f"Tool class '{cls.__name__}' must define "
                f"`idempotent: bool` as a class attribute."
            )

    @abstractmethod
    async def call(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with the given arguments.

        Must return a ToolResult — never raise for expected failures.
        Raise ToolCallError only for unexpected infrastructure failures.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            ToolResult with success=True and output, or
            ToolResult with success=False and error message

        Raises:
            ToolCallError: infrastructure failure (not a business error)
        """
        ...

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.name!r}, "
            f"idempotent={self.idempotent})"
        )
