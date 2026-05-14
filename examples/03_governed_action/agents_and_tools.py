"""Example 03: Governed Action — Agent and Tool Implementations"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


class AnalystAgent(StubAgent):
    role = "analyst"
    def __init__(self):
        super().__init__(
            role="analyst",
            output={"status": "completed", "report": "Generated report content"},
            cost_usd=0.02,
        )


def build_agent_registry():
    r = AgentRegistry()
    r.register(AnalystAgent)
    return r


def build_tool_registry():
    r = ToolRegistry()
    r.register(StubTool("read_db", idempotent=True,
                        output={"rows": [{"id": 1, "content": "Document"}]}))
    r.register(StubTool("llm_extraction", idempotent=True,
                        output={"extracted": ["Point A", "Point B"]}))
    r.register(StubTool("llm_generation", idempotent=True,
                        output={"report": "Final report: ..."}))
    return r
