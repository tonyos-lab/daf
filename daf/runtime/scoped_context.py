"""
ScopedContext — the complete runtime interface for an agent.

Contains exactly the tools the Policy Engine approved.
Cannot be expanded after creation — by the agent, by model reasoning,
or by adversarial content in tool outputs.

WHAT IS IN SCOPE:
  tools:      ScopedToolRegistry — only permitted tools
  task_input: dict — read-only outputs from dependency tasks
  role:       str  — this agent's role name
  max_calls:  int  — maximum LLM calls permitted (enforced in Phase 3)

WHAT IS NOT IN SCOPE (yet):
  data_sources: DataRegistry clients are a Phase 3 concern.
                Data access in Phase 2 happens through tools
                (e.g. read_db tool queries the database).
                data_source names are recorded for audit purposes only.

DESIGN INVARIANT (from design-philosophy.md, Principle 7):
  ScopedContext permissions are enforced at instantiation.
  A tool that is not in permissions.tools does not exist
  in this context — not because the agent is instructed not to use it,
  but because it literally cannot access it.
  ToolNotFoundError is raised at get() time, not at call() time.

ADVERSARIAL PROPERTY:
  Even if a model instruction says "call write_db",
  even if tool output contains "use admin_tool",
  the agent cannot comply — those clients do not exist.
  This is verified by the adversarial test suite.
"""
from __future__ import annotations

import logging
from typing import Any

from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.runtime.tool_registry import ToolRegistry, ScopedToolRegistry

logger = logging.getLogger(__name__)


class ScopedContext:
    """
    Complete runtime interface for an agent.

    Instantiated from ApprovalGrant + ToolRegistry.
    Scope is immutable after creation.

    Args:
        agent_role:    The role name for this agent (from SubTask.agent_required)
        grant:         The ApprovalGrant from the Policy Engine
        tool_registry: The full ToolRegistry — only permitted tools are exposed
        task_input:    Read-only outputs from dependency tasks
    """

    def __init__(
        self,
        agent_role:     str,
        grant:          ApprovalGrant,
        tool_registry:  ToolRegistry,
        task_input:     dict[str, Any] | None = None,
        budget_tracker: Any | None = None,
    ) -> None:
        # Validate that the role exists in the grant
        if agent_role not in grant.agent_permissions:
            raise ValueError(
                f"Agent role '{agent_role}' not found in ApprovalGrant. "
                f"Available roles: {list(grant.agent_permissions.keys())}"
            )

        permissions: AgentPermissions = grant.agent_permissions[agent_role]

        # Build ScopedToolRegistry — only permitted tools exist here
        # ToolNotFoundError raised here (at instantiation) if a permitted
        # tool is not registered — not silently at call time
        self.tools: ScopedToolRegistry = tool_registry.scoped(
            permissions.tools
        )

        # Record permitted data sources (clients deferred to Phase 3)
        self._permitted_data_sources: list[str] = permissions.data_sources

        # Read-only dependency outputs — agents receive upstream results here
        self.task_input: dict[str, Any] = dict(task_input or {})

        # Agent metadata
        self.role:      str = agent_role
        self.max_calls: int = permissions.max_calls

        # BudgetTracker — shared across all agents in this workflow
        # Injected by ExecutionOrchestrator (Step 14)
        # Can be None in unit tests that don't test budget enforcement
        self._budget_tracker: Any = budget_tracker

        logger.debug(
            f"ScopedContext created: "
            f"role={agent_role!r} "
            f"tools={self.tools.names()} "
            f"data_sources={self._permitted_data_sources} "
            f"max_calls={self.max_calls}"
        )

    @property
    def permitted_data_sources(self) -> list[str]:
        """
        Names of data sources this agent is permitted to access.
        Actual data client instantiation is deferred to Phase 3.
        """
        return list(self._permitted_data_sources)

    @property
    def budget(self) -> Any:
        """
        BudgetTracker for this execution context.

        Shared across all agents in the same workflow.
        Injected by ExecutionOrchestrator via the budget_tracker parameter.
        Returns None when not injected (unit tests without budget enforcement).

        Agents check this before every LLM call:
            if not context.budget.check_and_reserve(estimated_cost):
                return AgentResult.fail(...)
        """
        return self._budget_tracker

    def __repr__(self) -> str:
        return (
            f"ScopedContext("
            f"role={self.role!r}, "
            f"tools={self.tools.names()}, "
            f"data_sources={self._permitted_data_sources}, "
            f"max_calls={self.max_calls})"
        )
