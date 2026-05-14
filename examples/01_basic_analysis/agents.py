"""
Example 01: Basic Analysis — Agent Implementations

These are stub agents for the boilerplate.
Replace them with real implementations when you have real infrastructure.

REAL IMPLEMENTATION PATTERN:
  class AnalystAgent(BaseAgent):
      role = "analyst"

      def __init__(self, db_client: MyDatabaseClient):
          self._db = db_client

      async def execute(self, task: SubTask, context: ScopedContext) -> AgentResult:
          # Check budget before LLM calls
          if context.budget and not context.budget.check_and_reserve(0.02):
              return AgentResult.fail(task.task_id, "Budget exhausted")

          # Use only permitted tools
          tool   = context.tools.get("read_db")
          result = await tool.call(query="SELECT * FROM documents LIMIT 10")

          if not result.success:
              return AgentResult.fail(task.task_id, result.error, cost_usd=0.0)

          # Record actual cost
          if context.budget:
              context.budget.record_actual(actual_cost=0.018, reserved_cost=0.02)

          return AgentResult.ok(task.task_id, output=result.output, cost_usd=0.018)
"""
from __future__ import annotations

from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class AnalystAgent(StubAgent):
    """
    Analyst agent for Example 01.

    In the boilerplate: returns stub output.
    In production: replace with a real BaseAgent subclass
    that calls your actual data sources and LLM tools.
    """
    role = "analyst"

    def __init__(self) -> None:
        super().__init__(
            role="analyst",
            output={
                "status":   "completed",
                "findings": [
                    "Product supports multi-tenant deployment",
                    "Real-time processing with sub-100ms latency",
                    "SOC 2 Type II compliant",
                    "API-first architecture with REST and gRPC",
                    "99.9% uptime SLA with automatic failover",
                ],
                "document_count": 3,
                "confidence":     0.91,
            },
            cost_usd=0.02,
        )


def build_agent_registry() -> AgentRegistry:
    """Build the AgentRegistry for Example 01."""
    registry = AgentRegistry()
    registry.register(AnalystAgent)
    return registry
