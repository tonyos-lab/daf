"""
Unit tests for BaseAgent, AgentResult, AgentRegistry, and StubAgent.

Coverage:
  - AgentResult ok/fail constructors and fields
  - BaseAgent subclass enforcement (role required)
  - BaseAgent.run() wraps execute() with error handling
  - AgentRegistry register, instantiate, has, roles
  - AgentRegistry error cases (not found, duplicate, wrong type)
  - StubAgent run, failure, run history, reset
  - AgentExecutionError wrapping of unexpected exceptions
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone

from daf.runtime.agent import (
    BaseAgent, AgentResult,
    AgentNotFoundError, AgentAlreadyRegisteredError, AgentExecutionError,
)
from daf.runtime.agent_registry import AgentRegistry
from daf.agents.stub_agent import StubAgent
from daf.models.plan_proposal import SubTask


# ── Fixtures ─────────────────────────────────────────────────

def make_subtask(**overrides) -> SubTask:
    defaults = dict(
        task_id="ST-01", name="test",
        task_type="llm_extraction",
        agent_required="stub_agent",
        tools_required=["read_db"],
        data_required=["test_data"],
        depends_on=[],
        estimated_cost=0.02,
        reversible=True,
        rationale="test task",
    )
    defaults.update(overrides)
    return SubTask(**defaults)


class MockContext:
    """Minimal mock ScopedContext for testing."""
    pass


# ── AgentResult ──────────────────────────────────────────────

class TestAgentResult:

    def test_ok_sets_success_true(self):
        result = AgentResult.ok(task_id="ST-01", output={"data": [1, 2]})
        assert result.success is True
        assert result.task_id == "ST-01"
        assert result.output == {"data": [1, 2]}
        assert result.error is None

    def test_fail_sets_success_false(self):
        result = AgentResult.fail(task_id="ST-01", error="extraction failed")
        assert result.success is False
        assert result.task_id == "ST-01"
        assert result.error == "extraction failed"
        assert result.output is None

    def test_ok_with_cost(self):
        result = AgentResult.ok(task_id="ST-01", output=None, cost_usd=0.034)
        assert result.cost_usd == 0.034

    def test_fail_with_cost(self):
        result = AgentResult.fail(task_id="ST-01", error="err", cost_usd=0.001)
        assert result.cost_usd == 0.001

    def test_ok_accepts_metadata(self):
        result = AgentResult.ok(task_id="ST-01", output=None, tokens=500)
        assert result.metadata["tokens"] == 500

    def test_fail_accepts_metadata(self):
        result = AgentResult.fail(task_id="ST-01", error="err", retry=True)
        assert result.metadata["retry"] is True

    def test_default_cost_is_zero(self):
        result = AgentResult.ok(task_id="ST-01", output=None)
        assert result.cost_usd == 0.0

    def test_task_id_preserved(self):
        result = AgentResult.ok(task_id="ST-99", output=None)
        assert result.task_id == "ST-99"


# ── BaseAgent Enforcement ────────────────────────────────────

class TestBaseAgentEnforcement:

    def test_concrete_subclass_without_role_raises(self):
        """Concrete subclass missing role raises TypeError."""
        with pytest.raises(TypeError, match="role"):
            class BadAgent(BaseAgent):
                async def execute(self, task, context):
                    return AgentResult.ok(task_id="x", output=None)

    def test_concrete_subclass_with_role_ok(self):
        """Concrete subclass with role constructs without error."""
        class GoodAgent(BaseAgent):
            role = "good_agent"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output=None)

        agent = GoodAgent()
        assert agent.role == "good_agent"

    def test_abstract_subclass_not_enforced(self):
        """Abstract intermediate classes are not enforced."""
        class AbstractAgent(BaseAgent):
            """Abstract intermediate — no role required."""
            @abstractmethod_helper
            async def extra(self): ...

        # No TypeError raised

    def test_role_must_be_string(self):
        """role must be a str, not int or other type."""
        with pytest.raises(TypeError, match="role"):
            class IntRoleAgent(BaseAgent):
                role = 42  # not a string
                async def execute(self, task, context):
                    return AgentResult.ok(task_id="x", output=None)

    def test_repr_includes_role(self):
        agent = StubAgent(role="test_role")
        assert "test_role" in repr(agent)


# Helper for abstract intermediate test
def abstractmethod_helper(fn):
    fn.__isabstractmethod__ = True
    return fn


# ── BaseAgent.run() error handling ───────────────────────────

class TestBaseAgentRun:
    """run() wraps execute() and handles errors correctly."""

    @pytest.mark.asyncio
    async def test_run_returns_execute_result(self):
        """run() returns the result from execute()."""
        agent = StubAgent(output={"extracted": "data"})
        task  = make_subtask()
        ctx   = MockContext()

        result = await agent.run(task=task, context=ctx)

        assert result.success is True
        assert result.output == {"extracted": "data"}
        assert result.task_id == "ST-01"

    @pytest.mark.asyncio
    async def test_run_wraps_unexpected_exception_as_agent_execution_error(self):
        """
        Unexpected exceptions from execute() are wrapped in AgentExecutionError.
        run() never lets raw exceptions propagate.
        """
        class ExplodingAgent(BaseAgent):
            role = "exploding_agent"
            async def execute(self, task, context):
                raise RuntimeError("unexpected database error")

        agent  = ExplodingAgent()
        task   = make_subtask(task_id="ST-BOOM")
        ctx    = MockContext()

        with pytest.raises(AgentExecutionError) as exc_info:
            await agent.run(task=task, context=ctx)

        err = exc_info.value
        assert err.role    == "exploding_agent"
        assert err.task_id == "ST-BOOM"
        assert "unexpected database error" in err.reason

    @pytest.mark.asyncio
    async def test_run_reraises_agent_execution_error_unchanged(self):
        """
        If execute() raises AgentExecutionError directly,
        run() re-raises it without wrapping.
        """
        class DirectErrorAgent(BaseAgent):
            role = "direct_error_agent"
            async def execute(self, task, context):
                raise AgentExecutionError(
                    role="direct_error_agent",
                    task_id=task.task_id,
                    reason="explicit error from execute",
                )

        agent = DirectErrorAgent()
        task  = make_subtask(task_id="ST-ERR")
        ctx   = MockContext()

        with pytest.raises(AgentExecutionError) as exc_info:
            await agent.run(task=task, context=ctx)

        assert exc_info.value.reason == "explicit error from execute"

    @pytest.mark.asyncio
    async def test_run_passes_task_and_context_to_execute(self):
        """run() passes task and context through to execute()."""
        received = {}

        class RecordingAgent(BaseAgent):
            role = "recording_agent"
            async def execute(self, task, context):
                received["task"]    = task
                received["context"] = context
                return AgentResult.ok(task_id=task.task_id, output=None)

        agent = RecordingAgent()
        task  = make_subtask(task_id="ST-RECORD")
        ctx   = MockContext()

        await agent.run(task=task, context=ctx)

        assert received["task"]    is task
        assert received["context"] is ctx


# ── StubAgent ─────────────────────────────────────────────────

class TestStubAgent:

    @pytest.mark.asyncio
    async def test_run_returns_configured_output(self):
        """StubAgent returns configured output."""
        agent  = StubAgent(output={"result": "extracted_text"})
        task   = make_subtask()
        ctx    = MockContext()

        result = await agent.run(task=task, context=ctx)

        assert result.success is True
        assert result.output == {"result": "extracted_text"}

    @pytest.mark.asyncio
    async def test_run_returns_none_output_by_default(self):
        """Default output is None."""
        agent  = StubAgent()
        result = await agent.run(task=make_subtask(), context=MockContext())
        assert result.success is True
        assert result.output is None

    @pytest.mark.asyncio
    async def test_run_fails_when_configured(self):
        """StubAgent returns failure when should_fail=True."""
        agent = StubAgent(should_fail=True, error="extraction failed")
        result = await agent.run(task=make_subtask(), context=MockContext())
        assert result.success is False
        assert result.error == "extraction failed"

    @pytest.mark.asyncio
    async def test_run_records_history(self):
        """Every run is recorded in self.runs."""
        agent  = StubAgent()
        task_a = make_subtask(task_id="ST-01")
        task_b = make_subtask(task_id="ST-02")

        await agent.run(task=task_a, context=MockContext())
        await agent.run(task=task_b, context=MockContext())

        assert len(agent.runs) == 2
        assert agent.runs[0]["task_id"] == "ST-01"
        assert agent.runs[1]["task_id"] == "ST-02"

    @pytest.mark.asyncio
    async def test_result_includes_task_id(self):
        """AgentResult.task_id matches the sub-task's task_id."""
        agent  = StubAgent()
        task   = make_subtask(task_id="ST-XYZ")
        result = await agent.run(task=task, context=MockContext())
        assert result.task_id == "ST-XYZ"

    @pytest.mark.asyncio
    async def test_result_includes_cost(self):
        """AgentResult.cost_usd matches configured cost."""
        agent  = StubAgent(cost_usd=0.042)
        result = await agent.run(task=make_subtask(), context=MockContext())
        assert result.cost_usd == 0.042

    def test_reset_clears_run_history(self):
        """reset() clears the run history."""
        agent = StubAgent()
        agent.runs.append({"task_id": "ST-01"})
        agent.runs.append({"task_id": "ST-02"})
        agent.reset()
        assert len(agent.runs) == 0

    def test_custom_role_name(self):
        """StubAgent can be given a custom role name."""
        agent = StubAgent(role="document_reader")
        assert agent.role == "document_reader"

    def test_repr_includes_role_and_runs(self):
        agent = StubAgent(role="test_role")
        r = repr(agent)
        assert "test_role" in r
        assert "0" in r  # 0 runs


# ── AgentRegistry ────────────────────────────────────────────

class TestAgentRegistry:

    def make_populated_registry(self) -> AgentRegistry:
        registry = AgentRegistry()
        # Register two distinct agent classes with different roles

        class ReaderAgent(BaseAgent):
            role = "document_reader"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output=None)

        class WriterAgent(BaseAgent):
            role = "report_writer"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output=None)

        registry.register(ReaderAgent)
        registry.register(WriterAgent)
        return registry

    def test_register_and_has(self):
        """Registered role can be found with has()."""
        registry = self.make_populated_registry()
        assert registry.has("document_reader") is True
        assert registry.has("report_writer") is True

    def test_has_returns_false_for_unregistered(self):
        """has() returns False for unregistered role."""
        registry = AgentRegistry()
        assert registry.has("nonexistent") is False

    def test_duplicate_registration_raises(self):
        """Registering same role twice raises AgentAlreadyRegisteredError."""
        registry = AgentRegistry()

        class AgentA(BaseAgent):
            role = "duplicate_role"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output=None)

        class AgentB(BaseAgent):
            role = "duplicate_role"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output=None)

        registry.register(AgentA)
        with pytest.raises(AgentAlreadyRegisteredError):
            registry.register(AgentB)

    def test_replace_allows_override(self):
        """replace=True allows overriding existing registration."""
        registry = AgentRegistry()

        class AgentA(BaseAgent):
            role = "replaceable"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output="A")

        class AgentB(BaseAgent):
            role = "replaceable"
            async def execute(self, task, context):
                return AgentResult.ok(task_id=task.task_id, output="B")

        registry.register(AgentA)
        registry.register(AgentB, replace=True)
        assert registry.get_class("replaceable") is AgentB

    def test_register_non_agent_class_raises(self):
        """Registering a non-BaseAgent class raises TypeError."""
        registry = AgentRegistry()
        with pytest.raises(TypeError):
            registry.register(str)  # not a BaseAgent subclass

    def test_instantiate_returns_agent_instance(self):
        """instantiate() returns a BaseAgent instance for the role."""
        registry = self.make_populated_registry()
        ctx      = MockContext()
        agent    = registry.instantiate("document_reader", ctx)
        assert isinstance(agent, BaseAgent)
        assert agent.role == "document_reader"

    def test_instantiate_unknown_role_raises(self):
        """instantiate() raises AgentNotFoundError for unregistered role."""
        registry = AgentRegistry()
        with pytest.raises(AgentNotFoundError) as exc_info:
            registry.instantiate("ghost_agent", MockContext())
        assert "ghost_agent" in str(exc_info.value)

    def test_instantiate_creates_fresh_instance_each_time(self):
        """Each instantiate() call returns a new instance."""
        registry = self.make_populated_registry()
        ctx      = MockContext()
        agent_a  = registry.instantiate("document_reader", ctx)
        agent_b  = registry.instantiate("document_reader", ctx)
        assert agent_a is not agent_b

    def test_get_class_returns_the_class(self):
        """get_class() returns the registered class, not an instance."""
        registry = self.make_populated_registry()
        cls = registry.get_class("document_reader")
        assert isinstance(cls, type)
        assert issubclass(cls, BaseAgent)

    def test_get_class_unregistered_raises(self):
        """get_class() raises AgentNotFoundError for unknown role."""
        registry = AgentRegistry()
        with pytest.raises(AgentNotFoundError):
            registry.get_class("unknown")

    def test_roles_returns_all_registered(self):
        """roles() returns all registered role names."""
        registry = self.make_populated_registry()
        roles = registry.roles()
        assert "document_reader" in roles
        assert "report_writer" in roles
        assert len(roles) == 2

    def test_len_returns_count(self):
        """len() returns number of registered roles."""
        registry = self.make_populated_registry()
        assert len(registry) == 2

    def test_repr_includes_role_names(self):
        """repr() includes registered role names."""
        registry = self.make_populated_registry()
        r = repr(registry)
        assert "document_reader" in r
        assert "report_writer" in r


# ── AgentRegistry + StubAgent integration ───────────────────

class TestAgentRegistryWithStubAgent:
    """
    Verify AgentRegistry works correctly with StubAgent.
    This is how tests will configure agents throughout Phase 2.
    """

    @pytest.mark.asyncio
    async def test_register_stub_agent_class_and_instantiate(self):
        """
        Register a StubAgent subclass and instantiate it through the registry.
        """
        registry = AgentRegistry()

        class TestReaderAgent(StubAgent):
            role   = "test_reader"
            def __init__(self):
                super().__init__(
                    role="test_reader",
                    output={"rows": [1, 2, 3]},
                )

        registry.register(TestReaderAgent)
        ctx   = MockContext()
        agent = registry.instantiate("test_reader", ctx)

        assert isinstance(agent, TestReaderAgent)
        assert agent.role == "test_reader"

        task   = make_subtask(task_id="ST-TEST", agent_required="test_reader")
        result = await agent.run(task=task, context=ctx)

        assert result.success is True
        assert result.output == {"rows": [1, 2, 3]}
        assert result.task_id == "ST-TEST"
