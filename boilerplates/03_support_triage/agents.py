"""Support Triage — Agent Implementations"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class SupportAnalystAgent(StubAgent):
    """Reads tickets, classifies urgency, drafts responses."""
    role = "support_analyst"
    def __init__(self):
        super().__init__(role="support_analyst", output={
            "ticket_id": "TKT-2847",
            "classification": {"urgency": "high", "category": "billing", "sentiment": "frustrated"},
            "draft_response": (
                "Thank you for contacting us. I understand your concern about the charge. "
                "I have reviewed your account and can confirm a refund of $47.50 "
                "will be processed within 3-5 business days."
            ),
            "recommended_action": "approve_and_send",
        }, cost_usd=0.03)


def build_agent_registry():
    r = AgentRegistry()
    r.register(SupportAnalystAgent)
    return r
