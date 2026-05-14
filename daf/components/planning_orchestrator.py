"""
PlanningOrchestrator — the only component that invokes an LLM.

Receives WorkflowRequests and produces PlanProposals.
Re-plans when given ViolationReports from the Policy Engine.

Depends on LLMClient interface — never on a specific provider.
The provider is injected at construction time.

CRITICAL:
- This is the ONLY component in DAF that calls an LLM
- All other components are deterministic code
- This component does NOT evaluate proposals — that is the Policy Engine
- This component does NOT execute anything — that is the Execution Orchestrator
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import PolicyMatrix
from daf.models.violation_report import ViolationReport
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.llm_client import LLMClient, LLMOutputError

logger = logging.getLogger(__name__)


# ── Prompts ──────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are the Planning Orchestrator for a Policy-Based Agentic System.

Your role is to decompose a user task into a structured plan proposal.
You PROPOSE plans. You do NOT evaluate, govern, or execute anything.
A separate Policy Engine evaluates your proposals against organizational policy.
A separate Execution Orchestrator runs approved plans.

AVAILABLE AGENT ROLES:
{available_roles}

AVAILABLE TOOLS PER ROLE:
{available_tools}

BUDGET CONSTRAINT:
Maximum total estimated cost: ${max_cost_usd:.4f} USD

TASK DECOMPOSITION RULES:
1. Break the task into the minimum number of sub-tasks needed
2. Each sub-task must use exactly one agent role
3. Each sub-task must specify only tools available to that role
4. Assign realistic cost estimates (typical range: $0.001 - $0.05 per step)
5. Mark any action that cannot be undone as reversible=false
6. Provide a clear rationale for each sub-task
7. Specify dependencies using task_ids (empty list if no dependency)

Respond ONLY using the structured_response tool.
Do not add any text outside the tool response."""

_REPLAN_PROMPT = """The plan you proposed (iteration {iteration}) was rejected.

VIOLATIONS FOUND:
{violations}

TASKS THAT PASSED ALL CHECKS (you may reuse these):
{approvable_tasks}

REMAINING BUDGET: ${budget_remaining:.4f} USD

Produce a revised plan that:
1. Resolves ALL violations listed above
2. Reuses approvable tasks unchanged where possible
3. Stays within the remaining budget
4. Still accomplishes the original goal

ORIGINAL TASK: {task}"""


# ── PlanProposal JSON Schema ─────────────────────────────────

_PLAN_PROPOSAL_SCHEMA = {
    "type": "object",
    "required": [
        "orchestrator",
        "planning_rationale",
        "sub_tasks",
        "total_estimated_cost",
        "confidence",
        "requires_human_gate",
    ],
    "properties": {
        "orchestrator": {
            "type": "string",
            "description": "Name of the orchestrator to use for execution",
        },
        "planning_rationale": {
            "type": "string",
            "description": "Brief explanation of the overall approach",
        },
        "sub_tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "task_id", "name", "task_type",
                    "agent_required", "tools_required",
                    "data_required", "depends_on",
                    "estimated_cost", "reversible", "rationale",
                ],
                "properties": {
                    "task_id": {"type": "string"},
                    "name": {"type": "string"},
                    "task_type": {
                        "type": "string",
                        "enum": [
                            "deterministic",
                            "llm_classification",
                            "llm_extraction",
                            "llm_summarization",
                            "llm_transformation",
                            "llm_generation",
                            "llm_evaluation",
                        ],
                    },
                    "agent_required": {"type": "string"},
                    "tools_required": {"type": "array", "items": {"type": "string"}},
                    "data_required": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "estimated_cost": {"type": "number"},
                    "reversible": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
            },
        },
        "total_estimated_cost": {"type": "number"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "requires_human_gate": {"type": "boolean"},
    },
    "additionalProperties": False,
}


class PlanningOrchestrator:
    """
    Generates Plan Proposals using an LLM via the LLMClient interface.

    This is the ONLY component in DAF that calls an LLM.
    It depends on LLMClient — not on any specific provider.
    The provider is injected at construction time.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        temperature: float = 0.2,
    ) -> None:
        self._llm = llm_client
        self._temperature = temperature

    async def plan(
        self,
        workflow_request: WorkflowRequest,
        policy_matrix: PolicyMatrix,
        violation_history: list[ViolationReport],
        iteration: int,
    ) -> PlanProposal:
        """
        Generate a PlanProposal for the given workflow request.

        On first call (iteration=1, no violations): initial plan.
        On subsequent calls: re-plan with violation context.

        Args:
            workflow_request: The user's request
            policy_matrix:    Available roles, tools, and constraints
            violation_history: Prior rejected proposals and their violations
            iteration:        Current loop iteration (1-based)

        Returns:
            PlanProposal conforming to the schema

        Raises:
            LLMClientError:  If the API call fails
            LLMOutputError:  If schema validation fails after all retries
        """
        system = self._build_system_prompt(policy_matrix)

        if violation_history:
            user = self._build_replan_prompt(
                workflow_request=workflow_request,
                violation_history=violation_history,
                policy_matrix=policy_matrix,
                iteration=iteration,
            )
        else:
            user = workflow_request.task_description

        logger.info(
            f"PlanningOrchestrator generating plan "
            f"(iteration={iteration}, model={self._llm.model_id})"
        )

        response = await self._llm.complete(
            system=system,
            user=user,
            schema=_PLAN_PROPOSAL_SCHEMA,
            max_tokens=4096,
            max_retries=2,
        )

        proposal = self._parse_response(
            content=response.content,
            workflow_request=workflow_request,
            iteration=iteration,
        )

        logger.info(
            f"Plan generated: {len(proposal.sub_tasks)} sub-tasks, "
            f"estimated_cost=${proposal.total_estimated_cost:.4f}, "
            f"confidence={proposal.confidence:.2f}, "
            f"tokens_in={response.usage.input_tokens}, "
            f"tokens_out={response.usage.output_tokens}, "
            f"cost=${response.usage.cost_usd:.6f}"
        )

        return proposal

    # ── Private methods ──────────────────────────────────────

    def _build_system_prompt(self, matrix: PolicyMatrix) -> str:
        """Build the system prompt with available roles and tools."""
        role_lines = []
        for role_name, config in matrix.agent_roles.items():
            role_lines.append(
                f"  - {role_name}: "
                f"permitted task types: {', '.join(config.permitted_task_types)}"
            )
        available_roles = (
            "\n".join(role_lines) if role_lines else "  (none defined)"
        )

        tool_lines = []
        for role_name, config in matrix.agent_roles.items():
            if config.permitted_tools:
                tool_lines.append(
                    f"  - {role_name}: {', '.join(config.permitted_tools)}"
                )
        available_tools = (
            "\n".join(tool_lines) if tool_lines else "  (none defined)"
        )

        return _SYSTEM_PROMPT.format(
            available_roles=available_roles,
            available_tools=available_tools,
            max_cost_usd=matrix.budget_policy.max_cost_per_workflow_usd,
        )

    def _build_replan_prompt(
        self,
        workflow_request: WorkflowRequest,
        violation_history: list[ViolationReport],
        policy_matrix: PolicyMatrix,
        iteration: int,
    ) -> str:
        """Build the re-planning user message with violation context."""
        latest = violation_history[-1]

        violation_lines = []
        for v in latest.violations:
            line = f"  Sub-task {v.task_id} [{v.dimension}]: {v.detail}"
            if v.suggestion:
                line += f"\n    Suggestion: {v.suggestion}"
            violation_lines.append(line)
        violations_text = "\n".join(violation_lines)

        approvable_text = (
            ", ".join(latest.approvable_task_ids)
            if latest.approvable_task_ids
            else "None — all tasks require revision"
        )

        return _REPLAN_PROMPT.format(
            iteration=iteration,
            violations=violations_text,
            approvable_tasks=approvable_text,
            budget_remaining=policy_matrix.budget_policy.max_cost_per_workflow_usd,
            task=workflow_request.task_description,
        )

    def _parse_response(
        self,
        content: dict,
        workflow_request: WorkflowRequest,
        iteration: int,
    ) -> PlanProposal:
        """
        Parse the validated LLM response dict into a PlanProposal.
        Schema is already validated by LLMClient before this is called.
        """
        sub_tasks = [
            SubTask(
                task_id=t["task_id"],
                name=t.get("name", ""),
                task_type=t["task_type"],
                agent_required=t["agent_required"],
                tools_required=t.get("tools_required", []),
                data_required=t.get("data_required", []),
                depends_on=t.get("depends_on", []),
                estimated_cost=float(t.get("estimated_cost", 0.0)),
                reversible=bool(t.get("reversible", True)),
                rationale=t.get("rationale", ""),
            )
            for t in content.get("sub_tasks", [])
        ]

        return PlanProposal(
            proposal_id=uuid.uuid4(),
            request_id=workflow_request.request_id,
            iteration=iteration,
            orchestrator=content.get("orchestrator", "default_orchestrator"),
            planning_rationale=content.get("planning_rationale", ""),
            sub_tasks=sub_tasks,
            total_estimated_cost=float(
                content.get("total_estimated_cost", 0.0)
            ),
            confidence=float(content.get("confidence", 0.85)),
            requires_human_gate=bool(
                content.get("requires_human_gate", False)
            ),
        )
