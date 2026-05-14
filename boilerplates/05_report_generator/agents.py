"""Report Generator — Agent Implementations"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class DataAnalystAgent(StubAgent):
    """Reads and analyses data sources."""
    role = "data_analyst"
    def __init__(self):
        super().__init__(role="data_analyst", output={
            "revenue_total": 1_247_890,
            "revenue_growth": 0.134,
            "top_product": "Enterprise Plan",
            "churn_rate": 0.023,
            "nps_score": 52,
        }, cost_usd=0.04)


class ReporterAgent(StubAgent):
    """Generates formatted reports for distribution."""
    role = "reporter"
    def __init__(self):
        super().__init__(role="reporter", output={
            "report_title": "Q1 2026 Business Performance Report",
            "report_html": "<h1>Q1 2026</h1><p>Revenue grew 13.4%...</p>",
            "recipients": ["ceo@company.com", "cfo@company.com", "board@company.com"],
            "word_count": 847,
        }, cost_usd=0.05)


def build_agent_registry():
    r = AgentRegistry()
    r.register(DataAnalystAgent)
    r.register(ReporterAgent)
    return r
