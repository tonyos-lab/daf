"""DB Migration Validator — Agent Implementations"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class DbAnalystAgent(StubAgent):
    """Reads and analyses SQL migration scripts."""
    role = "db_analyst"
    def __init__(self):
        super().__init__(role="db_analyst", output={
            "operations_found": ["ALTER TABLE", "ADD COLUMN", "CREATE INDEX"],
            "destructive_ops":  [],
            "affected_tables":  ["users", "orders"],
            "estimated_rows":   1_240_000,
            "risk_level":       "low",
            "recommendation":   "Safe to apply — no destructive operations",
        }, cost_usd=0.04)


def build_agent_registry():
    r = AgentRegistry()
    r.register(DbAnalystAgent)
    return r
