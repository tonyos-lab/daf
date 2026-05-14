from __future__ import annotations
import uuid
from pydantic import BaseModel, Field
from typing import Any

class SubTask(BaseModel):
    task_id: str
    name: str = ""
    task_type: str
    agent_required: str
    tools_required: list[str] = Field(default_factory=list)
    data_required: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    reversible: bool = True
    rationale: str = ""
    output_contract: dict[str, Any] = Field(default_factory=dict)

class PlanProposal(BaseModel):
    proposal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    iteration: int = 1
    orchestrator: str
    planning_rationale: str
    sub_tasks: list[SubTask] = Field(default_factory=list)
    total_estimated_cost: float = 0.0
    confidence: float = 0.85
    requires_human_gate: bool = False
