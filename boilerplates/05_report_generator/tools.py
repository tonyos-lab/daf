"""Report Generator — Tool Implementations"""
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry():
    r = ToolRegistry()
    r.register(StubTool("read_csv", idempotent=True, output={
        "rows": 1240, "columns": ["date", "revenue", "users", "churn"],
        "date_range": "2026-01-01 to 2026-03-31",
    }))
    r.register(StubTool("llm_extraction", idempotent=True, output={
        "kpis": {"revenue": 1247890, "growth": 0.134, "nps": 52},
    }))
    r.register(StubTool("llm_summarization", idempotent=True, output={
        "summary": "Strong Q1: revenue up 13.4%, NPS 52, churn stable at 2.3%.",
    }))
    r.register(StubTool("llm_generation", idempotent=True, output={
        "report": "Q1 2026 Report — Revenue $1.25M (+13.4% YoY)...",
        "format": "html",
    }))
    r.register(StubTool("send_email", idempotent=False, output={
        "sent": True, "recipients": 3, "message_id": "msg-20260415-001",
    }))
    return r
