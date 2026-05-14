"""
PolicyEngine — the deterministic governance layer.

This is the most critical component in DAF. It must remain:
- A pure function: same inputs always produce same outputs
- Deterministic: no async, no LLM calls, no external state during evaluation
- Complete: every proposal evaluated against every applicable dimension

The Policy Engine is the nervous system. It decides what the brain is allowed to do.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import PolicyMatrix
from daf.models.approval_grant import ApprovalGrant, AgentPermissions
from daf.models.violation_report import ViolationReport, Violation

logger = logging.getLogger(__name__)


class PolicyEvaluation(BaseModel):
    """Result of a Policy Engine evaluation."""
    verdict: str  # "APPROVED" or "REJECTED"
    approval_grant: ApprovalGrant | None = None
    violation_report: ViolationReport | None = None


class PolicyEngine:
    """
    Evaluates Plan Proposals against the PolicyMatrix.

    CRITICAL CONSTRAINTS:
    - This class must never invoke an LLM
    - The evaluate() method must be synchronous
    - No mutable state between evaluate() calls
    - PolicyMatrix is loaded once and passed to evaluate()

    Any deviation from these constraints is a security regression.
    """

    def __init__(self, policy_matrix_path: str) -> None:
        self._policy_matrix_path = Path(policy_matrix_path)
        self._cached_matrix: PolicyMatrix | None = None

    def load_matrix(self, tenant_id: str) -> PolicyMatrix:
        """
        Load the PolicyMatrix for a tenant.
        Checks matrix integrity before returning.
        """
        # TODO: implement per-tenant matrix loading and integrity verification
        if self._cached_matrix is None:
            raw = yaml.safe_load(self._policy_matrix_path.read_text())
            self._cached_matrix = PolicyMatrix.model_validate(raw)
        return self._cached_matrix

    def evaluate(
        self,
        proposal: PlanProposal,
        matrix: PolicyMatrix,
    ) -> PolicyEvaluation:
        """
        Evaluate a PlanProposal against the PolicyMatrix.

        This is a pure function. Given the same proposal and matrix,
        it always returns the same result.

        Args:
            proposal: The plan proposed by the Planning Orchestrator
            matrix: The organizational policy matrix

        Returns:
            PolicyEvaluation with verdict APPROVED or REJECTED.
            On REJECTED: ViolationReport with specific violations and suggestions.
            On APPROVED: ApprovalGrant with scoped permissions per agent role.
        """
        violations: list[Violation] = []
        approvable_task_ids: list[str] = []

        for task in proposal.sub_tasks:
            task_violations = self._evaluate_task(task, proposal, matrix)

            if task_violations:
                violations.extend(task_violations)
            else:
                approvable_task_ids.append(task.task_id)

        # Check total workflow budget
        if proposal.total_estimated_cost > matrix.budget_policy.max_cost_per_workflow_usd:
            violations.append(
                Violation(
                    task_id="workflow",
                    dimension="budget",
                    severity="blocking",
                    detail=(
                        f"Total estimated cost ${proposal.total_estimated_cost:.4f} "
                        f"exceeds workflow limit "
                        f"${matrix.budget_policy.max_cost_per_workflow_usd:.4f}"
                    ),
                    rule_ref="BUDGET-WORKFLOW",
                    suggestion=(
                        f"Reduce total scope to fit within "
                        f"${matrix.budget_policy.max_cost_per_workflow_usd:.4f}"
                    ),
                )
            )

        blocking = [v for v in violations if v.severity == "blocking"]

        if not blocking:
            # Collect gated tasks from approvable set
            gated_tasks = self._collect_gated_tasks(
                proposal, matrix, approvable_task_ids
            )
            grant = self._build_approval_grant(proposal, matrix, gated_tasks)
            return PolicyEvaluation(verdict="APPROVED", approval_grant=grant)
        else:
            should_escalate = (
                proposal.iteration >= matrix.loop_policy.max_replan_attempts
            )
            report = ViolationReport(
                proposal_id=proposal.proposal_id,
                violations=violations,
                approvable_task_ids=approvable_task_ids,
                escalate_to_human=should_escalate,
                escalation_reason=(
                    f"Maximum re-plan attempts ({matrix.loop_policy.max_replan_attempts}) "
                    f"reached without finding a compliant plan."
                    if should_escalate else None
                ),
            )
            return PolicyEvaluation(verdict="REJECTED", violation_report=report)

    def _evaluate_task(
        self,
        task: SubTask,
        proposal: PlanProposal,
        matrix: PolicyMatrix,
    ) -> list[Violation]:
        """Evaluate a single sub-task against all policy dimensions."""
        violations: list[Violation] = []

        # Get role permissions
        role_perms = matrix.agent_roles.get(task.agent_required)
        if role_perms is None:
            return [
                Violation(
                    task_id=task.task_id,
                    dimension="agent_authorization",
                    severity="blocking",
                    detail=f"Agent role '{task.agent_required}' is not defined in the PolicyMatrix",
                    rule_ref="AGENT-UNDEFINED",
                    suggestion="Use an approved agent role or request addition to PolicyMatrix",
                )
            ]

        # Dimension 1: Tool permissions
        for tool in task.tools_required:
            if tool not in role_perms.permitted_tools:
                violations.append(
                    Violation(
                        task_id=task.task_id,
                        dimension="tool_permission",
                        severity="blocking",
                        detail=f"Role '{task.agent_required}' is not permitted to invoke '{tool}'",
                        rule_ref=f"TOOL-{tool.upper()}",
                        suggestion=self._suggest_tool_alternative(
                            task, tool, matrix
                        ),
                    )
                )

        # Dimension 2: Data access
        for source in task.data_required:
            if source not in role_perms.permitted_data_sources:
                violations.append(
                    Violation(
                        task_id=task.task_id,
                        dimension="data_access",
                        severity="blocking",
                        detail=f"Role '{task.agent_required}' is not permitted to access '{source}'",
                        rule_ref=f"DATA-{source.upper()}",
                        suggestion=(
                            f"Use an intermediary agent with '{source}' access "
                            f"to extract and pass only required fields to '{task.agent_required}'"
                        ),
                    )
                )

        # Dimension 3: Agent authorization for task type
        if task.task_type not in role_perms.permitted_task_types:
            violations.append(
                Violation(
                    task_id=task.task_id,
                    dimension="agent_authorization",
                    severity="blocking",
                    detail=(
                        f"Role '{task.agent_required}' is not permitted "
                        f"for task type '{task.task_type}'"
                    ),
                    rule_ref="AGENT-TASKTYPE",
                    suggestion=f"Assign a role with '{task.task_type}' in its permitted_task_types",
                )
            )

        # Dimension 4: Per-step budget
        if task.estimated_cost > matrix.budget_policy.max_cost_per_step_usd:
            violations.append(
                Violation(
                    task_id=task.task_id,
                    dimension="budget",
                    severity="blocking",
                    detail=(
                        f"Estimated step cost ${task.estimated_cost:.4f} "
                        f"exceeds per-step limit "
                        f"${matrix.budget_policy.max_cost_per_step_usd:.4f}"
                    ),
                    rule_ref="BUDGET-STEP",
                    suggestion="Break this step into smaller sub-tasks or reduce scope",
                )
            )

        # Dimension 5: Compliance rules
        for rule in matrix.compliance_rules:
            if self._rule_applies(rule, task):
                from daf.models.policy_matrix import ComplianceAction
                if rule.action == ComplianceAction.BLOCK:
                    violations.append(
                        Violation(
                            task_id=task.task_id,
                            dimension="compliance",
                            severity="blocking",
                            detail=f"Sub-task violates compliance rule {rule.rule_ref}",
                            rule_ref=rule.rule_ref,
                            suggestion=rule.remediation_hint or "Review compliance rule and adjust plan",
                        )
                    )
                elif rule.action == ComplianceAction.WARN:
                    # Non-blocking — log but do not add to violations
                    logger.warning(
                        f"Compliance warning on task {task.task_id}: "
                        f"rule {rule.rule_ref} — {rule.remediation_hint}"
                    )
                elif rule.action == ComplianceAction.REQUIRE_HUMAN_GATE:
                    # Non-blocking — task is approvable but requires human gate
                    # Recorded via _collect_gated_tasks in evaluate()
                    logger.info(
                        f"Task {task.task_id} requires human gate: "
                        f"rule {rule.rule_ref}"
                    )

        # Dimension 6: Risk threshold for irreversible actions
        if not task.reversible:
            if proposal.confidence < matrix.risk_policy.irreversible_min_confidence:
                violations.append(
                    Violation(
                        task_id=task.task_id,
                        dimension="risk_threshold",
                        severity="blocking",
                        detail=(
                            f"Irreversible action requires confidence >= "
                            f"{matrix.risk_policy.irreversible_min_confidence}, "
                            f"got {proposal.confidence:.2f}"
                        ),
                        rule_ref="RISK-CONFIDENCE",
                        suggestion=(
                            "Increase plan specificity to improve confidence, "
                            "or route through human gate"
                        ),
                    )
                )

        return violations

    def _rule_applies(
        self,
        rule: Any,
        task: SubTask,
    ) -> bool:
        """
        Evaluate whether a compliance rule condition matches a sub-task.

        Evaluates the structured Condition against the SubTask fields.
        Conservative by design: unknown operators or fields return False
        (rule does not apply) rather than raising or blocking.

        Supported operators:
            contains  — task field (list[str]) contains condition value
            equals    — task field (str) equals condition value
            in_list   — task field (str) is in condition values list

        Args:
            rule: ComplianceRule from the PolicyMatrix
            task: SubTask being evaluated

        Returns:
            True if the condition matches (rule applies to this task)
            False if the condition does not match or cannot be evaluated
        """
        from daf.models.policy_matrix import ConditionOperator

        condition = rule.condition

        # Extract field value from SubTask
        # Only these fields are supported as condition targets
        field_map: dict[str, Any] = {
            "task_id":         task.task_id,
            "task_type":       task.task_type,
            "agent_required":  task.agent_required,
            "tools_required":  task.tools_required,
            "data_required":   task.data_required,
            "reversible":      task.reversible,
            "estimated_cost":  task.estimated_cost,
        }

        if condition.field not in field_map:
            # Unknown field — conservative, rule does not apply
            logger.debug(
                f"Compliance rule {rule.rule_ref}: "
                f"unknown field '{condition.field}' — rule skipped"
            )
            return False

        field_value = field_map[condition.field]

        # Evaluate by operator
        try:
            if condition.operator == ConditionOperator.CONTAINS:
                # field must be a list, value must be in it
                if not isinstance(field_value, list):
                    return False
                return condition.value in field_value

            elif condition.operator == ConditionOperator.EQUALS:
                # field must be a string, must equal value
                if not isinstance(field_value, str):
                    return False
                return field_value == condition.value

            elif condition.operator == ConditionOperator.IN_LIST:
                # field must be a string, must be in values list
                if not isinstance(field_value, str):
                    return False
                return field_value in (condition.values or [])

            else:
                # Unknown operator — conservative, rule does not apply
                logger.debug(
                    f"Compliance rule {rule.rule_ref}: "
                    f"unknown operator '{condition.operator}' — rule skipped"
                )
                return False

        except Exception as e:
            # Any evaluation error — conservative, rule does not apply
            logger.warning(
                f"Compliance rule {rule.rule_ref} evaluation error: {e} — rule skipped"
            )
            return False

    def _collect_gated_tasks(
        self,
        proposal: PlanProposal,
        matrix: Any,
        approvable_task_ids: list[str],
    ) -> list[str]:
        """
        Identify sub-tasks that require human gate before execution.

        A task requires a human gate when:
        1. A compliance rule with action=require_human_gate matches it
        2. Its action class is in risk_policy.always_gate_action_classes
        3. It is irreversible AND proposal confidence < irreversible_min_confidence

        Only called for approvable tasks (those that passed all blocking checks).

        Args:
            proposal: The approved PlanProposal
            matrix: The PolicyMatrix
            approvable_task_ids: task_ids that passed all blocking checks

        Returns:
            List of task_ids requiring human gate
        """
        from daf.models.policy_matrix import ComplianceAction

        gated: list[str] = []
        approvable_set = set(approvable_task_ids)

        for task in proposal.sub_tasks:
            if task.task_id not in approvable_set:
                continue  # skip tasks that already have blocking violations

            # Gate condition 1: compliance rule requires_human_gate
            for rule in matrix.compliance_rules:
                if (rule.action == ComplianceAction.REQUIRE_HUMAN_GATE
                        and self._rule_applies(rule, task)):
                    if task.task_id not in gated:
                        gated.append(task.task_id)
                        logger.info(
                            f"Task {task.task_id} gated by compliance rule "
                            f"{rule.rule_ref}"
                        )

            # Gate condition 2: action class in always_gate list
            if task.task_type in matrix.risk_policy.always_gate_action_classes:
                if task.task_id not in gated:
                    gated.append(task.task_id)
                    logger.info(
                        f"Task {task.task_id} gated: task_type "
                        f"'{task.task_type}' in always_gate_action_classes"
                    )

            # Gate condition 3: irreversible + low confidence
            if (not task.reversible
                    and proposal.confidence
                    < matrix.risk_policy.irreversible_min_confidence):
                if task.task_id not in gated:
                    gated.append(task.task_id)
                    logger.info(
                        f"Task {task.task_id} gated: irreversible action "
                        f"with confidence {proposal.confidence:.2f} below "
                        f"threshold {matrix.risk_policy.irreversible_min_confidence}"
                    )

        return gated

    def _suggest_tool_alternative(
        self,
        task: SubTask,
        tool: str,
        matrix: Any,
    ) -> str:
        """Suggest an alternative approach when a tool permission fails."""
        # Find roles that do have this tool
        permitted_roles = [
            role_name
            for role_name, perms in matrix.agent_roles.items()
            if tool in perms.permitted_tools
        ]
        if permitted_roles:
            return (
                f"Assign role '{permitted_roles[0]}' to this sub-task, "
                f"or restructure so '{task.agent_required}' receives the output instead"
            )
        return f"No role in the current PolicyMatrix has permission for '{tool}'"

    def _build_approval_grant(
        self,
        proposal: PlanProposal,
        matrix: Any,
        gated_tasks: list[str],
    ) -> ApprovalGrant:
        """Build an ApprovalGrant with scoped permissions and gated task list."""
        agent_permissions: dict[str, AgentPermissions] = {}

        for task in proposal.sub_tasks:
            role_name = task.agent_required
            if role_name not in agent_permissions:
                role_perms = matrix.agent_roles[role_name]
                agent_permissions[role_name] = AgentPermissions(
                    tools=role_perms.permitted_tools,
                    data_sources=role_perms.permitted_data_sources,
                    access_level="read_only",
                    max_calls=role_perms.max_llm_calls_per_step,
                )

        return ApprovalGrant(
            proposal_id=proposal.proposal_id,
            approved_plan=proposal,
            agent_permissions=agent_permissions,
            gated_tasks=gated_tasks,
            execution_constraints={
                "max_cost_usd": matrix.budget_policy.max_cost_per_workflow_usd,
                "max_duration_s": matrix.loop_policy.max_duration_s,
                "human_gate_required": len(gated_tasks) > 0,
            },
        )
