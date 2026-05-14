"""DB Migration Validator — Tool Implementations"""
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry():
    r = ToolRegistry()
    r.register(StubTool("read_sql_file", idempotent=True, output={
        "filename": "V42__add_user_preferences.sql",
        "sql": "ALTER TABLE users ADD COLUMN preferences JSONB;",
        "line_count": 24,
        "operations": ["ALTER TABLE", "ADD COLUMN"],
    }))
    r.register(StubTool("llm_extraction", idempotent=True, output={
        "operations":   ["ALTER TABLE", "ADD COLUMN"],
        "tables":       ["users"],
        "has_drop":     False,
        "has_truncate": False,
    }))
    r.register(StubTool("llm_evaluation", idempotent=True, output={
        "risk_level":      "low",
        "risk_score":      0.12,
        "affected_rows":   1_240_000,
        "estimated_time":  "< 30 seconds",
        "rollback_safe":   True,
        "recommendation":  "Safe to deploy during low-traffic window",
    }))
    return r
