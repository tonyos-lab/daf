"""
Contract Reviewer — Tool Implementations

Replace StubTool with real BaseTool subclasses
when you have real infrastructure.
"""
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    # Replace with: real file storage client (S3, GCS, local)
    registry.register(StubTool(
        name="read_file",
        idempotent=True,
        output={
            "filename":    "vendor_agreement_2026.pdf",
            "content":     "VENDOR AGREEMENT... Payment due Net 30...",
            "page_count":  12,
            "size_bytes":  48230,
        },
    ))

    # Replace with: real LLM extraction call
    registry.register(StubTool(
        name="llm_extraction",
        idempotent=True,
        output={
            "payment_terms":  "Net 30 days from invoice date",
            "liability_cap":  "Limited to $500,000 per incident",
            "notice_period":  "60 days written notice required",
            "governing_law":  "Laws of the State of Delaware",
            "auto_renewal":   True,
            "renewal_notice": "90 days before anniversary",
        },
    ))

    # Replace with: real LLM classification call
    registry.register(StubTool(
        name="llm_classification",
        idempotent=True,
        output={
            "risk_level":   "medium",
            "risk_score":   0.52,
            "risk_factors": [
                "Auto-renewal with 90-day notice window",
                "Indemnification clause broader than standard",
            ],
            "recommendation": "Legal review recommended before signing",
        },
    ))

    return registry
