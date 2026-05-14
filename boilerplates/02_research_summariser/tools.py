"""Research Summariser — Tool Implementations"""
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry():
    r = ToolRegistry()
    r.register(StubTool("http_fetch", idempotent=True, output={
        "html": "<html>Article content about market trends...</html>",
        "status_code": 200, "word_count": 1200,
    }))
    r.register(StubTool("llm_extraction", idempotent=True, output={
        "key_claims": ["Claim A with evidence", "Claim B with citation"],
        "entities": ["Company X", "Market Y"],
    }))
    r.register(StubTool("llm_summarization", idempotent=True, output={
        "brief": "Research brief: market growing strongly, key players consolidating.",
        "word_count": 180, "sources_cited": 3,
    }))
    return r
