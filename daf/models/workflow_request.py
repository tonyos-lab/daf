from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

class WorkflowRequest(BaseModel):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime
    user_id: str
    tenant_id: str
    task_description: str
    intent_class: str = "mixed"
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
