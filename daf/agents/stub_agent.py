"""
StubAgent — a configurable stub agent for testing and development.

Parallel to StubTool — same pattern, different abstraction level.

Used in:
  - Unit tests that need agent instances without real execution logic
  - Phase 1/2 examples before real agent implementations exist
  - Development environments without real tool infrastructure

USAGE:
    # Always succeeds with fixed output
    agent = StubAgent(output={"summary": "test output"})
    result = await agent.run(task, context)
    assert result.success is True
    assert result.output == {"summary": "test output"}

    # Fails on demand
    agent = StubAgent(should_fail=True, error="extraction failed")
    result = await agent.run(task, context)
    assert result.success is False

    # Inspect run history
    agent = StubAgent()
    await agent.run(task_a, context)
    await agent.run(task_b, context)
    assert len(agent.runs) == 2
    assert agent.runs[0]["task_id"] == task_a.task_id
"""
from __future__ import annotations

from typing import Any

from daf.runtime.agent import BaseAgent, AgentResult


class StubAgent(BaseAgent):
    """
    A configurable stub agent for testing and development.

    Unlike real agents, StubAgent:
    - Has no external dependencies
    - Returns configurable output
    - Records all runs for test inspection
    - Can be configured to fail on demand

    This is NOT a production agent. It is for testing only.
    """

    role: str = "stub_agent"  # override at instantiation if needed

    def __init__(
        self,
        role:        str  = "stub_agent",
        output:      Any  = None,
        should_fail: bool = False,
        error:       str  = "StubAgent configured to fail",
        cost_usd:    float = 0.0,
    ) -> None:
        """
        Args:
            role:        Agent role name
            output:      Output to return on success
            should_fail: If True, returns AgentResult.fail() on every run
            error:       Error message when should_fail=True
            cost_usd:    Simulated cost to include in AgentResult
        """
        self.role         = role
        self._output      = output
        self._should_fail = should_fail
        self._error       = error
        self._cost_usd    = cost_usd
        self.runs: list[dict[str, Any]] = []  # run history for inspection

    async def execute(
        self,
        task:    Any,
        context: Any,
    ) -> AgentResult:
        """
        Return configured output or failure.
        Records every run in self.runs for inspection.
        """
        task_id = getattr(task, "task_id", "unknown")

        # Record the run
        self.runs.append({
            "task_id":  task_id,
            "task":     task,
            "context":  context,
            "run_number": len(self.runs) + 1,
        })

        if self._should_fail:
            return AgentResult.fail(
                task_id=task_id,
                error=self._error,
                cost_usd=self._cost_usd,
                run_number=len(self.runs),
            )

        return AgentResult.ok(
            task_id=task_id,
            output=self._output,
            cost_usd=self._cost_usd,
            run_number=len(self.runs),
        )

    def reset(self) -> None:
        """Clear run history. Useful between test assertions."""
        self.runs.clear()

    def __repr__(self) -> str:
        return (
            f"StubAgent("
            f"role={self.role!r}, "
            f"runs={len(self.runs)})"
        )
