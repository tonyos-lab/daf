"""
daf.testing — testing infrastructure for DAF-based applications.

This module ships with DAF but is intended for use in tests and
development environments only. Never import from daf.testing in
production code.

PUBLIC API:

  MockLLMClient
    Drop-in replacement for any LLMClient implementation.
    Returns developer-provided plan dicts without making API calls.
    Use in tests regardless of which LLM provider you use in production.

  FixturePlanBuilder
    Fluent builder for valid PlanProposal dicts.
    Use with MockLLMClient to construct test scenarios.

ALSO AVAILABLE (in production modules, usable in tests):

  from daf.tools.stub_tool import StubTool
  from daf.agents.stub_agent import StubAgent
  from daf.runtime.human_review_gateway import StubHumanReviewGateway
  from daf.runtime.audit_store import InMemoryAuditStore
  from daf.runtime.checkpoint_store import InMemoryCheckpointStore

SWITCHING BETWEEN REAL AND MOCK:

  # Production — use YOUR LLMClient implementation
  from myapp.llm import MyClient
  llm = MyClient(...)

  # Testing — use MockLLMClient regardless of provider
  from daf.testing import MockLLMClient, FixturePlanBuilder
  plan = FixturePlanBuilder()\\
      .with_task("ST-01", agent="analyst", tools=["read_db"])\\
      .build()
  llm = MockLLMClient(responses=[plan])

  # Same loop constructor — only llm_client changes
  loop = GovernedAgenticLoop(llm_client=llm, ...)

IMPLEMENTING LLMClient FOR YOUR PROVIDER:

  from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage

  class MyClient(LLMClient):
      async def complete(self, system, user, schema) -> LLMResponse: ...
      def estimate_cost(self, input_tokens, output_tokens) -> float: ...
      @property
      def model_id(self) -> str: ...
"""
from daf.testing.mock_llm_client import MockLLMClient
from daf.testing.fixture_builder import FixturePlanBuilder, VALID_TASK_TYPES

__all__ = [
    "MockLLMClient",
    "FixturePlanBuilder",
    "VALID_TASK_TYPES",
]
