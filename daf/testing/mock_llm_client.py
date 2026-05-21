"""
MockLLMClient — a developer-controlled LLM client for testing and development.

Allows developers to provide their own plan responses without a real API key.
Works as a drop-in replacement for any LLMClient implementation.

DESIGN:
  The real LLM returns a PlanProposal dict.
  MockLLMClient returns whatever the developer provides.
  The developer is responsible for providing a valid structure
  (use FixturePlanBuilder to construct valid plans easily).

USAGE:

  # Single fixed response
  from daf.testing import MockLLMClient, FixturePlanBuilder

  plan = FixturePlanBuilder()\\
      .with_task("ST-01", agent="analyst", tools=["read_db"])\\
      .build()

  loop = GovernedAgenticLoop(
      llm_client=MockLLMClient(responses=[plan]),
      ...
  )

  # Multiple responses in sequence (re-plan scenario)
  loop = GovernedAgenticLoop(
      llm_client=MockLLMClient(responses=[
          forbidden_plan,   # iteration 1 → rejected by PolicyEngine
          valid_plan,       # iteration 2 → approved
      ]),
      ...
  )

  # Callable response — full control per call
  def dynamic_plan(system: str, user: str) -> dict:
      return my_plan if "contracts" in user else other_plan

  loop = GovernedAgenticLoop(
      llm_client=MockLLMClient(responses=[dynamic_plan]),
      ...
  )

  # Simulate LLM failure
  loop = GovernedAgenticLoop(
      llm_client=MockLLMClient(responses=[], fail_after=0),
      ...
  )
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from daf.runtime.llm_client import (
    LLMClient, LLMResponse, LLMUsage,
    LLMClientError, LLMOutputError,
)

logger = logging.getLogger(__name__)

# Type for a single response: either a dict or a callable
ResponseItem = dict[str, Any] | Callable[[str, str], dict[str, Any]]


class MockLLMClient(LLMClient):
    """
    A developer-controlled LLM client for testing and development.

    Returns developer-provided responses in sequence.
    No API key required. No network calls made.

    Responses cycle when exhausted (last response is repeated).
    Use fail_after to simulate LLM failures.

    Attributes:
        calls: list of (system, user) tuples from every complete() call
        call_count: number of times complete() has been called
    """

    def __init__(
        self,
        responses:    list[ResponseItem] | None = None,
        model:        str  = "mock-model",
        fail_after:   int | None = None,
        input_tokens:  int = 400,
        output_tokens: int = 250,
        cost_per_call: float = 0.0,
    ) -> None:
        """
        Args:
            responses:     List of plan dicts or callables to return in sequence.
                           If empty and fail_after is None, raises on first call.
                           Last response is repeated when list is exhausted.
            model:         Model ID to report in LLMUsage (for audit records).
            fail_after:    Raise LLMClientError after this many successful calls.
                           0 = fail on first call. None = never fail.
            input_tokens:  Simulated input token count per call.
            output_tokens: Simulated output token count per call.
            cost_per_call: Simulated cost per call in USD.
        """
        self._responses     = responses or []
        self._model         = model
        self._fail_after    = fail_after
        self._input_tokens  = input_tokens
        self._output_tokens = output_tokens
        self._cost_per_call = cost_per_call
        self.calls:         list[tuple[str, str]] = []
        self.call_count:    int = 0

    @property
    def model_id(self) -> str:
        return self._model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return self._cost_per_call

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
        Return the next developer-provided response.

        Cycles through responses in order.
        Repeats the last response when the list is exhausted.
        Raises LLMClientError if fail_after is reached.
        Raises LLMClientError if responses is empty.
        """
        # Record the call
        self.calls.append((system, user))
        self.call_count += 1

        # Check fail_after
        if self._fail_after is not None and self.call_count > self._fail_after:
            raise LLMClientError(
                message=(
                    f"MockLLMClient: simulated failure after "
                    f"{self._fail_after} successful call(s)"
                ),
                provider="mock",
                status_code=500,
            )

        # No responses configured
        if not self._responses:
            raise LLMClientError(
                message=(
                    "MockLLMClient has no responses configured. "
                    "Pass responses=[your_plan_dict] to MockLLMClient()."
                ),
                provider="mock",
            )

        # Pick response: use index if available, else repeat last
        idx      = min(self.call_count - 1, len(self._responses) - 1)
        response = self._responses[idx]

        # If callable, invoke with system and user
        if callable(response):
            content = response(system, user)
        else:
            content = dict(response)  # defensive copy

        logger.debug(
            f"MockLLMClient: returning response {idx + 1}/{len(self._responses)} "
            f"(call #{self.call_count})"
        )

        return LLMResponse(
            content=content,
            usage=LLMUsage(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                cost_usd=self._cost_per_call,
                model_id=self._model,
            ),
        )

    def reset(self) -> None:
        """Clear call history. Useful between test scenarios."""
        self.calls.clear()
        self.call_count = 0

    def __repr__(self) -> str:
        return (
            f"MockLLMClient("
            f"responses={len(self._responses)}, "
            f"calls={self.call_count})"
        )
