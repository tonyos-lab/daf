from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field, model_validator
from typing import Any


class ConditionOperator(str, Enum):
    """
    Supported operators for compliance rule conditions.

    CONTAINS:  field (list) contains the value
    EQUALS:    field (str)  equals the value
    IN_LIST:   field (str)  is in the values list
    """
    CONTAINS = "contains"
    EQUALS   = "equals"
    IN_LIST  = "in_list"


class Condition(BaseModel):
    """
    Structured condition for a compliance rule.

    Examples:
        # data_required list contains "pii_data"
        Condition(field="data_required", operator="contains", value="pii_data")

        # agent_required equals "finance_agent"
        Condition(field="agent_required", operator="equals", value="finance_agent")

        # task_type is one of the listed values
        Condition(field="task_type", operator="in_list",
                  values=["llm_generation", "deterministic"])
    """
    field:    str
    operator: ConditionOperator
    value:    str | None       = None   # for CONTAINS, EQUALS
    values:   list[str] | None = None   # for IN_LIST

    @model_validator(mode="after")
    def validate_value_for_operator(self) -> Condition:
        """Ensure the correct value field is set for the operator."""
        if self.operator in (ConditionOperator.CONTAINS,
                             ConditionOperator.EQUALS):
            if self.value is None:
                raise ValueError(
                    f"Operator '{self.operator}' requires 'value' to be set"
                )
        if self.operator == ConditionOperator.IN_LIST:
            if not self.values:
                raise ValueError(
                    "Operator 'in_list' requires 'values' to be a non-empty list"
                )
        return self


class ComplianceAction(str, Enum):
    """What the Policy Engine does when a compliance rule matches."""
    BLOCK               = "block"
    WARN                = "warn"
    REQUIRE_HUMAN_GATE  = "require_human_gate"


class AgentRoleConfig(BaseModel):
    permitted_tools:        list[str] = Field(default_factory=list)
    permitted_data_sources: list[str] = Field(default_factory=list)
    permitted_task_types:   list[str] = Field(default_factory=list)
    max_llm_calls_per_step: int       = 5


class OrchestratorRoutingConfig(BaseModel):
    may_spawn_roles: list[str] = Field(default_factory=list)


class BudgetPolicyConfig(BaseModel):
    max_cost_per_call_usd:       float = 0.02
    max_cost_per_step_usd:       float = 0.10
    max_cost_per_workflow_usd:   float = 0.50
    max_cost_per_user_day_usd:   float = 5.00
    max_cost_per_tenant_day_usd: float = 100.00


class ComplianceRule(BaseModel):
    """
    A single compliance rule in the PolicyMatrix.

    The condition is evaluated against each SubTask during Policy Engine
    evaluation. If the condition matches:
    - action=block              → sub-task is rejected (blocking violation)
    - action=warn               → sub-task is approved but violation is logged
    - action=require_human_gate → sub-task is added to gated_tasks in ApprovalGrant
    """
    rule_ref:         str
    condition:        Condition
    action:           ComplianceAction
    remediation_hint: str = ""

class RiskPolicyConfig(BaseModel):
    irreversible_min_confidence: float = 0.90
    always_gate_action_classes: list[str] = Field(default_factory=list)
    auto_approve_action_classes: list[str] = Field(default_factory=list)

class LoopPolicyConfig(BaseModel):
    max_replan_attempts: int = 3
    max_duration_s: float = 300.0

class PolicyMatrix(BaseModel):
    version: str
    tenant_id: str
    effective: str
    agent_roles: dict[str, AgentRoleConfig]
    orchestrator_routing: dict[str, OrchestratorRoutingConfig] = Field(default_factory=dict)
    budget_policy: BudgetPolicyConfig = Field(default_factory=BudgetPolicyConfig)
    compliance_rules: list[ComplianceRule] = Field(default_factory=list)
    risk_policy: RiskPolicyConfig = Field(default_factory=RiskPolicyConfig)
    loop_policy: LoopPolicyConfig = Field(default_factory=LoopPolicyConfig)
