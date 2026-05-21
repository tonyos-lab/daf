"""
LLMClient — provider-agnostic interface for LLM calls.

PlanningOrchestrator depends on this interface only.
It never imports a specific provider.

is the provider-specific implementation file.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# ── Exceptions ───────────────────────────────────────────────

class LLMClientError(Exception):
    """
    Raised when the LLM provider API call fails.

    This covers: network errors, authentication failures,
    rate limit exhaustion, provider-side errors.
    Not raised for output validation failures — see LLMOutputError.
    """
    def __init__(self, message: str, provider: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider    = provider
        self.status_code = status_code


class LLMOutputError(Exception):
    """
    Raised when the LLM response does not conform to the expected schema
    after all retries are exhausted.

    This means the model returned a structurally invalid response
    that could not be coerced into the required format.
    The GovernedAgenticLoop treats this as an unexpected failure
    and does not attempt re-planning — it halts and escalates.
    """
    def __init__(self, message: str, raw_response: str, attempt: int) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.attempt      = attempt


# ── Usage record ────────────────────────────────────────────

@dataclass(frozen=True)
class LLMUsage:
    """
    Token usage and cost for a single LLM call.
    Returned alongside the response so the caller
    can update the BudgetTracker with actual cost.
    """
    input_tokens:  int
    output_tokens: int
    cost_usd:      float
    model_id:      str


# ── Response wrapper ─────────────────────────────────────────

@dataclass(frozen=True)
class LLMResponse:
    """
    Complete result of a single LLM call.
    content is the parsed JSON dict — already validated against schema.
    usage contains token counts and actual cost.
    """
    content: dict
    usage:   LLMUsage


# ── Abstract interface ───────────────────────────────────────

class LLMClient(ABC):
    """
    Abstract interface for LLM providers.

    PlanningOrchestrator calls complete() with a system prompt,
    user message, and JSON schema. It receives a validated dict back.

    Implementations handle:
    - Provider-specific API call
    - Structured output / JSON mode enforcement
    - Schema validation of the response
    - Retry on schema failure (up to max_retries)
    - Token counting and cost calculation
    - Error translation to LLMClientError / LLMOutputError

    CRITICAL:
    - complete() must raise LLMClientError on API failure
    - complete() must raise LLMOutputError if schema validation
      fails after all retries
    - complete() must never return an unvalidated response
    - complete() must populate LLMUsage with accurate token counts
    """

    @abstractmethod
    async def complete(
        self,
        system:      str,
        user:        str,
        schema:      dict,
        max_tokens:  int = 4096,
        max_retries: int = 2,
        stage:       str = "",
    ) -> LLMResponse:
        """
        Call the LLM and return a schema-validated response.

        Args:
            system:      System prompt — instructions and context
            user:        User message — the specific task for this call
            schema:      JSON Schema dict the response must conform to
            max_tokens:  Maximum tokens to generate
            max_retries: Retry attempts on schema validation failure
            stage:       Which cognitive stage is calling (planner/validator/
                         executor/collector). Used by MockLLMClient to select
                         the correct fixture response.

        Returns:
            LLMResponse with validated content dict and usage stats

        Raises:
            LLMClientError:  API call failed (network, auth, rate limit)
            LLMOutputError:  Schema validation failed after all retries
        """
        ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        """
        The exact model identifier used for calls.
        Logged in every audit record.
        Must be the pinned version string, not an alias like 'latest'.
        """
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Estimate cost in USD for a call with given token counts.
        Used by BudgetTracker for pre-call reservation.
        Must be conservative (slightly over, not under).
        """
        ...
