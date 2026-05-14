from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel

class ExecutionResult(BaseModel):
    grant_id: uuid.UUID
    proposal_id: uuid.UUID
    outcome: str
    step_results: list[Any]
    total_cost_usd: float
    total_duration_ms: int
    completed_at: datetime
