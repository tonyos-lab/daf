"""
Unit tests for WorkflowCheckpoint model and InMemoryCheckpointStore.

All tests use InMemoryCheckpointStore — no Redis/Docker required.
RedisCheckpointStore is tested in integration tests.

Coverage:
  - CheckpointState constants
  - WorkflowCheckpoint.create() initial state
  - WorkflowCheckpoint transition methods (immutable returns)
  - InMemoryCheckpointStore save, load, delete, exists
  - Resume scenario: loading checkpoint with pending tasks
  - HITL scenario: awaiting and resuming
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone

from daf.models.workflow_checkpoint import (
    WorkflowCheckpoint, CheckpointState,
)
from daf.runtime.checkpoint_store import (
    CheckpointStore, InMemoryCheckpointStore, CheckpointStoreError,
)
from daf.runtime.agent import AgentResult


# ── Fixtures ─────────────────────────────────────────────────

def make_checkpoint(
    request_id:    uuid.UUID | None = None,
    grant_id:      uuid.UUID | None = None,
    pending_tasks: list[str] | None = None,
) -> WorkflowCheckpoint:
    return WorkflowCheckpoint.create(
        request_id=request_id or uuid.uuid4(),
        grant_id=grant_id or uuid.uuid4(),
        pending_tasks=pending_tasks or ["ST-01", "ST-02", "ST-03"],
    )


def make_agent_result(task_id: str, success: bool = True) -> AgentResult:
    if success:
        return AgentResult.ok(task_id=task_id, output={"data": "result"})
    return AgentResult.fail(task_id=task_id, error="step failed")


# ── CheckpointState ──────────────────────────────────────────

class TestCheckpointState:

    def test_all_states_are_strings(self):
        """Every state constant is a non-empty string."""
        for state in CheckpointState.ALL:
            assert isinstance(state, str)
            assert len(state) > 0

    def test_all_contains_expected_states(self):
        assert CheckpointState.RUNNING       in CheckpointState.ALL
        assert CheckpointState.AWAITING_HITL in CheckpointState.ALL
        assert CheckpointState.RESUMING      in CheckpointState.ALL
        assert CheckpointState.COMPLETED     in CheckpointState.ALL
        assert CheckpointState.FAILED        in CheckpointState.ALL

    def test_no_duplicate_values(self):
        values = [
            v for k, v in vars(CheckpointState).items()
            if not k.startswith("_") and isinstance(v, str)
        ]
        assert len(values) == len(set(values))


# ── WorkflowCheckpoint.create() ──────────────────────────────

class TestWorkflowCheckpointCreate:

    def test_create_sets_initial_state(self):
        """create() sets state to RUNNING."""
        cp = make_checkpoint()
        assert cp.state == CheckpointState.RUNNING

    def test_create_sets_pending_tasks(self):
        """create() sets pending_tasks from the provided list."""
        cp = make_checkpoint(pending_tasks=["ST-01", "ST-02"])
        assert cp.pending_tasks == ["ST-01", "ST-02"]

    def test_create_empty_completed_tasks(self):
        """create() starts with no completed tasks."""
        cp = make_checkpoint()
        assert cp.completed_tasks == {}

    def test_create_zero_budget_spent(self):
        """create() starts with budget_spent=0."""
        cp = make_checkpoint()
        assert cp.budget_spent == 0.0

    def test_create_no_paused_task(self):
        """create() has no paused_at_task."""
        cp = make_checkpoint()
        assert cp.paused_at_task is None

    def test_create_generates_checkpoint_id(self):
        """create() generates a unique checkpoint_id."""
        cp_a = make_checkpoint()
        cp_b = make_checkpoint()
        assert cp_a.checkpoint_id != cp_b.checkpoint_id

    def test_create_sets_created_at(self):
        """create() sets created_at to current UTC time."""
        before = datetime.now(timezone.utc)
        cp     = make_checkpoint()
        after  = datetime.now(timezone.utc)
        assert before <= cp.created_at <= after


# ── WorkflowCheckpoint transitions (immutable) ───────────────

class TestWorkflowCheckpointTransitions:
    """
    Transition methods return new checkpoints — they never mutate in place.
    """

    def test_mark_task_complete_returns_new_checkpoint(self):
        """mark_task_complete() returns a new object, not mutating self."""
        cp     = make_checkpoint(pending_tasks=["ST-01", "ST-02"])
        result = make_agent_result("ST-01")
        updated = cp.mark_task_complete("ST-01", result, cost_usd=0.02)
        assert updated is not cp

    def test_mark_task_complete_moves_task_to_completed(self):
        """Completed task moves from pending_tasks to completed_tasks."""
        cp     = make_checkpoint(pending_tasks=["ST-01", "ST-02"])
        result = make_agent_result("ST-01")
        updated = cp.mark_task_complete("ST-01", result, cost_usd=0.02)

        assert "ST-01" in updated.completed_tasks
        assert "ST-01" not in updated.pending_tasks
        assert "ST-02" in updated.pending_tasks

    def test_mark_task_complete_accumulates_cost(self):
        """Each mark_task_complete adds to budget_spent."""
        cp = make_checkpoint(pending_tasks=["ST-01", "ST-02"])

        cp = cp.mark_task_complete("ST-01", make_agent_result("ST-01"), 0.03)
        cp = cp.mark_task_complete("ST-02", make_agent_result("ST-02"), 0.05)

        assert cp.budget_spent == pytest.approx(0.08)

    def test_mark_task_complete_preserves_original(self):
        """Original checkpoint is unchanged after mark_task_complete."""
        cp      = make_checkpoint(pending_tasks=["ST-01"])
        original_pending = list(cp.pending_tasks)
        cp.mark_task_complete("ST-01", make_agent_result("ST-01"))

        assert cp.pending_tasks == original_pending
        assert "ST-01" not in cp.completed_tasks

    def test_mark_awaiting_hitl_updates_state(self):
        """mark_awaiting_hitl() sets state to AWAITING_HITL."""
        cp      = make_checkpoint()
        updated = cp.mark_awaiting_hitl("ST-03")

        assert updated.state          == CheckpointState.AWAITING_HITL
        assert updated.paused_at_task == "ST-03"

    def test_mark_awaiting_hitl_stores_review_id(self):
        """mark_awaiting_hitl() stores review_id in metadata."""
        cp      = make_checkpoint()
        updated = cp.mark_awaiting_hitl("ST-03", review_id="rev-abc-123")

        assert updated.metadata["review_id"] == "rev-abc-123"

    def test_mark_resuming_updates_state(self):
        """mark_resuming() sets state to RESUMING."""
        cp = make_checkpoint()
        cp = cp.mark_awaiting_hitl("ST-03")
        cp = cp.mark_resuming()

        assert cp.state == CheckpointState.RESUMING

    def test_mark_completed_clears_pending_tasks(self):
        """mark_completed() clears pending_tasks and sets COMPLETED state."""
        cp = make_checkpoint(pending_tasks=["ST-01"])
        cp = cp.mark_completed()

        assert cp.state         == CheckpointState.COMPLETED
        assert cp.pending_tasks == []

    def test_mark_failed_sets_state_and_reason(self):
        """mark_failed() sets FAILED state and stores failure reason."""
        cp      = make_checkpoint()
        updated = cp.mark_failed(reason="DB connection lost", failed_task="ST-02")

        assert updated.state                       == CheckpointState.FAILED
        assert updated.metadata["failure_reason"]  == "DB connection lost"
        assert updated.metadata["failed_task"]     == "ST-02"

    def test_updated_at_changes_on_transition(self):
        """updated_at is refreshed on every transition."""
        cp          = make_checkpoint()
        original_ts = cp.updated_at
        import time; time.sleep(0.01)  # ensure time difference
        updated     = cp.mark_task_complete("ST-01", make_agent_result("ST-01"))

        assert updated.updated_at >= original_ts


# ── InMemoryCheckpointStore ───────────────────────────────────

class TestInMemoryCheckpointStore:

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Saved checkpoint can be loaded by request_id."""
        store = InMemoryCheckpointStore()
        cp    = make_checkpoint()

        await store.save(cp)
        loaded = await store.load(cp.request_id)

        assert loaded is not None
        assert loaded.checkpoint_id == cp.checkpoint_id
        assert loaded.request_id    == cp.request_id

    @pytest.mark.asyncio
    async def test_load_returns_none_for_unknown(self):
        """load() returns None for unknown request_id."""
        store  = InMemoryCheckpointStore()
        result = await store.load(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self):
        """Saving again overwrites the existing checkpoint."""
        store  = InMemoryCheckpointStore()
        cp     = make_checkpoint()
        await store.save(cp)

        updated = cp.mark_task_complete("ST-01", make_agent_result("ST-01"))
        await store.save(updated)

        loaded = await store.load(cp.request_id)
        assert "ST-01" in loaded.completed_tasks

    @pytest.mark.asyncio
    async def test_delete_removes_checkpoint(self):
        """delete() removes the checkpoint."""
        store = InMemoryCheckpointStore()
        cp    = make_checkpoint()
        await store.save(cp)

        deleted = await store.delete(cp.request_id)
        assert deleted is True

        loaded = await store.load(cp.request_id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_unknown(self):
        """delete() returns False for unknown request_id."""
        store   = InMemoryCheckpointStore()
        deleted = await store.delete(uuid.uuid4())
        assert deleted is False

    @pytest.mark.asyncio
    async def test_exists_returns_true_when_saved(self):
        store = InMemoryCheckpointStore()
        cp    = make_checkpoint()
        await store.save(cp)
        assert await store.exists(cp.request_id) is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_unknown(self):
        store = InMemoryCheckpointStore()
        assert await store.exists(uuid.uuid4()) is False

    @pytest.mark.asyncio
    async def test_exists_returns_false_after_delete(self):
        store = InMemoryCheckpointStore()
        cp    = make_checkpoint()
        await store.save(cp)
        await store.delete(cp.request_id)
        assert await store.exists(cp.request_id) is False

    def test_clear_removes_all(self):
        """clear() removes all checkpoints."""
        store = InMemoryCheckpointStore()
        # Cannot use async in sync test — add directly
        store._checkpoints[uuid.uuid4()] = make_checkpoint()
        store._checkpoints[uuid.uuid4()] = make_checkpoint()
        assert len(store) == 2
        store.clear()
        assert len(store) == 0

    def test_len_returns_count(self):
        store = InMemoryCheckpointStore()
        assert len(store) == 0

    def test_repr_includes_count(self):
        store = InMemoryCheckpointStore()
        assert "0" in repr(store)


# ── Resume Scenario ──────────────────────────────────────────

class TestCheckpointResumeScenario:
    """
    Simulate the resume workflow: save checkpoints as tasks complete,
    then load and resume from the last saved state.
    """

    @pytest.mark.asyncio
    async def test_resume_from_partial_execution(self):
        """
        Simulate a crash after ST-01 and ST-02 complete.
        On resume, only ST-03 remains in pending_tasks.
        """
        store  = InMemoryCheckpointStore()
        req_id = uuid.uuid4()
        cp     = WorkflowCheckpoint.create(
            request_id=req_id,
            grant_id=uuid.uuid4(),
            pending_tasks=["ST-01", "ST-02", "ST-03"],
        )

        # Execute ST-01
        cp = cp.mark_task_complete("ST-01", make_agent_result("ST-01"), 0.02)
        await store.save(cp)

        # Execute ST-02
        cp = cp.mark_task_complete("ST-02", make_agent_result("ST-02"), 0.03)
        await store.save(cp)

        # "Crash" — load checkpoint to simulate resume
        loaded = await store.load(req_id)

        assert loaded is not None
        assert "ST-01" in loaded.completed_tasks
        assert "ST-02" in loaded.completed_tasks
        assert loaded.pending_tasks == ["ST-03"]
        assert loaded.budget_spent == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_hitl_suspend_and_resume(self):
        """
        Simulate HITL gate suspension at ST-03 and resumption.
        """
        store  = InMemoryCheckpointStore()
        req_id = uuid.uuid4()
        cp     = WorkflowCheckpoint.create(
            request_id=req_id,
            grant_id=uuid.uuid4(),
            pending_tasks=["ST-01", "ST-02", "ST-03"],
        )

        # Complete ST-01 and ST-02
        cp = cp.mark_task_complete("ST-01", make_agent_result("ST-01"), 0.02)
        cp = cp.mark_task_complete("ST-02", make_agent_result("ST-02"), 0.03)

        # HITL gate triggers at ST-03
        cp = cp.mark_awaiting_hitl("ST-03", review_id="review-xyz")
        await store.save(cp)

        # Verify suspended state
        loaded = await store.load(req_id)
        assert loaded.state          == CheckpointState.AWAITING_HITL
        assert loaded.paused_at_task == "ST-03"
        assert loaded.metadata["review_id"] == "review-xyz"

        # Human approves — resume
        cp = loaded.mark_resuming()
        await store.save(cp)

        loaded_again = await store.load(req_id)
        assert loaded_again.state == CheckpointState.RESUMING

    @pytest.mark.asyncio
    async def test_completed_workflow_checkpoint_deleted(self):
        """
        On workflow completion, checkpoint is deleted.
        After deletion, load() returns None.
        """
        store  = InMemoryCheckpointStore()
        req_id = uuid.uuid4()
        cp     = WorkflowCheckpoint.create(
            request_id=req_id,
            grant_id=uuid.uuid4(),
            pending_tasks=["ST-01"],
        )

        cp = cp.mark_task_complete("ST-01", make_agent_result("ST-01"))
        cp = cp.mark_completed()
        await store.save(cp)

        # Workflow complete — delete checkpoint
        await store.delete(req_id)

        # No checkpoint remains
        assert await store.load(req_id) is None


# ── CheckpointStore Interface ─────────────────────────────────

class TestCheckpointStoreInterface:

    def test_checkpoint_store_is_abstract(self):
        """CheckpointStore cannot be instantiated directly."""
        with pytest.raises(TypeError):
            CheckpointStore()

    def test_in_memory_is_subclass(self):
        assert issubclass(InMemoryCheckpointStore, CheckpointStore)

    def test_checkpoint_store_error_fields(self):
        err = CheckpointStoreError("save", "Redis unavailable")
        assert err.operation == "save"
        assert err.reason    == "Redis unavailable"
        assert "save" in str(err)
