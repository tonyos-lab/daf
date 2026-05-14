"""
BaseAgent — the contract every agent in DAF must satisfy.

Agents are the workers of the Execution Layer.
Each agent:
  - Has a role name matching agent_required in SubTask
  - Receives a ScopedContext containing only its permitted tools
  - Executes exactly one sub-task per instantiation
  - Returns an AgentResult with success/failure + output

AGENT LIFECYCLE (per sub-task):
  1. ExecutionOrchestrator receives an ApprovalGrant
  2. For each sub-task, it calls AgentRegistry.instantiate()
  3. AgentRegistry creates a new agent instance with ScopedContext
  4. ExecutionOrchestrator calls agent.run(task, context)
  5. run() wraps execute() with error handling
  6. execute() does the actual work using context.tools
  7. AgentResult returned to ExecutionOrchestrator

DESIGN INVARIANTS:
  - Agents are instantiated per sub-task, not reused
  - Agents only access tools through their ScopedContext
  - run() is final — subclasses implement execute() only
  - Agents never call the LLM directly —
    they use context.llm if they need language model calls
    (which is also scoped to permitted call types and max_calls)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


# ── Result ───────────────────────────────────────────────────

class AgentResult(BaseModel):
    """
    The return value of every agent run.

    success=True:  output contains the agent's result
    success=False: error contains the failure reason

    cost_usd: actual cost incurred during this run
              (populated from BudgetTracker actual cost)
    metadata: optional diagnostic data for audit trail
    """
    task_id:  str
    success:  bool
    output:   Any              = None
    error:    str | None       = None
    cost_usd: float            = 0.0
    metadata: dict[str, Any]   = Field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        task_id:  str,
        output:   Any,
        cost_usd: float = 0.0,
        **metadata: Any,
    ) -> AgentResult:
        """Convenience constructor for a successful result."""
        return cls(
            task_id=task_id,
            success=True,
            output=output,
            cost_usd=cost_usd,
            metadata=metadata,
        )

    @classmethod
    def fail(
        cls,
        task_id:  str,
        error:    str,
        cost_usd: float = 0.0,
        **metadata: Any,
    ) -> AgentResult:
        """Convenience constructor for a failed result."""
        return cls(
            task_id=task_id,
            success=False,
            error=error,
            cost_usd=cost_usd,
            metadata=metadata,
        )


# ── Exceptions ───────────────────────────────────────────────

class AgentNotFoundError(Exception):
    """
    Raised when an agent role is not registered in AgentRegistry.
    Fail loud — misconfigured role names are caught at instantiation.
    """
    def __init__(self, role: str) -> None:
        super().__init__(
            f"Agent role '{role}' is not registered in the AgentRegistry. "
            f"Register an agent class for this role or check the PolicyMatrix."
        )
        self.role = role


class AgentAlreadyRegisteredError(Exception):
    """Raised when registering a role that is already registered."""
    def __init__(self, role: str) -> None:
        super().__init__(
            f"Agent role '{role}' is already registered. "
            f"Use replace=True to override."
        )
        self.role = role


class AgentExecutionError(Exception):
    """
    Raised when an agent's execute() raises an unexpected exception.

    Distinct from AgentResult(success=False):
      - AgentResult(success=False): agent ran but task failed
        (e.g. no results found, validation failed) — handled gracefully
      - AgentExecutionError: agent itself broke unexpectedly
        — ExecutionOrchestrator decides on retry/halt
    """
    def __init__(self, role: str, task_id: str, reason: str) -> None:
        super().__init__(
            f"Agent '{role}' failed on task '{task_id}': {reason}"
        )
        self.role    = role
        self.task_id = task_id
        self.reason  = reason


# ── Base class ───────────────────────────────────────────────

class BaseAgent(ABC):
    """
    Abstract base class for all DAF agents.

    Every agent implementation must:
    1. Define `role` as a class attribute (str)
    2. Implement `execute(task, context) -> AgentResult`

    Do NOT override `run()` — it is the public interface
    that handles error wrapping. Override `execute()` only.

    Agents are stateless across runs. Do not store sub-task
    state in instance variables that persists between execute() calls.
    Each instantiation handles exactly one sub-task.
    """

    # Subclasses must define this as a class attribute
    role: str  # matches agent_required in SubTask + PolicyMatrix

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce that concrete subclasses declare role."""
        super().__init_subclass__(**kwargs)

        import inspect
        # Check for abstract methods in the class or its parents
        has_abstract = any(
            getattr(getattr(cls, m, None), "__isabstractmethod__", False)
            for m in dir(cls)
        )
        has_own_abstract = any(
            getattr(v, "__isabstractmethod__", False)
            for v in cls.__dict__.values()
        )
        if has_abstract or has_own_abstract:
            return  # abstract class — skip enforcement

        # Concrete class — enforce role attribute
        if not hasattr(cls, "role") or not isinstance(
            getattr(cls, "role", None), str
        ):
            raise TypeError(
                f"Agent class '{cls.__name__}' must define "
                f"`role: str` as a class attribute."
            )

    async def run(
        self,
        task:    Any,   # SubTask — avoid circular import
        context: Any,   # ScopedContext — avoid circular import
    ) -> AgentResult:
        """
        Public execution method — called by ExecutionOrchestrator.

        Wraps execute() with:
          - Exception catching (unexpected errors → AgentExecutionError)
          - Guarantees AgentResult is always returned (never raises)

        Do NOT override this method. Override execute() instead.
        """
        try:
            return await self.execute(task=task, context=context)
        except AgentExecutionError:
            raise  # re-raise structured errors from execute()
        except Exception as e:
            raise AgentExecutionError(
                role=self.role,
                task_id=getattr(task, "task_id", "unknown"),
                reason=str(e),
            ) from e

    @abstractmethod
    async def execute(
        self,
        task:    Any,   # SubTask
        context: Any,   # ScopedContext
    ) -> AgentResult:
        """
        Implement the agent's actual work here.

        Args:
            task:    The SubTask to execute
            context: ScopedContext with permitted tools and data

        Returns:
            AgentResult with success=True/False and output/error

        Raises:
            AgentExecutionError: for unexpected infrastructure failures
            Do NOT raise for expected business failures —
            return AgentResult.fail() instead.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(role={self.role!r})"
