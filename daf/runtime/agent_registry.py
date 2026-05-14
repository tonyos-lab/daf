"""
AgentRegistry — maps agent role names to agent classes.

The registry stores CLASSES, not instances.
Agents are instantiated per sub-task by the ExecutionOrchestrator.

WHY CLASSES NOT INSTANCES:
  Each sub-task execution needs a fresh agent instance
  with its own ScopedContext. Storing classes allows
  the ExecutionOrchestrator to instantiate on demand
  with the correct permissions for each run.

USAGE:
    registry = AgentRegistry()
    registry.register(DocumentReaderAgent)
    registry.register(RiskAnalyzerAgent)

    # ExecutionOrchestrator uses this:
    agent = registry.instantiate("document_reader", context)
    result = await agent.run(task, context)
"""
from __future__ import annotations

import logging
from typing import Any, Type

from daf.runtime.agent import BaseAgent, AgentNotFoundError, AgentAlreadyRegisteredError

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Registry mapping agent role names to agent classes.

    Stores agent classes — not instances.
    Instantiation happens at execution time via instantiate().
    """

    def __init__(self) -> None:
        self._agents: dict[str, type[BaseAgent]] = {}

    def register(
        self,
        agent_class: type[BaseAgent],
        replace: bool = False,
    ) -> None:
        """
        Register an agent class by its role name.

        Args:
            agent_class: A concrete BaseAgent subclass
            replace:     If True, overwrites existing registration.
                         If False (default), raises if role already registered.

        Raises:
            AgentAlreadyRegisteredError: role already registered and replace=False
            TypeError: agent_class is not a BaseAgent subclass
        """
        if not (isinstance(agent_class, type)
                and issubclass(agent_class, BaseAgent)):
            raise TypeError(
                f"Expected a BaseAgent subclass, got {agent_class!r}"
            )

        role = agent_class.role

        if role in self._agents and not replace:
            raise AgentAlreadyRegisteredError(role)

        self._agents[role] = agent_class
        logger.debug(f"Agent registered: role={role!r} class={agent_class.__name__}")

    def instantiate(
        self,
        role:    str,
        context: Any,   # ScopedContext — avoid circular import
    ) -> BaseAgent:
        """
        Instantiate an agent for the given role with its ScopedContext.

        Args:
            role:    The agent role name (from SubTask.agent_required)
            context: ScopedContext built from the ApprovalGrant

        Returns:
            A fresh BaseAgent instance ready to execute

        Raises:
            AgentNotFoundError: role not registered
        """
        agent_class = self._agents.get(role)
        if agent_class is None:
            raise AgentNotFoundError(role)

        agent = agent_class()
        logger.debug(
            f"Agent instantiated: role={role!r} "
            f"class={agent_class.__name__}"
        )
        return agent

    def get_class(self, role: str) -> type[BaseAgent]:
        """
        Return the agent class for a role without instantiating.
        Used for inspection and testing.
        """
        cls = self._agents.get(role)
        if cls is None:
            raise AgentNotFoundError(role)
        return cls

    def has(self, role: str) -> bool:
        """Return True if a class is registered for this role."""
        return role in self._agents

    def roles(self) -> list[str]:
        """Return all registered role names."""
        return list(self._agents.keys())

    def __len__(self) -> int:
        return len(self._agents)

    def __repr__(self) -> str:
        return f"AgentRegistry(roles={self.roles()})"
