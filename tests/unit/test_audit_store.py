"""
Unit tests for AuditRecord, AuditEventType, and InMemoryAuditStore.

All tests use InMemoryAuditStore — no PostgreSQL/Docker required.
PostgresAuditStore is tested in integration tests (Step 10 integration).

Coverage:
  - AuditRecord construction and immutability
  - AuditRecord.make() factory method
  - AuditEventType constants completeness
  - InMemoryAuditStore write, query, count, clear
  - Duplicate write protection
  - Query filtering by event_type
  - Chronological ordering
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone

from daf.models.audit_record import AuditRecord, AuditEventType
from daf.runtime.audit_store import (
    InMemoryAuditStore, AuditStore, AuditStoreError,
)


# ── Fixtures ─────────────────────────────────────────────────

def make_record(
    request_id: uuid.UUID | None = None,
    event_type: str = AuditEventType.WORKFLOW_STARTED,
    tenant_id:  str = "test-tenant",
    user_id:    str = "test-user",
    payload:    dict | None = None,
) -> AuditRecord:
    return AuditRecord.make(
        request_id=request_id or uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        payload=payload,
    )


# ── AuditEventType ───────────────────────────────────────────

class TestAuditEventType:

    def test_all_constants_are_strings(self):
        """Every event type constant is a non-empty string."""
        for event_type in AuditEventType.ALL:
            assert isinstance(event_type, str)
            assert len(event_type) > 0

    def test_all_frozenset_contains_known_types(self):
        """ALL frozenset includes the core workflow event types."""
        assert AuditEventType.WORKFLOW_STARTED   in AuditEventType.ALL
        assert AuditEventType.WORKFLOW_COMPLETED in AuditEventType.ALL
        assert AuditEventType.WORKFLOW_ESCALATED in AuditEventType.ALL
        assert AuditEventType.PLAN_PROPOSED      in AuditEventType.ALL
        assert AuditEventType.PLAN_EVALUATED     in AuditEventType.ALL
        assert AuditEventType.EXECUTION_STARTED  in AuditEventType.ALL
        assert AuditEventType.STEP_STARTED       in AuditEventType.ALL
        assert AuditEventType.STEP_COMPLETED     in AuditEventType.ALL
        assert AuditEventType.STEP_FAILED        in AuditEventType.ALL

    def test_no_duplicate_values(self):
        """All event type constants have distinct values."""
        values = [
            v for k, v in vars(AuditEventType).items()
            if not k.startswith("_") and isinstance(v, str)
        ]
        assert len(values) == len(set(values)), (
            "Duplicate event type values detected"
        )


# ── AuditRecord ──────────────────────────────────────────────

class TestAuditRecord:

    def test_make_creates_record_with_correct_fields(self):
        """AuditRecord.make() sets all fields correctly."""
        req_id = uuid.uuid4()
        record = AuditRecord.make(
            request_id=req_id,
            tenant_id="acme",
            user_id="alice",
            event_type=AuditEventType.WORKFLOW_STARTED,
            payload={"task": "analyse contracts"},
        )
        assert record.request_id == req_id
        assert record.tenant_id  == "acme"
        assert record.user_id    == "alice"
        assert record.event_type == "workflow_started"
        assert record.payload["task"] == "analyse contracts"

    def test_make_generates_unique_audit_id(self):
        """Each call to make() produces a unique audit_id."""
        req_id = uuid.uuid4()
        record_a = make_record(request_id=req_id)
        record_b = make_record(request_id=req_id)
        assert record_a.audit_id != record_b.audit_id

    def test_make_sets_created_at_to_now(self):
        """created_at is set to current UTC time."""
        before = datetime.now(timezone.utc)
        record = make_record()
        after  = datetime.now(timezone.utc)
        assert before <= record.created_at <= after

    def test_make_empty_payload_defaults_to_empty_dict(self):
        """payload defaults to {} when not provided."""
        record = AuditRecord.make(
            request_id=uuid.uuid4(),
            tenant_id="t", user_id="u",
            event_type=AuditEventType.PLAN_PROPOSED,
        )
        assert record.payload == {}

    def test_record_is_immutable(self):
        """AuditRecord is frozen — fields cannot be modified after creation."""
        record = make_record()
        with pytest.raises(Exception):   # pydantic ValidationError or TypeError
            record.event_type = "modified"   # type: ignore

    def test_custom_event_type_allowed(self):
        """Custom event types (not in AuditEventType.ALL) are accepted."""
        record = make_record(event_type="custom_tool_invoked")
        assert record.event_type == "custom_tool_invoked"


# ── InMemoryAuditStore ───────────────────────────────────────

class TestInMemoryAuditStore:

    @pytest.mark.asyncio
    async def test_write_and_query(self):
        """Written record can be retrieved by request_id."""
        store     = InMemoryAuditStore()
        req_id    = uuid.uuid4()
        record    = make_record(request_id=req_id,
                                event_type=AuditEventType.WORKFLOW_STARTED)

        await store.write(record)
        results = await store.query(request_id=req_id)

        assert len(results) == 1
        assert results[0].audit_id    == record.audit_id
        assert results[0].event_type  == AuditEventType.WORKFLOW_STARTED

    @pytest.mark.asyncio
    async def test_query_returns_only_matching_request(self):
        """query() returns only records for the given request_id."""
        store    = InMemoryAuditStore()
        req_a    = uuid.uuid4()
        req_b    = uuid.uuid4()

        await store.write(make_record(request_id=req_a))
        await store.write(make_record(request_id=req_b))
        await store.write(make_record(request_id=req_a))

        results_a = await store.query(request_id=req_a)
        results_b = await store.query(request_id=req_b)

        assert len(results_a) == 2
        assert len(results_b) == 1

    @pytest.mark.asyncio
    async def test_query_filters_by_event_type(self):
        """query() with event_type returns only matching records."""
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()

        await store.write(make_record(req_id, AuditEventType.WORKFLOW_STARTED))
        await store.write(make_record(req_id, AuditEventType.PLAN_PROPOSED))
        await store.write(make_record(req_id, AuditEventType.PLAN_EVALUATED))
        await store.write(make_record(req_id, AuditEventType.WORKFLOW_COMPLETED))

        plan_records = await store.query(
            request_id=req_id,
            event_type=AuditEventType.PLAN_PROPOSED,
        )
        assert len(plan_records) == 1
        assert plan_records[0].event_type == AuditEventType.PLAN_PROPOSED

    @pytest.mark.asyncio
    async def test_query_returns_in_write_order(self):
        """Records are returned in the order they were written."""
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()

        events = [
            AuditEventType.WORKFLOW_STARTED,
            AuditEventType.PLAN_PROPOSED,
            AuditEventType.PLAN_EVALUATED,
            AuditEventType.EXECUTION_STARTED,
            AuditEventType.WORKFLOW_COMPLETED,
        ]
        for event in events:
            await store.write(make_record(req_id, event))

        results = await store.query(req_id)
        assert [r.event_type for r in results] == events

    @pytest.mark.asyncio
    async def test_count_returns_correct_number(self):
        """count() returns number of records for a workflow."""
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()

        for _ in range(5):
            await store.write(make_record(request_id=req_id))

        assert await store.count(req_id) == 5

    @pytest.mark.asyncio
    async def test_count_zero_for_unknown_request(self):
        """count() returns 0 for unknown request_id."""
        store = InMemoryAuditStore()
        assert await store.count(uuid.uuid4()) == 0

    @pytest.mark.asyncio
    async def test_duplicate_write_raises(self):
        """Writing the same audit_id twice raises AuditStoreError."""
        store  = InMemoryAuditStore()
        record = make_record()

        await store.write(record)

        with pytest.raises(AuditStoreError, match="already exists"):
            await store.write(record)   # same object = same audit_id

    @pytest.mark.asyncio
    async def test_duplicate_write_does_not_corrupt_store(self):
        """After a duplicate write error, the store is in a consistent state."""
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()
        record = make_record(request_id=req_id)

        await store.write(record)
        try:
            await store.write(record)
        except AuditStoreError:
            pass

        # Store should still have exactly one record
        results = await store.query(req_id)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_clear_removes_all_records(self):
        """clear() removes all records from the store."""
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()

        for _ in range(3):
            await store.write(make_record(request_id=req_id))

        store.clear()

        assert len(store) == 0
        results = await store.query(req_id)
        assert results == []

    @pytest.mark.asyncio
    async def test_all_records_returns_everything(self):
        """all_records() returns all records regardless of request_id."""
        store = InMemoryAuditStore()
        req_a = uuid.uuid4()
        req_b = uuid.uuid4()

        await store.write(make_record(request_id=req_a))
        await store.write(make_record(request_id=req_b))

        all_r = store.all_records()
        assert len(all_r) == 2

    def test_len_returns_total_count(self):
        """len(store) returns total number of records."""
        store = InMemoryAuditStore()
        assert len(store) == 0

    def test_repr_includes_record_count(self):
        """repr() includes record count."""
        store = InMemoryAuditStore()
        assert "0" in repr(store)

    @pytest.mark.asyncio
    async def test_query_empty_returns_empty_list(self):
        """query() for unknown request_id returns empty list."""
        store = InMemoryAuditStore()
        results = await store.query(uuid.uuid4())
        assert results == []

    @pytest.mark.asyncio
    async def test_payload_preserved_exactly(self):
        """Payload dict is stored and retrieved exactly."""
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()
        payload = {
            "proposal_id": str(uuid.uuid4()),
            "sub_tasks":   3,
            "cost_usd":    0.047,
            "nested":      {"key": "value"},
        }
        record = make_record(request_id=req_id, payload=payload)
        await store.write(record)

        results = await store.query(req_id)
        assert results[0].payload == payload


# ── AuditStore Interface ─────────────────────────────────────

class TestAuditStoreInterface:

    def test_audit_store_is_abstract(self):
        """AuditStore cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AuditStore()

    def test_in_memory_is_subclass(self):
        """InMemoryAuditStore is a subclass of AuditStore."""
        assert issubclass(InMemoryAuditStore, AuditStore)

    def test_audit_store_error_has_operation_and_reason(self):
        """AuditStoreError stores operation and reason."""
        err = AuditStoreError("write", "connection lost")
        assert err.operation == "write"
        assert err.reason    == "connection lost"
        assert "write"         in str(err)
        assert "connection lost" in str(err)


# ── Full Workflow Audit Scenario ─────────────────────────────

class TestAuditStoreWorkflowScenario:
    """
    End-to-end scenario: record the full event sequence for a workflow.
    Verifies that all expected events are captured and retrievable.
    """

    @pytest.mark.asyncio
    async def test_full_workflow_audit_trail(self):
        """
        Simulate writing audit records for a complete workflow.
        Verify the full trail is retrievable in order.
        """
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()

        # Simulate a complete successful workflow
        events = [
            (AuditEventType.WORKFLOW_STARTED,   {"task": "analyse contracts"}),
            (AuditEventType.PLAN_PROPOSED,       {"iteration": 1, "sub_tasks": 3}),
            (AuditEventType.PLAN_EVALUATED,      {"verdict": "APPROVED", "gated": 0}),
            (AuditEventType.EXECUTION_STARTED,   {"grant_id": str(uuid.uuid4())}),
            (AuditEventType.STEP_STARTED,        {"task_id": "ST-01"}),
            (AuditEventType.STEP_COMPLETED,      {"task_id": "ST-01", "cost": 0.02}),
            (AuditEventType.STEP_STARTED,        {"task_id": "ST-02"}),
            (AuditEventType.STEP_COMPLETED,      {"task_id": "ST-02", "cost": 0.03}),
            (AuditEventType.WORKFLOW_COMPLETED,  {"outcome": "completed", "total_cost": 0.05}),
        ]

        for event_type, payload in events:
            await store.write(AuditRecord.make(
                request_id=req_id,
                tenant_id="acme",
                user_id="alice",
                event_type=event_type,
                payload=payload,
            ))

        # Retrieve full trail
        trail = await store.query(req_id)
        assert len(trail) == len(events)
        assert trail[0].event_type == AuditEventType.WORKFLOW_STARTED
        assert trail[-1].event_type == AuditEventType.WORKFLOW_COMPLETED

        # Verify step records
        step_records = await store.query(
            req_id, event_type=AuditEventType.STEP_COMPLETED
        )
        assert len(step_records) == 2

        # Verify count
        assert await store.count(req_id) == len(events)

    @pytest.mark.asyncio
    async def test_escalated_workflow_audit_trail(self):
        """
        Simulate writing audit records for an escalated workflow.
        """
        store  = InMemoryAuditStore()
        req_id = uuid.uuid4()

        await store.write(make_record(req_id, AuditEventType.WORKFLOW_STARTED))
        await store.write(make_record(req_id, AuditEventType.PLAN_PROPOSED))
        await store.write(make_record(req_id, AuditEventType.PLAN_EVALUATED,
                                      payload={"verdict": "REJECTED"}))
        await store.write(make_record(req_id, AuditEventType.PLAN_PROPOSED,
                                      payload={"iteration": 2}))
        await store.write(make_record(req_id, AuditEventType.PLAN_EVALUATED,
                                      payload={"verdict": "REJECTED"}))
        await store.write(make_record(req_id, AuditEventType.WORKFLOW_ESCALATED))

        trail = await store.query(req_id)
        assert len(trail) == 6
        assert trail[-1].event_type == AuditEventType.WORKFLOW_ESCALATED

        # Two rejections in the trail
        evaluations = await store.query(
            req_id, event_type=AuditEventType.PLAN_EVALUATED
        )
        assert len(evaluations) == 2
        assert all(r.payload["verdict"] == "REJECTED" for r in evaluations)
