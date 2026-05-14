"""
PostgresAuditStore — production PostgreSQL audit trail implementation.

Requires:
  - asyncpg package: pip install asyncpg
  - PostgreSQL running (make services-up)
  - Table created: scripts/init.sql

The audit_records table has UPDATE and DELETE revoked
at the database level — append-only is enforced in the DB,
not just in application code.

USAGE:
    store = PostgresAuditStore(dsn=os.getenv("POSTGRES_URL"))
    await store.connect()
    await store.write(record)
    await store.disconnect()

    # Or as an async context manager:
    async with PostgresAuditStore.connect_ctx(dsn) as store:
        await store.write(record)
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from daf.models.audit_record import AuditRecord
from daf.runtime.audit_store import AuditStore, AuditStoreError

logger = logging.getLogger(__name__)

_INSERT_SQL = """
    INSERT INTO audit_records
        (audit_id, request_id, tenant_id, user_id, event_type, payload, created_at)
    VALUES
        ($1, $2, $3, $4, $5, $6, $7)
"""

_QUERY_SQL = """
    SELECT audit_id, request_id, tenant_id, user_id,
           event_type, payload, created_at
    FROM audit_records
    WHERE request_id = $1
    {event_filter}
    ORDER BY created_at ASC, id ASC
"""

_COUNT_SQL = """
    SELECT COUNT(*) FROM audit_records WHERE request_id = $1
"""


class PostgresAuditStore(AuditStore):
    """
    Production audit store backed by PostgreSQL.

    Uses asyncpg for async PostgreSQL access.
    Connection pool is created on connect() and released on disconnect().
    """

    def __init__(self, dsn: str) -> None:
        """
        Args:
            dsn: PostgreSQL connection string
                 e.g. "postgresql://daf:daf@localhost:5432/daf"
        """
        self._dsn:  str      = dsn
        self._pool: Any      = None   # asyncpg pool

    async def connect(self) -> None:
        """
        Create the connection pool.
        Must be called before write() or query().
        """
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=1,
                max_size=10,
                command_timeout=30,
            )
            logger.info("PostgresAuditStore connected")
        except ImportError as e:
            raise AuditStoreError(
                "connect",
                "asyncpg package not installed. Run: pip install asyncpg"
            ) from e
        except Exception as e:
            raise AuditStoreError("connect", str(e)) from e

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("PostgresAuditStore disconnected")

    @classmethod
    @asynccontextmanager
    async def connect_ctx(
        cls, dsn: str
    ) -> AsyncGenerator[PostgresAuditStore, None]:
        """Async context manager for automatic connect/disconnect."""
        store = cls(dsn=dsn)
        await store.connect()
        try:
            yield store
        finally:
            await store.disconnect()

    async def write(self, record: AuditRecord) -> None:
        """
        Append an audit record to PostgreSQL.

        Raises AuditStoreError on failure.
        Raises AuditStoreError if audit_id already exists
        (PostgreSQL UNIQUE constraint on audit_id).
        """
        self._ensure_connected()
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    _INSERT_SQL,
                    record.audit_id,
                    record.request_id,
                    record.tenant_id,
                    record.user_id,
                    record.event_type,
                    json.dumps(record.payload),
                    record.created_at,
                )
            logger.debug(
                f"AuditStore.write: "
                f"event={record.event_type} "
                f"request_id={record.request_id}"
            )
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise AuditStoreError(
                    "write",
                    f"audit_id {record.audit_id} already exists"
                ) from e
            raise AuditStoreError("write", str(e)) from e

    async def query(
        self,
        request_id: uuid.UUID,
        event_type: str | None = None,
    ) -> list[AuditRecord]:
        """
        Retrieve audit records for a workflow.
        Returns records in chronological order.
        """
        self._ensure_connected()
        try:
            event_filter = (
                f"AND event_type = '{event_type}'"
                if event_type else ""
            )
            sql = _QUERY_SQL.format(event_filter=event_filter)

            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, request_id)

            return [
                AuditRecord(
                    audit_id   = row["audit_id"],
                    request_id = row["request_id"],
                    tenant_id  = row["tenant_id"],
                    user_id    = row["user_id"],
                    event_type = row["event_type"],
                    payload    = (
                        json.loads(row["payload"])
                        if isinstance(row["payload"], str)
                        else dict(row["payload"])
                    ),
                    created_at = row["created_at"],
                )
                for row in rows
            ]
        except AuditStoreError:
            raise
        except Exception as e:
            raise AuditStoreError("query", str(e)) from e

    async def count(self, request_id: uuid.UUID) -> int:
        """Return count of records for a workflow."""
        self._ensure_connected()
        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetchval(_COUNT_SQL, request_id)
            return int(result)
        except Exception as e:
            raise AuditStoreError("count", str(e)) from e

    def _ensure_connected(self) -> None:
        """Raise AuditStoreError if not connected."""
        if self._pool is None:
            raise AuditStoreError(
                "operation",
                "Not connected. Call connect() before using the store."
            )

    def __repr__(self) -> str:
        connected = self._pool is not None
        return f"PostgresAuditStore(connected={connected})"
