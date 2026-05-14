"""
CheckpointStore — workflow execution state storage.

Two implementations:
  InMemoryCheckpointStore: for unit tests — no infrastructure needed
  RedisCheckpointStore:    for production — requires Redis

DESIGN CONTRAST WITH AUDITSTORE:
  AuditStore:      append-only, permanent history, records accumulate
  CheckpointStore: mutable, temporary state, one record per workflow

The checkpoint is the execution state. The audit trail is the history.
Both are needed. They serve different purposes.

CHECKPOINT LIFECYCLE:
  1. create()    — ExecutionOrchestrator starts execution
  2. save()      — after each completed sub-task
  3. save()      — when HITL gate triggers (state=awaiting_hitl)
  4. save()      — when HITL resumes (state=resuming)
  5. delete()    — on workflow completion (no longer needed)
  6. (preserved) — on failure (enables retry/resume)

RESUME PATTERN:
  checkpoint = await store.load(request_id)
  if checkpoint and checkpoint.pending_tasks:
      # Resume from checkpoint — skip completed tasks
      remaining = checkpoint.pending_tasks
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any
import uuid

from daf.models.workflow_checkpoint import WorkflowCheckpoint

logger = logging.getLogger(__name__)


# ── Exception ────────────────────────────────────────────────

class CheckpointStoreError(Exception):
    """Raised when a CheckpointStore operation fails."""
    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(f"CheckpointStore.{operation}() failed: {reason}")
        self.operation = operation
        self.reason    = reason


# ── Abstract interface ───────────────────────────────────────

class CheckpointStore(ABC):
    """
    Abstract interface for workflow execution state storage.

    Unlike AuditStore, checkpoints are mutable — save() overwrites
    the existing checkpoint for a request_id.
    """

    @abstractmethod
    async def save(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        Save (create or overwrite) a workflow checkpoint.

        Args:
            checkpoint: The WorkflowCheckpoint to persist

        Raises:
            CheckpointStoreError: on write failure
        """
        ...

    @abstractmethod
    async def load(
        self,
        request_id: uuid.UUID,
    ) -> WorkflowCheckpoint | None:
        """
        Load a checkpoint by request_id.

        Args:
            request_id: The WorkflowRequest UUID

        Returns:
            The WorkflowCheckpoint if found, None if not found
        """
        ...

    @abstractmethod
    async def delete(self, request_id: uuid.UUID) -> bool:
        """
        Delete a checkpoint.

        Args:
            request_id: The WorkflowRequest UUID

        Returns:
            True if deleted, False if not found
        """
        ...

    @abstractmethod
    async def exists(self, request_id: uuid.UUID) -> bool:
        """Return True if a checkpoint exists for request_id."""
        ...


# ── InMemoryCheckpointStore ──────────────────────────────────

class InMemoryCheckpointStore(CheckpointStore):
    """
    In-memory checkpoint store for unit tests.

    Stores checkpoints in a dict keyed by request_id.
    No infrastructure required.
    """

    def __init__(self) -> None:
        self._checkpoints: dict[uuid.UUID, WorkflowCheckpoint] = {}

    async def save(self, checkpoint: WorkflowCheckpoint) -> None:
        """Save or overwrite a checkpoint."""
        self._checkpoints[checkpoint.request_id] = checkpoint
        logger.debug(
            f"Checkpoint saved: "
            f"request_id={checkpoint.request_id} "
            f"state={checkpoint.state} "
            f"pending={len(checkpoint.pending_tasks)}"
        )

    async def load(
        self,
        request_id: uuid.UUID,
    ) -> WorkflowCheckpoint | None:
        """Load a checkpoint by request_id. Returns None if not found."""
        return self._checkpoints.get(request_id)

    async def delete(self, request_id: uuid.UUID) -> bool:
        """Delete a checkpoint. Returns True if deleted, False if not found."""
        if request_id in self._checkpoints:
            del self._checkpoints[request_id]
            logger.debug(f"Checkpoint deleted: request_id={request_id}")
            return True
        return False

    async def exists(self, request_id: uuid.UUID) -> bool:
        """Return True if a checkpoint exists."""
        return request_id in self._checkpoints

    def clear(self) -> None:
        """Clear all checkpoints (for test teardown)."""
        self._checkpoints.clear()

    def __len__(self) -> int:
        return len(self._checkpoints)

    def __repr__(self) -> str:
        return f"InMemoryCheckpointStore(checkpoints={len(self._checkpoints)})"


# ── RedisCheckpointStore ─────────────────────────────────────

class RedisCheckpointStore(CheckpointStore):
    """
    Production checkpoint store backed by Redis.

    Uses redis-py async client.
    Checkpoints are stored as JSON strings keyed by request_id.
    Optional TTL to auto-expire stale checkpoints.

    USAGE:
        store = RedisCheckpointStore(
            url="redis://localhost:6379/0",
            ttl_seconds=86400,   # 24 hours
        )
        await store.connect()
        await store.save(checkpoint)
        checkpoint = await store.load(request_id)
        await store.disconnect()
    """

    _KEY_PREFIX = "daf:checkpoint:"

    def __init__(
        self,
        url:         str,
        ttl_seconds: int | None = 86400,  # 24 hours default
    ) -> None:
        self._url:         str         = url
        self._ttl:         int | None  = ttl_seconds
        self._client:      Any         = None

    async def connect(self) -> None:
        """Create the Redis client connection."""
        try:
            import redis.asyncio as aioredis
            self._client = await aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._client.ping()
            logger.info("RedisCheckpointStore connected")
        except ImportError as e:
            raise CheckpointStoreError(
                "connect",
                "redis package not installed. Run: pip install redis"
            ) from e
        except Exception as e:
            raise CheckpointStoreError("connect", str(e)) from e

    async def disconnect(self) -> None:
        """Close the Redis client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("RedisCheckpointStore disconnected")

    def _key(self, request_id: uuid.UUID) -> str:
        return f"{self._KEY_PREFIX}{request_id}"

    async def save(self, checkpoint: WorkflowCheckpoint) -> None:
        """Save checkpoint to Redis as JSON. Overwrites if exists."""
        self._ensure_connected()
        try:
            key  = self._key(checkpoint.request_id)
            data = checkpoint.model_dump_json()

            if self._ttl:
                await self._client.setex(key, self._ttl, data)
            else:
                await self._client.set(key, data)

            logger.debug(
                f"Checkpoint saved: "
                f"request_id={checkpoint.request_id} "
                f"state={checkpoint.state}"
            )
        except Exception as e:
            raise CheckpointStoreError("save", str(e)) from e

    async def load(
        self,
        request_id: uuid.UUID,
    ) -> WorkflowCheckpoint | None:
        """Load checkpoint from Redis. Returns None if not found."""
        self._ensure_connected()
        try:
            key  = self._key(request_id)
            data = await self._client.get(key)
            if data is None:
                return None
            return WorkflowCheckpoint.model_validate_json(data)
        except Exception as e:
            raise CheckpointStoreError("load", str(e)) from e

    async def delete(self, request_id: uuid.UUID) -> bool:
        """Delete checkpoint from Redis. Returns True if deleted."""
        self._ensure_connected()
        try:
            key     = self._key(request_id)
            deleted = await self._client.delete(key)
            return deleted > 0
        except Exception as e:
            raise CheckpointStoreError("delete", str(e)) from e

    async def exists(self, request_id: uuid.UUID) -> bool:
        """Return True if checkpoint exists in Redis."""
        self._ensure_connected()
        try:
            key = self._key(request_id)
            return bool(await self._client.exists(key))
        except Exception as e:
            raise CheckpointStoreError("exists", str(e)) from e

    def _ensure_connected(self) -> None:
        if self._client is None:
            raise CheckpointStoreError(
                "operation",
                "Not connected. Call connect() before using the store."
            )

    def __repr__(self) -> str:
        connected = self._client is not None
        return f"RedisCheckpointStore(connected={connected}, ttl={self._ttl})"
