from __future__ import annotations
import uuid
from typing import Any
from pydantic import BaseModel, Field


class FinalResponse(BaseModel):
    """
    The final output of a GovernedAgenticLoop run.

    outcome values:
      "completed"     — all tasks succeeded
      "partial"       — some tasks failed, execution halted
      "escalated"     — loop exhausted or HITL forced escalation
      "invalid_input" — InputProcessor rejected the request
    """
    request_id:         uuid.UUID
    outcome:            str
    loop_iterations:    int
    total_cost_usd:     float
    result:             Any                   = None
    escalation_context: dict[str, Any] | None = None
    audit_summary:      dict[str, Any]        = Field(default_factory=dict)
    # audit_summary: event counts and key timestamps for the caller
    # populated by OutputAssembler when audit_store is available
