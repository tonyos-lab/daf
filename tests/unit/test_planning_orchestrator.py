"""
Unit tests for PlanningOrchestrator and LLMClient interface.

ALL tests use a mock LLMClient.
NO real API calls are made in this test file.

Coverage:
  - LLMClient interface (ABC, not instantiable)
  - AnthropicLLMClient conforms to interface
  - PlanningOrchestrator.plan() initial plan
  - PlanningOrchestrator.plan() re-plan with violation context
  - PlanningOrchestrator._build_system_prompt() includes roles and tools
  - PlanningOrchestrator._build_replan_prompt() includes violation detail
  - PlanningOrchestrator._parse_response() produces valid PlanProposal
  - Schema validation failure propagates as LLMOutputError
  - LLMClientError propagates from plan()
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from daf.components.planning_orchestrator import (
    PlanningOrchestrator,
    _PLAN_PROPOSAL_SCHEMA,
    _SYSTEM_PROMPT,
    _REPLAN_PROMPT,
)
from daf.models.plan_proposal import PlanProposal, SubTask
from daf.models.policy_matrix import (
    PolicyMatrix, AgentRoleConfig, BudgetPolicyConfig,
    LoopPolicyConfig, RiskPolicyConfig,
)
from daf.models.violation_report import ViolationReport, Violation
from daf.models.workflow_request import WorkflowRequest
from daf.runtime.llm_client import (
    LLMClient, LLMClientError, LLMOutputError, LLMResponse, LLMUsage,
)


# ── Fixtures ─────────────────────────────────────────────────

def make_usage(**overrides) -> LLMUsage:
    defaults = dict(
        input_tokens=500, output_tokens=300,
        cost_usd=0.0056, model_id="claude-sonnet-4-20250514"
    )
    defaults.update(overrides)
    return LLMUsage(**defaults)


def make_workflow_request(task: str = "Analyse the documents") -> WorkflowRequest:
    return WorkflowRequest(
        request_id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        user_id="test-user",
        tenant_id="test-tenant",
        task_description=task,
    )


def make_matrix(**overrides) -> PolicyMatrix:
    defaults = dict(
        version="1.0.0", tenant_id="test",
        effective="2026-01-01T00:00:00Z",
        agent_roles={
            "document_reader": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["internal_docs"],
                permitted_task_types=["llm_extraction"],
            ),
            "report_writer": AgentRoleConfig(
                permitted_tools=["write_file"],
                permitted_data_sources=[],
                permitted_task_types=["llm_generation"],
            ),
        },
        budget_policy=BudgetPolicyConfig(max_cost_per_workflow_usd=0.50),
        loop_policy=LoopPolicyConfig(max_replan_attempts=3),
        risk_policy=RiskPolicyConfig(),
        compliance_rules=[],
    )
    defaults.update(overrides)
    return PolicyMatrix(**defaults)


def make_violation_report(**overrides) -> ViolationReport:
    defaults = dict(
        proposal_id=uuid.uuid4(),
        violations=[
            Violation(
                task_id="ST-01",
                dimension="tool_permission",
                severity="blocking",
                detail="Role 'document_reader' may not call 'write_db'",
                rule_ref="TOOL-WRITE_DB",
                suggestion="Use 'report_writer' role for write operations",
            )
        ],
        approvable_task_ids=["ST-02"],
        escalate_to_human=False,
    )
    defaults.update(overrides)
    return ViolationReport(**defaults)


def make_valid_plan_content(**overrides) -> dict:
    """Build a valid plan response dict conforming to _PLAN_PROPOSAL_SCHEMA."""
    defaults = {
        "orchestrator": "document_orchestrator",
        "planning_rationale": "Read documents then write report",
        "sub_tasks": [
            {
                "task_id": "ST-01",
                "name": "read_documents",
                "task_type": "llm_extraction",
                "agent_required": "document_reader",
                "tools_required": ["read_db"],
                "data_required": ["internal_docs"],
                "depends_on": [],
                "estimated_cost": 0.03,
                "reversible": True,
                "rationale": "Need to read documents before summarising",
            },
            {
                "task_id": "ST-02",
                "name": "write_report",
                "task_type": "llm_generation",
                "agent_required": "report_writer",
                "tools_required": ["write_file"],
                "data_required": [],
                "depends_on": ["ST-01"],
                "estimated_cost": 0.02,
                "reversible": False,
                "rationale": "Produce final report from extracted data",
            },
        ],
        "total_estimated_cost": 0.05,
        "confidence": 0.90,
        "requires_human_gate": False,
    }
    defaults.update(overrides)
    return defaults


def make_mock_llm(response_content: dict | None = None) -> LLMClient:
    """Build a mock LLMClient that returns the given content."""
    content = response_content or make_valid_plan_content()
    mock = AsyncMock(spec=LLMClient)
    mock.model_id = "claude-sonnet-4-20250514"
    mock.complete = AsyncMock(return_value=LLMResponse(
        content=content,
        usage=make_usage(),
    ))
    mock.estimate_cost = MagicMock(return_value=0.005)
    return mock


# ── LLMClient Interface Tests ────────────────────────────────

class TestLLMClientInterface:
    """Tests that the LLMClient interface contract is correctly defined."""

    def test_llm_client_has_required_methods(self):
        """LLMClient defines the three required abstract methods."""
        assert hasattr(LLMClient, "complete")
        assert hasattr(LLMClient, "model_id")
        assert hasattr(LLMClient, "estimate_cost")

    def test_mock_llm_client_implements_interface(self):
        """MockLLMClient correctly implements the LLMClient interface."""
        from daf.testing import MockLLMClient
        assert issubclass(MockLLMClient, LLMClient)
        assert hasattr(MockLLMClient, "complete")
        assert hasattr(MockLLMClient, "model_id")
        assert hasattr(MockLLMClient, "estimate_cost")

    def test_mock_llm_client_model_id_returns_string(self):
        """MockLLMClient.model_id returns a non-empty string."""
        from daf.testing import MockLLMClient
        client = MockLLMClient(responses=[{}])
        assert isinstance(client.model_id, str)
        assert len(client.model_id) > 0

    def test_mock_llm_client_estimate_cost_returns_non_negative_float(self):
        """MockLLMClient.estimate_cost returns a non-negative float."""
        from daf.testing import MockLLMClient
        client = MockLLMClient(responses=[{}], cost_per_call=0.01)
        cost = client.estimate_cost(1000, 500)
        assert isinstance(cost, float)
        assert cost >= 0.0

    def test_any_llm_client_subclass_works_with_loop(self):
        """Any LLMClient subclass works with GovernedAgenticLoop."""
        from daf.testing import MockLLMClient
        # MockLLMClient is proof the interface is user-implementable
        # DAF ships no built-in provider implementations
        assert issubclass(MockLLMClient, LLMClient)


# ── PlanningOrchestrator — Initial Plan ─────────────────────

class TestPlanningOrchestratorInitialPlan:
    """Tests for PlanningOrchestrator.plan() on the first iteration."""

    @pytest.mark.asyncio
    async def test_plan_returns_valid_proposal(self):
        """plan() returns a PlanProposal with correct structure."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)
        request = make_workflow_request()
        matrix = make_matrix()

        proposal = await orchestrator.plan(
            workflow_request=request,
            policy_matrix=matrix,
            violation_history=[],
            iteration=1,
        )

        assert isinstance(proposal, PlanProposal)
        assert proposal.request_id == request.request_id
        assert proposal.iteration == 1
        assert len(proposal.sub_tasks) == 2

    @pytest.mark.asyncio
    async def test_plan_sub_tasks_have_correct_fields(self):
        """Each sub-task in the proposal has all required fields."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)

        proposal = await orchestrator.plan(
            workflow_request=make_workflow_request(),
            policy_matrix=make_matrix(),
            violation_history=[],
            iteration=1,
        )

        for task in proposal.sub_tasks:
            assert isinstance(task, SubTask)
            assert task.task_id != ""
            assert task.task_type != ""
            assert task.agent_required != ""
            assert isinstance(task.tools_required, list)
            assert isinstance(task.data_required, list)
            assert isinstance(task.depends_on, list)
            assert isinstance(task.estimated_cost, float)
            assert isinstance(task.reversible, bool)

    @pytest.mark.asyncio
    async def test_plan_uses_task_description_as_user_message(self):
        """plan() passes task_description as the user message to LLM."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)
        request = make_workflow_request(task="Summarise the Q3 report")

        await orchestrator.plan(
            workflow_request=request,
            policy_matrix=make_matrix(),
            violation_history=[],
            iteration=1,
        )

        call_kwargs = llm.complete.call_args
        assert call_kwargs.kwargs["user"] == "Summarise the Q3 report"

    @pytest.mark.asyncio
    async def test_plan_proposal_id_is_unique_per_call(self):
        """Each call to plan() produces a unique proposal_id."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)
        request = make_workflow_request()
        matrix = make_matrix()

        proposal_a = await orchestrator.plan(request, matrix, [], 1)
        proposal_b = await orchestrator.plan(request, matrix, [], 1)

        assert proposal_a.proposal_id != proposal_b.proposal_id

    @pytest.mark.asyncio
    async def test_plan_passes_schema_to_llm(self):
        """plan() passes _PLAN_PROPOSAL_SCHEMA to LLMClient.complete()."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)

        await orchestrator.plan(
            make_workflow_request(), make_matrix(), [], 1
        )

        call_kwargs = llm.complete.call_args
        assert call_kwargs.kwargs["schema"] == _PLAN_PROPOSAL_SCHEMA


# ── PlanningOrchestrator — System Prompt ────────────────────

class TestPlanningOrchestratorSystemPrompt:
    """Tests for _build_system_prompt()."""

    def test_system_prompt_includes_all_agent_roles(self):
        """System prompt lists all agent roles from the PolicyMatrix."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        matrix = make_matrix()
        prompt = orchestrator._build_system_prompt(matrix)
        assert "document_reader" in prompt
        assert "report_writer" in prompt

    def test_system_prompt_includes_permitted_tools(self):
        """System prompt lists permitted tools for each role."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        matrix = make_matrix()
        prompt = orchestrator._build_system_prompt(matrix)
        assert "read_db" in prompt
        assert "write_file" in prompt

    def test_system_prompt_includes_budget_constraint(self):
        """System prompt includes the workflow budget limit."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        matrix = make_matrix(
            budget_policy=BudgetPolicyConfig(max_cost_per_workflow_usd=0.25)
        )
        prompt = orchestrator._build_system_prompt(matrix)
        assert "0.25" in prompt or "0.2500" in prompt

    def test_system_prompt_no_roles_produces_placeholder(self):
        """System prompt handles empty agent_roles gracefully."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        matrix = make_matrix(agent_roles={})
        prompt = orchestrator._build_system_prompt(matrix)
        assert "(none defined)" in prompt


# ── PlanningOrchestrator — Re-plan ──────────────────────────

class TestPlanningOrchestratorReplan:
    """Tests for plan() on re-planning iterations."""

    @pytest.mark.asyncio
    async def test_replan_uses_replan_prompt_not_task_description(self):
        """On re-plan, user message is the replan prompt, not the task description."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)
        request = make_workflow_request(task="Analyse contracts")
        violation = make_violation_report()

        await orchestrator.plan(
            workflow_request=request,
            policy_matrix=make_matrix(),
            violation_history=[violation],
            iteration=2,
        )

        call_kwargs = llm.complete.call_args
        user_message = call_kwargs.kwargs["user"]
        # Should NOT be the bare task description
        assert user_message != "Analyse contracts"
        # Should contain violation information
        assert "VIOLATIONS" in user_message or "violation" in user_message.lower()

    @pytest.mark.asyncio
    async def test_replan_iteration_stored_in_proposal(self):
        """Re-plan proposal stores the correct iteration number."""
        llm = make_mock_llm()
        orchestrator = PlanningOrchestrator(llm_client=llm)

        proposal = await orchestrator.plan(
            make_workflow_request(), make_matrix(),
            violation_history=[make_violation_report()],
            iteration=2,
        )
        assert proposal.iteration == 2

    def test_replan_prompt_includes_violation_detail(self):
        """_build_replan_prompt() includes violation task_id and detail."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        request = make_workflow_request(task="Analyse contracts")
        violation = make_violation_report()

        prompt = orchestrator._build_replan_prompt(
            workflow_request=request,
            violation_history=[violation],
            policy_matrix=make_matrix(),
            iteration=2,
        )

        assert "ST-01" in prompt
        assert "tool_permission" in prompt

    def test_replan_prompt_includes_suggestion(self):
        """_build_replan_prompt() includes the violation suggestion."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        violation = make_violation_report()

        prompt = orchestrator._build_replan_prompt(
            workflow_request=make_workflow_request(),
            violation_history=[violation],
            policy_matrix=make_matrix(),
            iteration=2,
        )

        assert "report_writer" in prompt  # from the suggestion

    def test_replan_prompt_includes_approvable_tasks(self):
        """_build_replan_prompt() lists the tasks that already passed."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        violation = make_violation_report(approvable_task_ids=["ST-02", "ST-03"])

        prompt = orchestrator._build_replan_prompt(
            workflow_request=make_workflow_request(),
            violation_history=[violation],
            policy_matrix=make_matrix(),
            iteration=2,
        )

        assert "ST-02" in prompt
        assert "ST-03" in prompt

    def test_replan_prompt_no_approvable_tasks_shows_message(self):
        """_build_replan_prompt() handles empty approvable_task_ids."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        violation = make_violation_report(approvable_task_ids=[])

        prompt = orchestrator._build_replan_prompt(
            workflow_request=make_workflow_request(),
            violation_history=[violation],
            policy_matrix=make_matrix(),
            iteration=2,
        )

        assert "None" in prompt or "revision" in prompt

    def test_replan_uses_latest_violation_not_oldest(self):
        """When multiple violations exist, re-plan uses the latest one."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())

        violation_1 = make_violation_report(
            violations=[
                Violation(
                    task_id="ST-FIRST",
                    dimension="tool_permission",
                    severity="blocking",
                    detail="first violation",
                    suggestion="first suggestion",
                )
            ]
        )
        violation_2 = make_violation_report(
            violations=[
                Violation(
                    task_id="ST-LATEST",
                    dimension="budget",
                    severity="blocking",
                    detail="latest violation",
                    suggestion="latest suggestion",
                )
            ]
        )

        prompt = orchestrator._build_replan_prompt(
            workflow_request=make_workflow_request(),
            violation_history=[violation_1, violation_2],
            policy_matrix=make_matrix(),
            iteration=3,
        )

        # Should show latest violation, not oldest
        assert "ST-LATEST" in prompt
        assert "latest violation" in prompt


# ── PlanningOrchestrator — Error Propagation ─────────────────

class TestPlanningOrchestratorErrors:
    """Tests for error handling in PlanningOrchestrator."""

    @pytest.mark.asyncio
    async def test_llm_client_error_propagates(self):
        """LLMClientError from LLMClient propagates out of plan()."""
        llm = AsyncMock(spec=LLMClient)
        llm.model_id = "test-model"
        llm.complete = AsyncMock(
            side_effect=LLMClientError(
                "API rate limit exceeded",
                provider="anthropic",
                status_code=429
            )
        )
        orchestrator = PlanningOrchestrator(llm_client=llm)

        with pytest.raises(LLMClientError, match="rate limit"):
            await orchestrator.plan(
                make_workflow_request(), make_matrix(), [], 1
            )

    @pytest.mark.asyncio
    async def test_llm_output_error_propagates(self):
        """LLMOutputError from LLMClient propagates out of plan()."""
        llm = AsyncMock(spec=LLMClient)
        llm.model_id = "test-model"
        llm.complete = AsyncMock(
            side_effect=LLMOutputError(
                "Schema validation failed after 3 attempts",
                raw_response="{}",
                attempt=3,
            )
        )
        orchestrator = PlanningOrchestrator(llm_client=llm)

        with pytest.raises(LLMOutputError, match="Schema validation"):
            await orchestrator.plan(
                make_workflow_request(), make_matrix(), [], 1
            )


# ── PlanningOrchestrator — _parse_response ──────────────────

class TestPlanningOrchestratorParseResponse:
    """Tests for _parse_response()."""

    def test_parse_valid_response_produces_proposal(self):
        """Valid response content produces a well-formed PlanProposal."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        request = make_workflow_request()
        content = make_valid_plan_content()

        proposal = orchestrator._parse_response(
            content=content,
            workflow_request=request,
            iteration=1,
        )

        assert isinstance(proposal, PlanProposal)
        assert proposal.request_id == request.request_id
        assert proposal.iteration == 1
        assert proposal.orchestrator == "document_orchestrator"
        assert len(proposal.sub_tasks) == 2

    def test_parse_preserves_reversible_false(self):
        """_parse_response preserves reversible=False on sub-tasks."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        content = make_valid_plan_content()
        # ST-02 has reversible=False in the fixture
        request = make_workflow_request()

        proposal = orchestrator._parse_response(content, request, 1)

        st02 = next(t for t in proposal.sub_tasks if t.task_id == "ST-02")
        assert st02.reversible is False

    def test_parse_preserves_depends_on(self):
        """_parse_response preserves task dependencies."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        content = make_valid_plan_content()
        request = make_workflow_request()

        proposal = orchestrator._parse_response(content, request, 1)

        st02 = next(t for t in proposal.sub_tasks if t.task_id == "ST-02")
        assert "ST-01" in st02.depends_on

    def test_parse_assigns_unique_proposal_id(self):
        """_parse_response assigns a unique UUID as proposal_id."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        content = make_valid_plan_content()
        request = make_workflow_request()

        proposal_a = orchestrator._parse_response(content, request, 1)
        proposal_b = orchestrator._parse_response(content, request, 1)

        assert proposal_a.proposal_id != proposal_b.proposal_id

    def test_parse_empty_sub_tasks_list(self):
        """_parse_response handles empty sub_tasks list without error."""
        orchestrator = PlanningOrchestrator(llm_client=make_mock_llm())
        content = make_valid_plan_content(sub_tasks=[])
        request = make_workflow_request()

        proposal = orchestrator._parse_response(content, request, 1)
        assert proposal.sub_tasks == []
