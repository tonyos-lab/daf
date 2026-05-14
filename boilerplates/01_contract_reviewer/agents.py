"""
Contract Reviewer — Agent Implementations

Replace StubAgent with a real BaseAgent subclass
when you have real infrastructure.
"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class ContractAnalystAgent(StubAgent):
    """
    Reads contracts and extracts commercial terms.

    Real implementation would:
    - Call read_file tool to load the contract
    - Use llm_extraction to pull payment terms, liability, notice periods
    - Use llm_classification to assess risk level
    """
    role = "contract_analyst"

    def __init__(self):
        super().__init__(
            role="contract_analyst",
            output={
                "payment_terms":    "Net 30 days",
                "liability_cap":    "$500,000",
                "notice_period":    "60 days",
                "governing_law":    "Delaware, USA",
                "risk_level":       "medium",
                "flags": [
                    "Auto-renewal clause — review before anniversary",
                    "Indemnification scope broader than standard",
                ],
            },
            cost_usd=0.03,
        )


def build_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(ContractAnalystAgent)
    return registry
