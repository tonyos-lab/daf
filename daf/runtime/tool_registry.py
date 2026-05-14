"""
ToolRegistry — maps tool names to BaseTool instances.

The registry is the single source of truth for available tools.
ScopedContext uses it to instantiate tool clients for agents.

DESIGN RULES:
  1. get() never returns None — raises ToolNotFoundError on missing tool
  2. register() raises if a tool name is already registered
     (prevents silent overrides of production tools)
  3. The registry is built at application startup and treated as
     immutable during workflow execution

USAGE:
    registry = ToolRegistry()
    registry.register(ReadDbTool())
    registry.register(WriteFIleTool())

    # ScopedContext uses this:
    tool = registry.get("read_db")
    result = await tool.call(query="SELECT * FROM contracts")
"""
from __future__ import annotations

import logging
from typing import Iterator

from daf.runtime.tool import BaseTool, ToolNotFoundError

logger = logging.getLogger(__name__)


class ToolAlreadyRegisteredError(Exception):
    """Raised when registering a tool whose name is already taken."""
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' is already registered. "
            f"Use replace=True to override, or check for duplicate registrations."
        )
        self.tool_name = tool_name


class ToolRegistry:
    """
    Registry mapping tool names to BaseTool instances.

    Thread-safe for reads. Not thread-safe for concurrent registration
    (registration happens at startup, not during execution).
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(
        self,
        tool: BaseTool,
        replace: bool = False,
    ) -> None:
        """
        Register a tool in the registry.

        Args:
            tool:    A BaseTool instance to register
            replace: If True, overwrites an existing tool with the same name.
                     If False (default), raises ToolAlreadyRegisteredError
                     if the name is already taken.

        Raises:
            ToolAlreadyRegisteredError: name already registered and replace=False
        """
        if tool.name in self._tools and not replace:
            raise ToolAlreadyRegisteredError(tool.name)

        self._tools[tool.name] = tool
        logger.debug(
            f"Tool registered: {tool.name} "
            f"(idempotent={tool.idempotent})"
        )

    def get(self, tool_name: str) -> BaseTool:
        """
        Retrieve a tool by name.

        Args:
            tool_name: The tool's name string

        Returns:
            The registered BaseTool instance

        Raises:
            ToolNotFoundError: tool_name not registered
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(tool_name)
        return tool

    def has(self, tool_name: str) -> bool:
        """Return True if a tool with this name is registered."""
        return tool_name in self._tools

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def scoped(self, permitted_names: list[str]) -> ScopedToolRegistry:
        """
        Return a ScopedToolRegistry containing only the permitted tools.

        Used by ScopedContext to build an agent's tool set.
        Raises ToolNotFoundError if any permitted name is not registered.

        Args:
            permitted_names: List of tool names from the ApprovalGrant

        Returns:
            ScopedToolRegistry containing only the permitted tools
        """
        tools: dict[str, BaseTool] = {}
        for name in permitted_names:
            tools[name] = self.get(name)  # raises if not found
        return ScopedToolRegistry(tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return (
            f"ToolRegistry("
            f"tools={list(self._tools.keys())})"
        )


class ScopedToolRegistry:
    """
    An immutable, permission-scoped view of the ToolRegistry.

    Contains exactly the tools an agent is permitted to use.
    Cannot be expanded after creation.

    This is what ScopedContext exposes to agents —
    not the full ToolRegistry.
    """

    def __init__(self, tools: dict[str, BaseTool]) -> None:
        # Freeze the tools dict — no modifications after creation
        self._tools: dict[str, BaseTool] = dict(tools)

    def get(self, tool_name: str) -> BaseTool:
        """
        Get a tool by name.
        Raises ToolNotFoundError if not in the permitted set.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(tool_name)
        return tool

    def has(self, tool_name: str) -> bool:
        """Return True if this tool is in the permitted set."""
        return tool_name in self._tools

    def names(self) -> list[str]:
        """Return permitted tool names."""
        return list(self._tools.keys())

    def __iter__(self) -> Iterator[BaseTool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def __repr__(self) -> str:
        return (
            f"ScopedToolRegistry("
            f"permitted={list(self._tools.keys())})"
        )
