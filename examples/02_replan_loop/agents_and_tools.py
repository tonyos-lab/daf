"""
Example 02: Re-planning Loop — Agent and Tool Implementations
"""
from __future__ import annotations

from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


class AnalystAgent(StubAgent):
    role = "analyst"
    def __init__(self) -> None:
        super().__init__(
            role="analyst",
            output={"status": "completed", "findings": ["Feature A", "Feature B"]},
            cost_usd=0.02,
        )


def build_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(AnalystAgent)
    return registry


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(StubTool(
        "read_db", idempotent=True,
        output={"rows": [{"id": 1, "content": "Document content"}]},
    ))
    registry.register(StubTool(
        "llm_extraction", idempotent=True,
        output={"extracted": ["Finding A", "Finding B"]},
    ))
    return registry
