"""Code Review Assistant — Agent Implementations"""
from daf.agents.stub_agent import StubAgent
from daf.runtime.agent_registry import AgentRegistry


class SecurityReviewerAgent(StubAgent):
    role = "security_reviewer"
    def __init__(self):
        super().__init__(role="security_reviewer", output={
            "findings": [
                {"severity": "high", "type": "sql_injection",
                 "file": "api/users.py", "line": 47,
                 "detail": "Unsanitised user input passed to SQL query"},
            ],
            "severity_counts": {"high": 1, "medium": 0, "low": 2},
            "passed": False,
        }, cost_usd=0.05)


class QualityReviewerAgent(StubAgent):
    role = "quality_reviewer"
    def __init__(self):
        super().__init__(role="quality_reviewer", output={
            "issues": [
                {"type": "missing_tests", "file": "api/users.py",
                 "detail": "New endpoint has no test coverage"},
            ],
            "test_coverage_delta": -3.2,
            "complexity_score": 6.8,
            "passed": False,
        }, cost_usd=0.05)


class SummariserAgent(StubAgent):
    role = "summariser"
    def __init__(self):
        super().__init__(role="summariser", output={
            "review_comment": (
                "## Security\n🔴 Critical: SQL injection in api/users.py:47\n\n"
                "## Quality\n⚠️ Missing test coverage (-3.2%)\n\n"
                "**Verdict: Changes requested**"
            ),
            "verdict": "changes_requested",
        }, cost_usd=0.03)


def build_agent_registry():
    r = AgentRegistry()
    r.register(SecurityReviewerAgent)
    r.register(QualityReviewerAgent)
    r.register(SummariserAgent)
    return r
