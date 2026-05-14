"""Support Triage — Tool Implementations"""
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry():
    r = ToolRegistry()
    r.register(StubTool("read_ticket", idempotent=True, output={
        "ticket_id": "TKT-2847",
        "subject": "Charged twice for subscription",
        "body": "I was charged $47.50 twice this month. Please fix this.",
        "customer_tier": "premium", "account_age_days": 847,
    }))
    r.register(StubTool("llm_classification", idempotent=True, output={
        "urgency": "high", "category": "billing",
        "sentiment": "frustrated", "refund_likely": True,
    }))
    r.register(StubTool("llm_generation", idempotent=True, output={
        "draft": "Thank you for contacting support. We have reviewed your account...",
        "tone": "empathetic", "word_count": 45,
    }))
    return r
