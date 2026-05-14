"""
AnthropicLLMClient — Anthropic implementation of LLMClient.

This is the ONLY file in DAF that imports the anthropic package.
Everything else depends on the LLMClient interface only.

Supports:
- claude-sonnet-4-20250514  (recommended for Planning Orchestrator)
- claude-haiku-4-5-20251001 (for cheaper classification/extraction calls)

Structured output is enforced via Anthropic's tool_use with
input_schema — the model is constrained to return JSON matching
the provided schema.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from daf.runtime.llm_client import (
    LLMClient,
    LLMClientError,
    LLMOutputError,
    LLMResponse,
    LLMUsage,
)

logger = logging.getLogger(__name__)

# ── Anthropic pricing (USD per token) ───────────────────────
# Conservative estimates — slightly high to ensure budget tracker
# never under-reserves. Update when pricing changes.
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {
        "input":  0.000003,   # $3.00 per 1M input tokens
        "output": 0.000015,   # $15.00 per 1M output tokens
    },
    "claude-haiku-4-5-20251001": {
        "input":  0.0000008,  # $0.80 per 1M input tokens
        "output": 0.000004,   # $4.00 per 1M output tokens
    },
}
# Default pricing for unknown models — conservative
_DEFAULT_PRICING = {"input": 0.000015, "output": 0.000075}


class AnthropicLLMClient(LLMClient):
    """
    Anthropic implementation of LLMClient.

    Uses tool_use with a strict input_schema to enforce structured output.
    The model is constrained to return JSON matching the provided schema —
    not a prose response with embedded JSON.

    Retries on schema validation failure up to max_retries times,
    adding the validation error to the retry prompt so the model
    can correct its output.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model:   str | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("LLM_API_KEY")
        self._model   = model or os.getenv(
            "LLM_MODEL", "claude-sonnet-4-20250514"
        )
        self._client  = None  # lazy init — avoid import cost at startup

        if not self._api_key:
            raise LLMClientError(
                "Anthropic API key not set. "
                "Set LLM_API_KEY environment variable or pass api_key.",
                provider="anthropic",
            )

    def _get_client(self) -> Any:
        """Lazy-initialize the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(
                    api_key=self._api_key
                )
            except ImportError as e:
                raise LLMClientError(
                    "anthropic package not installed. "
                    "Run: pip install anthropic",
                    provider="anthropic",
                ) from e
        return self._client

    @property
    def model_id(self) -> str:
        return self._model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost with conservative (slightly high) pricing."""
        pricing = _PRICING.get(self._model, _DEFAULT_PRICING)
        return (
            input_tokens  * pricing["input"] +
            output_tokens * pricing["output"]
        )

    async def complete(
        self,
        system:      str,
        user:        str,
        schema:      dict,
        max_tokens:  int = 4096,
        max_retries: int = 2,
    ) -> LLMResponse:
        """
        Call the Anthropic API with structured output enforcement.

        Uses tool_use with the provided schema as input_schema.
        The model is forced to return a tool_use block matching the schema
        rather than prose text.

        Retries up to max_retries times on schema validation failure,
        appending the validation error to the conversation so the model
        can correct itself.
        """
        client = self._get_client()

        # Build the tool definition from the schema
        # The tool name is fixed — we extract the response from tool_use blocks
        tool = {
            "name": "structured_response",
            "description": (
                "Return your response as a structured JSON object "
                "conforming exactly to the provided schema."
            ),
            "input_schema": schema,
        }

        messages = [{"role": "user", "content": user}]
        last_error: str = ""
        last_raw: str = ""

        for attempt in range(1, max_retries + 2):  # attempts: 1, 2, 3 (if max_retries=2)
            try:
                logger.debug(
                    f"LLM call attempt {attempt}/{max_retries + 1} "
                    f"model={self._model}"
                )

                response = await client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "structured_response"},
                )

            except Exception as e:
                # Translate provider errors to LLMClientError
                raise LLMClientError(
                    f"Anthropic API call failed: {e}",
                    provider="anthropic",
                    status_code=getattr(e, "status_code", None),
                ) from e

            # Extract tool_use block
            tool_use_block = next(
                (b for b in response.content if b.type == "tool_use"),
                None,
            )

            if tool_use_block is None:
                last_raw = str(response.content)
                last_error = "Response contained no tool_use block"
                logger.warning(
                    f"Attempt {attempt}: no tool_use block in response"
                )
            else:
                # tool_use.input is already a dict from Anthropic's parser
                content = tool_use_block.input
                last_raw = json.dumps(content)

                # Validate against schema
                validation_error = self._validate_schema(content, schema)
                if validation_error is None:
                    # Success — build usage and return
                    usage = LLMUsage(
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        cost_usd=self.estimate_cost(
                            response.usage.input_tokens,
                            response.usage.output_tokens,
                        ),
                        model_id=self._model,
                    )
                    logger.debug(
                        f"LLM call success: "
                        f"in={usage.input_tokens} out={usage.output_tokens} "
                        f"cost=${usage.cost_usd:.6f}"
                    )
                    return LLMResponse(content=content, usage=usage)

                last_error = validation_error
                logger.warning(
                    f"Attempt {attempt}: schema validation failed: {last_error}"
                )

            # Prepare retry if attempts remain
            if attempt <= max_retries:
                # Add the failed response and correction instruction to messages
                messages = [
                    {"role": "user", "content": user},
                    {
                        "role": "assistant",
                        "content": str(response.content),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response failed validation: {last_error}\n"
                            f"Please correct your response to conform exactly to the schema."
                        ),
                    },
                ]

        # All retries exhausted
        raise LLMOutputError(
            f"Schema validation failed after {max_retries + 1} attempts. "
            f"Last error: {last_error}",
            raw_response=last_raw,
            attempt=max_retries + 1,
        )

    def _validate_schema(
        self,
        content: dict,
        schema: dict,
    ) -> str | None:
        """
        Validate content dict against a JSON Schema.

        Returns None if valid.
        Returns an error message string if invalid.

        Uses jsonschema if available, falls back to required-field check.
        """
        try:
            import jsonschema
            try:
                jsonschema.validate(content, schema)
                return None
            except jsonschema.ValidationError as e:
                return f"{e.message} at {list(e.absolute_path)}"
        except ImportError:
            # Fallback: check required fields only
            required = schema.get("required", [])
            missing = [f for f in required if f not in content]
            if missing:
                return f"Missing required fields: {missing}"
            return None
