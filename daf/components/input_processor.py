"""
InputProcessor — validates and structures all external input.

The sole entry point for all user requests.
Every raw request passes through here before anything
else in the loop touches it.

RESPONSIBILITIES:
  1. Validate required fields
  2. Sanitize string inputs
  3. Apply default values
  4. Validate constraints (cost, duration)
  5. Classify intent from task description
  6. Return a well-formed WorkflowRequest

WHAT IT DOES NOT DO:
  - No LLM calls — deterministic only
  - No policy evaluation — that is PolicyEngine
  - No authentication — caller's responsibility
  - No routing decisions — that is GovernedAgenticLoop

DESIGN NOTE:
  InputValidationError is raised for invalid input.
  The GovernedAgenticLoop catches this and returns
  a FinalResponse with outcome="invalid_input"
  rather than letting it propagate to the caller raw.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from daf.models.workflow_request import WorkflowRequest

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

MAX_TASK_LENGTH      = 10_000  # characters
MAX_ID_LENGTH        = 256     # characters (user_id, tenant_id)
DEFAULT_USER_ID      = "anonymous"
DEFAULT_TENANT_ID    = "default"
DEFAULT_INTENT_CLASS = "mixed"

# Intent classification keywords
_DETERMINISTIC_KEYWORDS = frozenset({
    "count", "list", "extract", "find", "get", "fetch",
    "retrieve", "search", "filter", "sort", "group",
    "calculate", "compute", "check", "verify", "validate",
})

_LLM_KEYWORDS = frozenset({
    "analyse", "analyze", "summarise", "summarize", "explain",
    "write", "generate", "review", "describe", "evaluate",
    "compare", "recommend", "suggest", "draft", "create",
    "identify", "assess", "interpret", "translate", "classify",
})


# ── Exception ─────────────────────────────────────────────────

class InputValidationError(Exception):
    """
    Raised when the raw request fails validation.

    field:   The field that failed validation (e.g. "task", "constraints")
    reason:  Human-readable description of the failure
    """
    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"Invalid input — field '{field}': {reason}")
        self.field  = field
        self.reason = reason


# ── InputProcessor ────────────────────────────────────────────

class InputProcessor:
    """
    Validates and structures all external input into WorkflowRequests.

    Fully deterministic. No LLM calls. No external dependencies.
    Raises InputValidationError on invalid input.
    """

    def __init__(self, policy_engine: Any = None) -> None:
        # policy_engine kept for interface compatibility
        # Not used by InputProcessor — policy evaluation is separate
        self._policy_engine = policy_engine

    def process(self, raw_request: dict[str, Any]) -> WorkflowRequest:
        """
        Validate, sanitize, and structure a raw request.

        Args:
            raw_request: Dict with at minimum {"task": str}
                         Optional: user_id, tenant_id, context, constraints

        Returns:
            WorkflowRequest — well-formed, validated, sanitized

        Raises:
            InputValidationError: on validation failure
        """
        # Step 1: Validate and sanitize task
        task = self._validate_task(raw_request.get("task", ""))

        # Step 2: Sanitize identifiers
        user_id   = self._sanitize_id(
            raw_request.get("user_id", DEFAULT_USER_ID),
            field="user_id",
            default=DEFAULT_USER_ID,
        )
        tenant_id = self._sanitize_id(
            raw_request.get("tenant_id", DEFAULT_TENANT_ID),
            field="tenant_id",
            default=DEFAULT_TENANT_ID,
        )

        # Step 3: Validate constraints
        constraints = self._validate_constraints(
            raw_request.get("constraints", {})
        )

        # Step 4: Classify intent
        intent_class = raw_request.get("intent_class") or self._classify_intent(task)

        # Step 5: Sanitize context (pass through, remove non-serialisable values)
        context = self._sanitize_context(raw_request.get("context", {}))

        logger.debug(
            f"InputProcessor: validated request "
            f"tenant={tenant_id!r} user={user_id!r} "
            f"intent={intent_class!r} "
            f"task_len={len(task)}"
        )

        return WorkflowRequest(
            request_id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            tenant_id=tenant_id,
            task_description=task,
            intent_class=intent_class,
            context=context,
            constraints=constraints,
        )

    # ── Private validation methods ───────────────────────────

    def _validate_task(self, raw_task: Any) -> str:
        """Validate and sanitize the task description."""
        if not isinstance(raw_task, str):
            raise InputValidationError(
                field="task",
                reason=f"must be a string, got {type(raw_task).__name__}",
            )

        task = raw_task.strip()

        if not task:
            raise InputValidationError(
                field="task",
                reason="must not be empty",
            )

        if len(task) > MAX_TASK_LENGTH:
            raise InputValidationError(
                field="task",
                reason=(
                    f"exceeds maximum length of {MAX_TASK_LENGTH} characters "
                    f"(got {len(task)})"
                ),
            )

        return task

    def _sanitize_id(
        self,
        value:   Any,
        field:   str,
        default: str,
    ) -> str:
        """Sanitize a string ID field (user_id or tenant_id)."""
        if value is None or value == "":
            return default

        if not isinstance(value, str):
            # Non-string ID — use default rather than raising
            logger.warning(
                f"InputProcessor: {field} is not a string "
                f"({type(value).__name__}) — using default '{default}'"
            )
            return default

        sanitized = value.strip()

        if not sanitized:
            return default

        if len(sanitized) > MAX_ID_LENGTH:
            # Truncate rather than reject — ID length is not security-critical
            logger.warning(
                f"InputProcessor: {field} truncated from "
                f"{len(sanitized)} to {MAX_ID_LENGTH} characters"
            )
            return sanitized[:MAX_ID_LENGTH]

        return sanitized

    def _validate_constraints(
        self,
        raw_constraints: Any,
    ) -> dict[str, Any]:
        """Validate constraints dict."""
        if raw_constraints is None:
            return {}

        if not isinstance(raw_constraints, dict):
            raise InputValidationError(
                field="constraints",
                reason=(
                    f"must be a dict, got {type(raw_constraints).__name__}"
                ),
            )

        constraints = dict(raw_constraints)

        # Validate max_cost_usd
        if "max_cost_usd" in constraints:
            cost = constraints["max_cost_usd"]
            if not isinstance(cost, (int, float)):
                raise InputValidationError(
                    field="constraints.max_cost_usd",
                    reason=f"must be a number, got {type(cost).__name__}",
                )
            if cost <= 0:
                raise InputValidationError(
                    field="constraints.max_cost_usd",
                    reason=f"must be greater than 0, got {cost}",
                )

        # Validate max_duration_s
        if "max_duration_s" in constraints:
            duration = constraints["max_duration_s"]
            if not isinstance(duration, (int, float)):
                raise InputValidationError(
                    field="constraints.max_duration_s",
                    reason=f"must be a number, got {type(duration).__name__}",
                )
            if duration <= 0:
                raise InputValidationError(
                    field="constraints.max_duration_s",
                    reason=f"must be greater than 0, got {duration}",
                )

        return constraints

    def _classify_intent(self, task: str) -> str:
        """
        Classify the intent of a task description.

        Simple keyword-based heuristic.
        Returns: "deterministic", "llm", or "mixed"
        """
        task_lower = task.lower()
        words      = set(task_lower.split())

        has_deterministic = bool(words & _DETERMINISTIC_KEYWORDS)
        has_llm           = bool(words & _LLM_KEYWORDS)

        if has_llm and not has_deterministic:
            return "llm"
        if has_deterministic and not has_llm:
            return "deterministic"
        return "mixed"  # ambiguous or both

    def _sanitize_context(
        self,
        raw_context: Any,
    ) -> dict[str, Any]:
        """
        Sanitize the context dict.

        Passes through string, number, bool, list, and dict values.
        Drops values that are not JSON-serialisable (callables, objects).
        """
        if not isinstance(raw_context, dict):
            return {}

        sanitized: dict[str, Any] = {}
        for key, value in raw_context.items():
            if not isinstance(key, str):
                continue  # skip non-string keys
            if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                sanitized[key] = value
            else:
                logger.debug(
                    f"InputProcessor: context key {key!r} has "
                    f"non-serialisable value ({type(value).__name__}) — skipped"
                )
        return sanitized
