from __future__ import annotations
import uuid
from pydantic import BaseModel, Field
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    from daf.models.plan_proposal import PlanProposal


class AgentPermissions(BaseModel):
    tools:        list[str]
    data_sources: list[str]
    access_level: str = "read_only"
    max_calls:    int = 5


class ApprovalGrant(BaseModel):
    """
    Issued by the Policy Engine when a PlanProposal passes all checks.

    gated_tasks: task_ids requiring human approval before execution.
                 Empty list means execute immediately without HITL.
                 Non-empty means the EvaluateStage must collect human
                 approvals before passing to ExecutionOrchestrator.
    """
    grant_id:              uuid.UUID = Field(default_factory=uuid.uuid4)
    proposal_id:           uuid.UUID
    approved_plan:         Any                          # PlanProposal
    agent_permissions:     dict[str, AgentPermissions]
    execution_constraints: dict[str, Any]               = Field(default_factory=dict)
    gated_tasks:           list[str]                    = Field(default_factory=list)
    # task_ids that require human approval before execution
    # populated by PolicyEngine when:
    #   - compliance rule action = require_human_gate
    #   - task action class in risk_policy.always_gate_action_classes
    #   - task.reversible=False AND confidence < irreversible_min_confidence
