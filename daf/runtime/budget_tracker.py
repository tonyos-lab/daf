"""
BudgetTracker — atomic pre-execution cost enforcement.

Checks budget BEFORE every LLM call. Never after.
Uses compare-and-swap semantics to prevent race conditions
under concurrent agent execution.

CRITICAL: check_and_reserve() must be called before every LLM call.
If it returns False, the call must NOT proceed.
This is not a suggestion. It is the enforcement mechanism.

ONE TRACKER PER WORKFLOW:
  The PolicyMatrix budget limit is per-workflow.
  All agents in a workflow share one BudgetTracker.
  It is created by ExecutionOrchestrator from the ApprovalGrant
  and injected into each ScopedContext.

USAGE IN AN AGENT:
    async def execute(self, task, context):
        estimated = context.budget.estimate_for_step(task)
        if not context.budget.check_and_reserve(estimated):
            return AgentResult.fail(
                task_id=task.task_id,
                error=f"Budget exhausted. "
                      f"Remaining: ${context.budget.remaining:.4f}"
            )
        try:
            response = await some_llm_call()
            context.budget.record_actual(
                actual_cost=response.usage.cost_usd,
                reserved_cost=estimated,
            )
            return AgentResult.ok(task_id=task.task_id, output=response)
        except Exception as e:
            # Release reservation on failure
            context.budget.record_actual(0.0, estimated)
            raise
"""
from __future__ import annotations

import threading
from typing import Any


class BudgetTracker:
    """
    Atomic budget enforcement for DAF workflows.

    Thread-safe via threading.Lock. Supports concurrent agents
    in the same workflow without race conditions.
    """

    def __init__(self, max_cost_usd: float) -> None:
        """
        Args:
            max_cost_usd: Maximum total spend allowed for this workflow.
                          From ApprovalGrant.execution_constraints["max_cost_usd"]
        """
        if max_cost_usd < 0:
            raise ValueError(
                f"max_cost_usd must be >= 0, got {max_cost_usd}"
            )
        self._max_cost = max_cost_usd
        self._spent    = 0.0
        self._lock     = threading.Lock()

    @classmethod
    def from_grant(cls, grant: Any) -> BudgetTracker:
        """
        Create a BudgetTracker from an ApprovalGrant.

        Reads max_cost_usd from grant.execution_constraints.
        Defaults to 1.0 if not set (conservative fallback).

        Args:
            grant: ApprovalGrant with execution_constraints

        Returns:
            BudgetTracker configured for this workflow
        """
        max_cost = grant.execution_constraints.get("max_cost_usd", 1.0)
        return cls(max_cost_usd=float(max_cost))

    def check_and_reserve(self, estimated_cost: float) -> bool:
        """
        Atomically check if budget remains and reserve the estimated amount.

        Must be called BEFORE every LLM call or tool call that has a cost.
        If returns False, the call MUST NOT proceed.

        Args:
            estimated_cost: Expected cost of the upcoming call in USD

        Returns:
            True:  reservation succeeded — caller may proceed
            False: budget would be exceeded — caller must NOT proceed
        """
        if estimated_cost < 0:
            raise ValueError(
                f"estimated_cost must be >= 0, got {estimated_cost}"
            )
        with self._lock:
            if self._spent + estimated_cost > self._max_cost:
                return False
            self._spent += estimated_cost
            return True

    def record_actual(
        self,
        actual_cost:   float,
        reserved_cost: float,
    ) -> None:
        """
        Adjust from reserved estimate to actual cost after a call completes.

        Call this after every successful LLM/tool call to correct the
        reservation. If the actual cost differs from the estimate,
        this adjusts the running total accordingly.

        If a call fails and no cost was incurred, call with actual_cost=0.0
        to release the reservation.

        Args:
            actual_cost:   Actual cost incurred (from LLMUsage.cost_usd)
            reserved_cost: The amount previously reserved via check_and_reserve
        """
        delta = actual_cost - reserved_cost
        if delta != 0:
            with self._lock:
                self._spent += delta
                # Clamp to prevent floating-point drift below zero
                if self._spent < 0:
                    self._spent = 0.0

    @property
    def spent(self) -> float:
        """Total cost spent so far (reserved + adjustments)."""
        return self._spent

    @property
    def remaining(self) -> float:
        """Remaining budget in USD. Never returns negative."""
        return max(0.0, self._max_cost - self._spent)

    @property
    def max_cost(self) -> float:
        """Maximum cost allowed for this workflow."""
        return self._max_cost

    @property
    def is_exhausted(self) -> bool:
        """True when no budget remains for any meaningful call."""
        return self._spent >= self._max_cost

    def summary(self) -> dict[str, float]:
        """
        Return a budget summary dict for audit records and logging.

        Returns:
            dict with max_cost_usd, spent_usd, remaining_usd, utilization_pct
        """
        return {
            "max_cost_usd":      self._max_cost,
            "spent_usd":         self._spent,
            "remaining_usd":     self.remaining,
            "utilization_pct":   (
                round(self._spent / self._max_cost * 100, 2)
                if self._max_cost > 0 else 0.0
            ),
        }

    def __repr__(self) -> str:
        return (
            f"BudgetTracker("
            f"spent=${self._spent:.4f}, "
            f"max=${self._max_cost:.4f}, "
            f"remaining=${self.remaining:.4f})"
        )
