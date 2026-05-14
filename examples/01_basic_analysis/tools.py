"""
Example 01: Basic Analysis — Tool Implementations

These are stub tools for the boilerplate.
Replace them with real implementations when you have real infrastructure.

REAL IMPLEMENTATION PATTERN:
  class ReadDbTool(BaseTool):
      name       = "read_db"
      idempotent = True            # safe to retry

      def __init__(self, db_client: MyDatabaseClient):
          self._db = db_client

      async def call(self, query: str, **kwargs) -> ToolResult:
          try:
              rows = await self._db.fetch(query)
              return ToolResult.ok(output={"rows": rows, "count": len(rows)})
          except ConnectionError as e:
              return ToolResult.fail(error=f"DB connection failed: {e}")
"""
from __future__ import annotations

from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry() -> ToolRegistry:
    """
    Build the ToolRegistry for Example 01.

    Stub tools return realistic-looking output.
    Replace with real tool implementations for production.
    """
    registry = ToolRegistry()

    registry.register(StubTool(
        name="read_db",
        idempotent=True,
        output={
            "rows": [
                {"id": 1, "title": "Product Overview",    "type": "overview"},
                {"id": 2, "title": "Technical Specs",     "type": "technical"},
                {"id": 3, "title": "Compliance Summary",  "type": "compliance"},
            ],
            "count": 3,
        },
    ))

    registry.register(StubTool(
        name="llm_extraction",
        idempotent=True,
        output={
            "extracted": [
                {"feature": "Multi-tenant",     "confidence": 0.95},
                {"feature": "Real-time",        "confidence": 0.92},
                {"feature": "SOC 2 compliant",  "confidence": 0.98},
            ],
        },
    ))

    registry.register(StubTool(
        name="llm_summarization",
        idempotent=True,
        output={
            "summary": (
                "The product is a multi-tenant, real-time platform "
                "with SOC 2 Type II compliance and 99.9% uptime SLA."
            ),
            "word_count": 22,
        },
    ))

    return registry
