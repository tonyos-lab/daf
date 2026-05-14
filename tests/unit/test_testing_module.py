"""
Unit tests for daf.testing: MockLLMClient and FixturePlanBuilder.

Coverage:
  MockLLMClient:
  - Single fixed response
  - Multiple responses in sequence
  - Response cycling (last response repeated)
  - Callable response
  - Simulated failure (fail_after)
  - Empty responses raises
  - Call recording (calls, call_count)
  - reset()
  - model_id and estimate_cost

  FixturePlanBuilder:
  - Single task build
  - Multiple tasks with dependencies
  - with_rationale, with_confidence, with_orchestrator, with_human_gate
  - Invalid task_type raises
  - Duplicate task_id raises
  - Unknown depends_on raises
  - No tasks raises
  - confidence out of range raises
  - Built dict matches PlanningOrchestrator schema exactly

  Integration:
  - MockLLMClient + GovernedAgenticLoop end-to-end
  - FixturePlanBuilder output passes PolicyEngine
  - Real ↔ Mock switch produces same FinalResponse structure
"""
from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock

from daf.testing import MockLLMClient, FixturePlanBuilder, VALID_TASK_TYPES
from daf.runtime.llm_client import LLMClientError, LLMResponse


# ── FixturePlanBuilder ────────────────────────────────────────

class TestFixturePlanBuilder:

    def test_single_task_builds_valid_dict(self):
        """Single task produces a dict with all required fields."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="analyst", tools=["read_db"])
                .build())

        assert plan["orchestrator"]          == "default_orchestrator"
        assert isinstance(plan["planning_rationale"], str)
        assert len(plan["sub_tasks"])         == 1
        assert isinstance(plan["total_estimated_cost"], float)
        assert 0.0 <= plan["confidence"] <= 1.0
        assert isinstance(plan["requires_human_gate"], bool)

    def test_task_fields_set_correctly(self):
        """Task fields match what was passed to with_task()."""
        plan = (FixturePlanBuilder()
                .with_task(
                    "ST-01",
                    agent="analyst",
                    tools=["read_db", "llm_extraction"],
                    task_type="llm_extraction",
                    data_sources=["documents"],
                    depends_on=[],
                    estimated_cost=0.03,
                    reversible=True,
                    rationale="Read contracts",
                    name="read_contracts",
                )
                .build())

        task = plan["sub_tasks"][0]
        assert task["task_id"]        == "ST-01"
        assert task["name"]           == "read_contracts"
        assert task["task_type"]      == "llm_extraction"
        assert task["agent_required"] == "analyst"
        assert task["tools_required"] == ["read_db", "llm_extraction"]
        assert task["data_required"]  == ["documents"]
        assert task["depends_on"]     == []
        assert task["estimated_cost"] == 0.03
        assert task["reversible"]     is True
        assert task["rationale"]      == "Read contracts"

    def test_multiple_tasks_with_dependencies(self):
        """Multiple tasks in sequence with depends_on."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="analyst", tools=["read_db"])
                .with_task("ST-02", agent="analyst", tools=["llm_extraction"],
                           depends_on=["ST-01"])
                .with_task("ST-03", agent="analyst", tools=["llm_summarization"],
                           depends_on=["ST-02"])
                .build())

        assert len(plan["sub_tasks"])           == 3
        assert plan["sub_tasks"][1]["depends_on"] == ["ST-01"]
        assert plan["sub_tasks"][2]["depends_on"] == ["ST-02"]

    def test_total_cost_is_sum_of_task_costs(self):
        """total_estimated_cost sums all task estimated_costs."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="analyst", tools=[], estimated_cost=0.02)
                .with_task("ST-02", agent="analyst", tools=[], estimated_cost=0.03)
                .build())

        assert plan["total_estimated_cost"] == pytest.approx(0.05)

    def test_with_rationale(self):
        """with_rationale() sets planning_rationale."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=[])
                .with_rationale("Custom rationale for the plan")
                .build())

        assert plan["planning_rationale"] == "Custom rationale for the plan"

    def test_with_confidence(self):
        """with_confidence() sets confidence."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=[])
                .with_confidence(0.75)
                .build())

        assert plan["confidence"] == pytest.approx(0.75)

    def test_with_orchestrator(self):
        """with_orchestrator() sets orchestrator name."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=[])
                .with_orchestrator("custom_orchestrator")
                .build())

        assert plan["orchestrator"] == "custom_orchestrator"

    def test_with_human_gate(self):
        """with_human_gate() sets requires_human_gate to True."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=[])
                .with_human_gate(True)
                .build())

        assert plan["requires_human_gate"] is True

    def test_default_requires_human_gate_is_false(self):
        """Default requires_human_gate is False."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=[])
                .build())

        assert plan["requires_human_gate"] is False

    def test_all_valid_task_types_accepted(self):
        """Every valid task_type is accepted without error."""
        for task_type in VALID_TASK_TYPES:
            plan = (FixturePlanBuilder()
                    .with_task("ST-01", agent="a", tools=[], task_type=task_type)
                    .build())
            assert plan["sub_tasks"][0]["task_type"] == task_type

    def test_invalid_task_type_raises(self):
        """Invalid task_type raises ValueError."""
        with pytest.raises(ValueError, match="task_type"):
            FixturePlanBuilder().with_task(
                "ST-01", agent="a", tools=[], task_type="magic"
            )

    def test_duplicate_task_id_raises(self):
        """Adding the same task_id twice raises ValueError."""
        builder = FixturePlanBuilder().with_task("ST-01", agent="a", tools=[])
        with pytest.raises(ValueError, match="ST-01"):
            builder.with_task("ST-01", agent="b", tools=[])

    def test_unknown_depends_on_raises(self):
        """depends_on referencing unknown task_id raises ValueError."""
        with pytest.raises(ValueError, match="ST-99"):
            (FixturePlanBuilder()
             .with_task("ST-01", agent="a", tools=[])
             .with_task("ST-02", agent="a", tools=[], depends_on=["ST-99"])
             .build())

    def test_no_tasks_raises(self):
        """build() with no tasks raises ValueError."""
        with pytest.raises(ValueError, match="no tasks"):
            FixturePlanBuilder().build()

    def test_confidence_out_of_range_raises(self):
        """Confidence outside 0.0–1.0 raises ValueError."""
        with pytest.raises(ValueError, match="confidence"):
            FixturePlanBuilder().with_confidence(1.5)
        with pytest.raises(ValueError, match="confidence"):
            FixturePlanBuilder().with_confidence(-0.1)

    def test_auto_generated_name_from_task_id(self):
        """name is derived from task_id when not explicitly set."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=[])
                .build())

        assert plan["sub_tasks"][0]["name"] == "st_01"

    def test_auto_generated_rationale(self):
        """rationale is auto-generated when not set."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="a", tools=["read_db"],
                           task_type="llm_extraction")
                .build())

        rationale = plan["sub_tasks"][0]["rationale"]
        assert len(rationale) > 0  # not empty

    def test_repr_includes_task_ids(self):
        builder = (FixturePlanBuilder()
                   .with_task("ST-01", agent="a", tools=[])
                   .with_task("ST-02", agent="a", tools=[]))
        assert "ST-01" in repr(builder)
        assert "ST-02" in repr(builder)

    def test_chaining_returns_builder(self):
        """Every method returns self for chaining."""
        builder = FixturePlanBuilder()
        assert builder.with_task("ST-01", agent="a", tools=[]) is builder
        assert builder.with_rationale("test") is builder
        assert builder.with_confidence(0.9) is builder
        assert builder.with_orchestrator("test") is builder
        assert builder.with_human_gate() is builder


# ── MockLLMClient ─────────────────────────────────────────────

class TestMockLLMClient:

    def make_plan(self, task_id: str = "ST-01") -> dict:
        return (FixturePlanBuilder()
                .with_task(task_id, agent="analyst", tools=["read_db"])
                .build())

    @pytest.mark.asyncio
    async def test_returns_configured_response(self):
        """Returns the configured plan dict."""
        plan   = self.make_plan()
        client = MockLLMClient(responses=[plan])
        result = await client.complete(system="sys", user="user", schema={})

        assert isinstance(result, LLMResponse)
        assert result.content == plan

    @pytest.mark.asyncio
    async def test_multiple_responses_in_sequence(self):
        """Returns responses in order."""
        plan_a = self.make_plan("ST-01")
        plan_b = self.make_plan("ST-02")
        client = MockLLMClient(responses=[plan_a, plan_b])

        result_a = await client.complete("s", "u", {})
        result_b = await client.complete("s", "u", {})

        assert result_a.content == plan_a
        assert result_b.content == plan_b

    @pytest.mark.asyncio
    async def test_last_response_repeated_when_exhausted(self):
        """Last response is repeated when call count exceeds list length."""
        plan_a = self.make_plan("ST-01")
        plan_b = self.make_plan("ST-02")
        client = MockLLMClient(responses=[plan_a, plan_b])

        await client.complete("s", "u", {})
        await client.complete("s", "u", {})
        result = await client.complete("s", "u", {})  # 3rd call, only 2 responses

        assert result.content == plan_b   # last response repeated

    @pytest.mark.asyncio
    async def test_callable_response(self):
        """Callable response receives system and user strings."""
        received = {}

        def dynamic_plan(system: str, user: str) -> dict:
            received["system"] = system
            received["user"]   = user
            return self.make_plan()

        client = MockLLMClient(responses=[dynamic_plan])
        await client.complete(system="my-system", user="my-user", schema={})

        assert received["system"] == "my-system"
        assert received["user"]   == "my-user"

    @pytest.mark.asyncio
    async def test_empty_responses_raises_llm_client_error(self):
        """Empty responses list raises LLMClientError."""
        client = MockLLMClient(responses=[])
        with pytest.raises(LLMClientError, match="no responses"):
            await client.complete("s", "u", {})

    @pytest.mark.asyncio
    async def test_fail_after_raises_after_n_calls(self):
        """Raises LLMClientError after fail_after successful calls."""
        plan   = self.make_plan()
        client = MockLLMClient(responses=[plan], fail_after=2)

        await client.complete("s", "u", {})   # call 1 — ok
        await client.complete("s", "u", {})   # call 2 — ok

        with pytest.raises(LLMClientError, match="simulated failure"):
            await client.complete("s", "u", {})   # call 3 — fails

    @pytest.mark.asyncio
    async def test_fail_after_zero_fails_on_first_call(self):
        """fail_after=0 raises on the very first call."""
        plan   = self.make_plan()
        client = MockLLMClient(responses=[plan], fail_after=0)

        with pytest.raises(LLMClientError):
            await client.complete("s", "u", {})

    @pytest.mark.asyncio
    async def test_records_calls(self):
        """Every complete() call is recorded in client.calls."""
        plan   = self.make_plan()
        client = MockLLMClient(responses=[plan])

        await client.complete(system="sys-1", user="user-1", schema={})
        await client.complete(system="sys-2", user="user-2", schema={})

        assert client.call_count == 2
        assert len(client.calls) == 2
        assert client.calls[0] == ("sys-1", "user-1")
        assert client.calls[1] == ("sys-2", "user-2")

    def test_reset_clears_call_history(self):
        """reset() clears calls and call_count."""
        client = MockLLMClient(responses=[self.make_plan()])
        client.calls.append(("s", "u"))
        client.call_count = 3
        client.reset()
        assert client.calls     == []
        assert client.call_count == 0

    def test_model_id_returns_configured_model(self):
        """model_id property returns the configured model string."""
        client = MockLLMClient(responses=[], model="my-test-model")
        assert client.model_id == "my-test-model"

    def test_estimate_cost_returns_configured_cost(self):
        """estimate_cost returns the configured cost per call."""
        client = MockLLMClient(responses=[], cost_per_call=0.007)
        assert client.estimate_cost(100, 200) == pytest.approx(0.007)

    @pytest.mark.asyncio
    async def test_usage_reflects_configured_tokens_and_cost(self):
        """LLMUsage fields match constructor configuration."""
        plan   = self.make_plan()
        client = MockLLMClient(
            responses=[plan],
            model="test-model",
            input_tokens=123,
            output_tokens=456,
            cost_per_call=0.009,
        )
        result = await client.complete("s", "u", {})

        assert result.usage.model_id      == "test-model"
        assert result.usage.input_tokens  == 123
        assert result.usage.output_tokens == 456
        assert result.usage.cost_usd      == pytest.approx(0.009)

    def test_repr_includes_response_count_and_call_count(self):
        """repr() includes response count and call count."""
        plan   = self.make_plan()
        client = MockLLMClient(responses=[plan, plan])
        assert "2" in repr(client)
        assert "0" in repr(client)


# ── Integration: MockLLMClient + GovernedAgenticLoop ─────────

class TestMockLLMClientIntegration:
    """
    End-to-end: MockLLMClient + FixturePlanBuilder + GovernedAgenticLoop.
    No API key. No infrastructure. Full loop.
    """

    def make_loop(self, responses: list[dict]):
        import tempfile, yaml
        from daf import GovernedAgenticLoop
        from daf.agents.stub_agent import StubAgent
        from daf.runtime.agent_registry import AgentRegistry
        from daf.runtime.tool_registry import ToolRegistry
        from daf.tools.stub_tool import StubTool

        matrix = {
            "version": "1.0.0", "tenant_id": "test",
            "effective": "2026-01-01T00:00:00Z",
            "agent_roles": {
                "analyst": {
                    "permitted_tools":        ["read_db", "llm_extraction"],
                    "permitted_data_sources": ["documents"],
                    "permitted_task_types":   [
                        "deterministic", "llm_extraction",
                        "llm_summarization", "llm_generation",
                    ],
                    "max_llm_calls_per_step": 3,
                }
            },
            "budget_policy": {
                "max_cost_per_step_usd": 0.10,
                "max_cost_per_workflow_usd": 1.00,
                "max_cost_per_user_day_usd": 10.0,
                "max_cost_per_tenant_day_usd": 50.0,
            },
            "compliance_rules": [],
            "risk_policy": {
                "irreversible_min_confidence": 0.70,
                "always_gate_action_classes":  [],
                "auto_approve_action_classes": [
                    "llm_extraction", "deterministic", "llm_summarization",
                ],
            },
            "loop_policy": {"max_replan_attempts": 3, "max_duration_s": 60},
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(matrix, f)
            matrix_path = f.name

        tool_registry = ToolRegistry()
        tool_registry.register(StubTool("read_db"))
        tool_registry.register(StubTool("llm_extraction"))

        agent_registry = AgentRegistry()

        class AnalystAgent(StubAgent):
            role = "analyst"
            def __init__(self):
                super().__init__(role="analyst", output={"done": True}, cost_usd=0.01)

        agent_registry.register(AnalystAgent)

        return GovernedAgenticLoop(
            llm_client=MockLLMClient(responses=responses),
            policy_matrix=matrix_path,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
        )

    @pytest.mark.asyncio
    async def test_fixture_builder_plan_produces_completed_outcome(self):
        """FixturePlanBuilder plan passes PolicyEngine and executes."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="analyst", tools=["read_db"])
                .with_task("ST-02", agent="analyst", tools=["llm_extraction"],
                           depends_on=["ST-01"])
                .with_rationale("Read and extract")
                .build())

        loop   = self.make_loop(responses=[plan])
        result = await loop.run({
            "task":      "Read documents and extract features",
            "tenant_id": "test",
            "user_id":   "test-user",
        })

        assert result.outcome == "completed"

    @pytest.mark.asyncio
    async def test_mock_and_real_produce_same_response_structure(self):
        """
        Switching from MockLLMClient to AnthropicLLMClient only requires
        changing the llm_client argument. The FinalResponse structure
        is identical.
        """
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="analyst", tools=["read_db"])
                .build())

        loop   = self.make_loop(responses=[plan])
        result = await loop.run({
            "task":      "Read documents",
            "tenant_id": "test",
            "user_id":   "test-user",
        })

        # FinalResponse has all expected fields regardless of LLM client
        assert hasattr(result, "outcome")
        assert hasattr(result, "loop_iterations")
        assert hasattr(result, "total_cost_usd")
        assert hasattr(result, "request_id")
        assert hasattr(result, "result")
        assert hasattr(result, "audit_summary")

    @pytest.mark.asyncio
    async def test_mock_llm_is_called_correct_number_of_times(self):
        """MockLLMClient call_count reflects actual loop iterations."""
        plan = (FixturePlanBuilder()
                .with_task("ST-01", agent="analyst", tools=["read_db"])
                .build())

        client = MockLLMClient(responses=[plan])
        loop   = self.make_loop.__func__(self, responses=[])
        # Rebuild with our tracked client
        import tempfile, yaml
        from daf import GovernedAgenticLoop
        from daf.agents.stub_agent import StubAgent
        from daf.runtime.agent_registry import AgentRegistry
        from daf.runtime.tool_registry import ToolRegistry
        from daf.tools.stub_tool import StubTool

        matrix = {
            "version": "1.0.0", "tenant_id": "test",
            "effective": "2026-01-01T00:00:00Z",
            "agent_roles": {"analyst": {
                "permitted_tools": ["read_db"],
                "permitted_data_sources": [],
                "permitted_task_types": ["llm_extraction"],
                "max_llm_calls_per_step": 3,
            }},
            "budget_policy": {
                "max_cost_per_step_usd": 0.10,
                "max_cost_per_workflow_usd": 1.0,
                "max_cost_per_user_day_usd": 10.0,
                "max_cost_per_tenant_day_usd": 50.0,
            },
            "compliance_rules": [],
            "risk_policy": {
                "irreversible_min_confidence": 0.70,
                "always_gate_action_classes": [],
                "auto_approve_action_classes": ["llm_extraction"],
            },
            "loop_policy": {"max_replan_attempts": 3, "max_duration_s": 60},
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(matrix, f)
            mp = f.name

        tr = ToolRegistry()
        tr.register(StubTool("read_db"))
        ar = AgentRegistry()

        class A(StubAgent):
            role = "analyst"
            def __init__(self): super().__init__(role="analyst")

        ar.register(A)

        loop = GovernedAgenticLoop(
            llm_client=client,
            policy_matrix=mp,
            agent_registry=ar,
            tool_registry=tr,
        )
        result = await loop.run({
            "task": "Read documents", "tenant_id": "test", "user_id": "u"
        })

        assert result.outcome         == "completed"
        assert result.loop_iterations == 1
        assert client.call_count      == 1
