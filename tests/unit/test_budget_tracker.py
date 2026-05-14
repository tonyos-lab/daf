"""
Unit tests for BudgetTracker (Step 9 additions)
and ScopedContext + BudgetTracker wiring.

The adversarial concurrent-budget tests remain in tests/adversarial/.
These unit tests cover:
  - BudgetTracker new methods: from_grant, is_exhausted, summary
  - Negative value validation
  - record_actual adjustment (positive and negative delta)
  - ScopedContext budget property accessible and correct
  - Agent can check and record budget through context
"""
from __future__ import annotations

import uuid
import pytest

from daf.runtime.budget_tracker import BudgetTracker
from daf.runtime.scoped_context import ScopedContext
from daf.runtime.tool_registry import ToolRegistry
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.tools.stub_tool import StubTool


# ── Fixtures ─────────────────────────────────────────────────

def make_registry(*tool_names: str) -> ToolRegistry:
    registry = ToolRegistry()
    for name in tool_names:
        registry.register(StubTool(name=name))
    return registry


def make_grant(
    agent_role: str,
    tools: list[str],
    max_cost_usd: float = 0.50,
    max_calls: int = 3,
) -> ApprovalGrant:
    return ApprovalGrant(
        grant_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        approved_plan=None,
        agent_permissions={
            agent_role: AgentPermissions(
                tools=tools,
                data_sources=[],
                access_level="read_only",
                max_calls=max_calls,
            )
        },
        gated_tasks=[],
        execution_constraints={
            "max_cost_usd": max_cost_usd,
            "human_gate_required": False,
        },
    )


# ── BudgetTracker — New Methods ───────────────────────────────

class TestBudgetTrackerNewMethods:

    def test_from_grant_reads_max_cost(self):
        """from_grant() reads max_cost_usd from execution_constraints."""
        grant   = make_grant("reader", tools=["read_db"], max_cost_usd=0.75)
        tracker = BudgetTracker.from_grant(grant)
        assert tracker.max_cost == 0.75

    def test_from_grant_defaults_to_one_dollar_when_not_set(self):
        """from_grant() defaults to $1.00 when max_cost_usd not in constraints."""
        grant = ApprovalGrant(
            grant_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            approved_plan=None,
            agent_permissions={
                "reader": AgentPermissions(
                    tools=[], data_sources=[], max_calls=3
                )
            },
            gated_tasks=[],
            execution_constraints={},  # no max_cost_usd
        )
        tracker = BudgetTracker.from_grant(grant)
        assert tracker.max_cost == 1.0

    def test_is_exhausted_false_when_budget_remains(self):
        """is_exhausted is False when budget has not been fully used."""
        tracker = BudgetTracker(max_cost_usd=0.50)
        tracker.check_and_reserve(0.20)
        assert tracker.is_exhausted is False

    def test_is_exhausted_true_when_fully_spent(self):
        """is_exhausted is True when all budget is reserved."""
        tracker = BudgetTracker(max_cost_usd=0.10)
        tracker.check_and_reserve(0.10)
        assert tracker.is_exhausted is True

    def test_is_exhausted_true_when_over_spent_via_record_actual(self):
        """is_exhausted is True when actual cost exceeds reservation."""
        tracker = BudgetTracker(max_cost_usd=0.10)
        tracker.check_and_reserve(0.05)
        tracker.record_actual(actual_cost=0.10, reserved_cost=0.05)
        # spent is now 0.10 = max_cost
        assert tracker.is_exhausted is True

    def test_summary_returns_correct_fields(self):
        """summary() returns all expected fields with correct values."""
        tracker = BudgetTracker(max_cost_usd=0.50)
        tracker.check_and_reserve(0.20)

        s = tracker.summary()
        assert s["max_cost_usd"]  == 0.50
        assert s["spent_usd"]     == 0.20
        assert s["remaining_usd"] == 0.30
        assert s["utilization_pct"] == 40.0

    def test_summary_zero_max_cost_does_not_divide_by_zero(self):
        """summary() handles max_cost_usd=0 without division by zero."""
        tracker = BudgetTracker(max_cost_usd=0.0)
        s = tracker.summary()
        assert s["utilization_pct"] == 0.0

    def test_negative_max_cost_raises(self):
        """Negative max_cost_usd raises ValueError."""
        with pytest.raises(ValueError, match="max_cost_usd"):
            BudgetTracker(max_cost_usd=-1.0)

    def test_negative_estimated_cost_raises(self):
        """Negative estimated_cost in check_and_reserve raises ValueError."""
        tracker = BudgetTracker(max_cost_usd=1.0)
        with pytest.raises(ValueError, match="estimated_cost"):
            tracker.check_and_reserve(-0.01)

    def test_repr_includes_spent_and_max(self):
        """repr() includes spent and max values."""
        tracker = BudgetTracker(max_cost_usd=0.50)
        tracker.check_and_reserve(0.10)
        r = repr(tracker)
        assert "0.10" in r or "0.1000" in r
        assert "0.50" in r or "0.5000" in r


# ── BudgetTracker — Core Behaviour ───────────────────────────

class TestBudgetTrackerCoreBehaviour:

    def test_initial_spent_is_zero(self):
        tracker = BudgetTracker(max_cost_usd=1.0)
        assert tracker.spent == 0.0

    def test_initial_remaining_equals_max(self):
        tracker = BudgetTracker(max_cost_usd=0.50)
        assert tracker.remaining == 0.50

    def test_check_and_reserve_reduces_remaining(self):
        tracker = BudgetTracker(max_cost_usd=0.50)
        tracker.check_and_reserve(0.10)
        assert tracker.remaining == pytest.approx(0.40)

    def test_check_and_reserve_returns_false_when_over_budget(self):
        tracker = BudgetTracker(max_cost_usd=0.10)
        result  = tracker.check_and_reserve(0.11)
        assert result is False
        assert tracker.spent == 0.0  # nothing reserved

    def test_check_and_reserve_returns_true_at_exact_limit(self):
        """Reservation exactly equal to remaining budget succeeds."""
        tracker = BudgetTracker(max_cost_usd=0.10)
        result  = tracker.check_and_reserve(0.10)
        assert result is True
        assert tracker.spent == pytest.approx(0.10)

    def test_record_actual_adjusts_upward(self):
        """record_actual with actual > reserved increases spent."""
        tracker = BudgetTracker(max_cost_usd=1.0)
        tracker.check_and_reserve(0.05)    # reserve 0.05
        tracker.record_actual(0.08, 0.05)  # actual was 0.08
        assert tracker.spent == pytest.approx(0.08)

    def test_record_actual_adjusts_downward(self):
        """record_actual with actual < reserved decreases spent."""
        tracker = BudgetTracker(max_cost_usd=1.0)
        tracker.check_and_reserve(0.10)    # reserve 0.10
        tracker.record_actual(0.03, 0.10)  # actual was only 0.03
        assert tracker.spent == pytest.approx(0.03)

    def test_record_actual_releases_on_zero_cost(self):
        """record_actual with actual=0 fully releases reservation."""
        tracker = BudgetTracker(max_cost_usd=0.50)
        tracker.check_and_reserve(0.10)
        tracker.record_actual(0.0, 0.10)  # call failed, no cost
        assert tracker.spent == pytest.approx(0.0)

    def test_record_actual_does_not_go_below_zero(self):
        """Floating-point drift cannot push spent below zero."""
        tracker = BudgetTracker(max_cost_usd=1.0)
        tracker.check_and_reserve(0.05)
        tracker.record_actual(0.0, 0.05)  # release
        tracker.record_actual(0.0, 0.01)  # extra release (shouldn't happen but safe)
        assert tracker.spent >= 0.0


# ── ScopedContext + BudgetTracker Wiring ─────────────────────

class TestScopedContextBudgetWiring:
    """
    Verify BudgetTracker is correctly wired into ScopedContext.
    """

    def test_budget_accessible_via_context(self):
        """context.budget returns the injected BudgetTracker."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        tracker  = BudgetTracker(max_cost_usd=0.50)

        ctx = ScopedContext(
            "reader", grant, registry,
            budget_tracker=tracker
        )

        assert ctx.budget is tracker

    def test_budget_none_when_not_injected(self):
        """context.budget is None when no tracker provided."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"])
        ctx      = ScopedContext("reader", grant, registry)

        assert ctx.budget is None

    def test_budget_check_and_reserve_via_context(self):
        """Agent can call context.budget.check_and_reserve()."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"], max_cost_usd=0.20)
        tracker  = BudgetTracker(max_cost_usd=0.20)

        ctx = ScopedContext(
            "reader", grant, registry,
            budget_tracker=tracker
        )

        # Agent reserves budget before a call
        approved = ctx.budget.check_and_reserve(0.05)
        assert approved is True
        assert ctx.budget.remaining == pytest.approx(0.15)

    def test_budget_exhaustion_visible_via_context(self):
        """When budget is exhausted, context.budget.is_exhausted is True."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"], max_cost_usd=0.10)
        tracker  = BudgetTracker(max_cost_usd=0.10)

        ctx = ScopedContext(
            "reader", grant, registry,
            budget_tracker=tracker
        )

        ctx.budget.check_and_reserve(0.10)
        assert ctx.budget.is_exhausted is True

        # Next reservation must fail
        approved = ctx.budget.check_and_reserve(0.001)
        assert approved is False

    def test_from_grant_integration(self):
        """BudgetTracker.from_grant() + ScopedContext integration."""
        registry = make_registry("read_db")
        grant    = make_grant("reader", tools=["read_db"], max_cost_usd=0.30)
        tracker  = BudgetTracker.from_grant(grant)

        ctx = ScopedContext(
            "reader", grant, registry,
            budget_tracker=tracker
        )

        assert ctx.budget.max_cost == 0.30
        assert ctx.budget.remaining == 0.30

    def test_shared_tracker_across_two_contexts(self):
        """
        The same BudgetTracker is shared across multiple ScopedContexts
        in the same workflow. Spending in one is visible in the other.
        This is the intended Phase 2 pattern for multi-agent workflows.
        """
        registry     = make_registry("read_db", "write_file")
        grant_reader = ApprovalGrant(
            grant_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            approved_plan=None,
            agent_permissions={
                "reader": AgentPermissions(
                    tools=["read_db"], data_sources=[],
                    max_calls=3,
                ),
                "writer": AgentPermissions(
                    tools=["write_file"], data_sources=[],
                    max_calls=3,
                ),
            },
            gated_tasks=[],
            execution_constraints={"max_cost_usd": 0.20},
        )
        shared_tracker = BudgetTracker(max_cost_usd=0.20)

        ctx_reader = ScopedContext(
            "reader", grant_reader, registry,
            budget_tracker=shared_tracker
        )
        ctx_writer = ScopedContext(
            "writer", grant_reader, registry,
            budget_tracker=shared_tracker
        )

        # Reader spends 0.08
        ctx_reader.budget.check_and_reserve(0.08)
        assert ctx_reader.budget.spent == pytest.approx(0.08)

        # Writer sees the same spent amount (shared tracker)
        assert ctx_writer.budget.spent == pytest.approx(0.08)
        assert ctx_writer.budget.remaining == pytest.approx(0.12)

        # Writer spends 0.10 — total now 0.18
        ctx_writer.budget.check_and_reserve(0.10)
        assert shared_tracker.spent == pytest.approx(0.18)

        # Neither can spend more than remaining 0.02
        assert ctx_reader.budget.check_and_reserve(0.05) is False
        assert ctx_writer.budget.check_and_reserve(0.05) is False
