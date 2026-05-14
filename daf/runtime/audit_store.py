"""
AuditStore — append-only audit trail storage.

Two implementations:
  InMemoryAuditStore:   for unit tests — no infrastructure needed
  PostgresAuditStore:   for production — requires PostgreSQL

DESIGN INVARIANT (from design-philosophy.md, Principle 4):
  The audit trail is immutable. write() appends — it never updates.
  The PostgreSQL implementation revokes UPDATE and DELETE at the DB level.
  The InMemory implementation raises if you try to modify existing records.

USAGE:
    # Unit tests
    store = InMemoryAuditStore()
    await store.write(AuditRecord.make(
        request_id=request.request_id,
        tenant_id="acme",
        user_id="alice",
        event_type=AuditEventType.WORKFLOW_STARTED,
        payload={"task": request.task_description},
    ))
    records = await store.query(request_id=request.request_id)

    # Production (ExecutionOrchestrator)
    store = PostgresAuditStore(dsn=os.getenv("POSTGRES_URL"))
    await store.connect()
    await store.write(record)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any
import uuid

from daf.models.audit_record import AuditRecord

logger = logging.getLogger(__name__)


# ── Abstract interface ───────────────────────────────────────

class AuditStore(ABC):
    """
    Abstract interface for audit trail storage.

    Implementations must be append-only.
    write() must never modify existing records.
    """

    @abstractmethod
    async def write(self, record: AuditRecord) -> None:
        """
        Append an audit record to the store.

        Must be atomic — either the record is written or it is not.
        Must never modify existing records.

        Args:
            record: The AuditRecord to persist

        Raises:
            AuditStoreError: on write failure
        """
        ...

    @abstractmethod
    async def query(
        self,
        request_id: uuid.UUID,
        event_type: str | None = None,
    ) -> list[AuditRecord]:
        """
        Retrieve audit records for a workflow.

        Args:
            request_id: The WorkflowRequest UUID to query
            event_type: Optional filter by event type

        Returns:
            List of AuditRecord in chronological order (oldest first)
        """
        ...

    @abstractmethod
    async def count(self, request_id: uuid.UUID) -> int:
        """Return the number of records for a workflow."""
        ...


# ── Exception ────────────────────────────────────────────────

class AuditStoreError(Exception):
    """Raised when an AuditStore operation fails."""
    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(f"AuditStore.{operation}() failed: {reason}")
        self.operation = operation
        self.reason    = reason


# ── InMemoryAuditStore ───────────────────────────────────────

class InMemoryAuditStore(AuditStore):
    """
    In-memory audit store for unit tests.

    Stores records in a list. No infrastructure required.
    Thread-safe for sequential tests (not concurrent writes).

    Records are stored in order of write() calls.
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._audit_ids: set[uuid.UUID]  = set()

    async def write(self, record: AuditRecord) -> None:
        """
        Append a record.
        Raises AuditStoreError if audit_id already exists
        (duplicate write protection — mirrors PostgreSQL UNIQUE constraint).
        """
        if record.audit_id in self._audit_ids:
            raise AuditStoreError(
                "write",
                f"audit_id {record.audit_id} already exists. "
                f"Audit records are immutable and cannot be re-written."
            )
        self._records.append(record)
        self._audit_ids.add(record.audit_id)
        logger.debug(
            f"AuditStore.write: "
            f"event={record.event_type} "
            f"request_id={record.request_id}"
        )

    async def query(
        self,
        request_id: uuid.UUID,
        event_type: str | None = None,
    ) -> list[AuditRecord]:
        """Return records for a workflow, optionally filtered by event_type."""
        results = [
            r for r in self._records
            if r.request_id == request_id
        ]
        if event_type is not None:
            results = [r for r in results if r.event_type == event_type]
        return results

    async def count(self, request_id: uuid.UUID) -> int:
        """Return count of records for a workflow."""
        return sum(1 for r in self._records if r.request_id == request_id)

    def all_records(self) -> list[AuditRecord]:
        """Return all records (for test inspection — not part of AuditStore API)."""
        return list(self._records)

    def clear(self) -> None:
        """Clear all records (for test teardown)."""
        self._records.clear()
        self._audit_ids.clear()

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return f"InMemoryAuditStore(records={len(self._records)})"
