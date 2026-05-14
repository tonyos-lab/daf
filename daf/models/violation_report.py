from __future__ import annotations
import uuid
from pydantic import BaseModel, Field

class Violation(BaseModel):
    task_id: str
    dimension: str
    severity: str = "blocking"
    detail: str
    rule_ref: str = ""
    suggestion: str = ""

class ViolationReport(BaseModel):
    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    proposal_id: uuid.UUID
    violations: list[Violation]
    approvable_task_ids: list[str] = Field(default_factory=list)
    escalate_to_human: bool = False
    escalation_reason: str | None = None
