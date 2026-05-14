"""Research Summariser — Agent Implementations"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class FetcherAgent(StubAgent):
    """Retrieves web pages. Replace with real HTTP client."""
    role = "fetcher"
    def __init__(self):
        super().__init__(role="fetcher", output={
            "pages": [
                {"url": "https://example.com/article-1", "word_count": 1200, "status": 200},
                {"url": "https://example.com/article-2", "word_count": 980,  "status": 200},
                {"url": "https://example.com/article-3", "word_count": 1450, "status": 200},
            ]
        }, cost_usd=0.01)


class AnalystAgent(StubAgent):
    """Extracts and summarises research findings."""
    role = "analyst"
    def __init__(self):
        super().__init__(role="analyst", output={
            "claims": [
                {"claim": "Market grew 23% YoY", "sources": 2, "confidence": 0.9},
                {"claim": "Top player holds 34% share", "sources": 3, "confidence": 0.85},
            ],
            "summary": "Market shows strong growth with consolidation among top players.",
            "source_count": 3,
        }, cost_usd=0.05)


def build_agent_registry():
    r = AgentRegistry()
    r.register(FetcherAgent)
    r.register(AnalystAgent)
    return r
