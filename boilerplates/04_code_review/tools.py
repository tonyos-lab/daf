"""Code Review Assistant — Tool Implementations"""
from daf.runtime.tool_registry import ToolRegistry
from daf.tools.stub_tool import StubTool


def build_tool_registry():
    r = ToolRegistry()
    r.register(StubTool("read_diff", idempotent=True, output={
        "files_changed": 3, "insertions": 47, "deletions": 12,
        "diff": "diff --git a/api/users.py...",
    }))
    r.register(StubTool("llm_extraction", idempotent=True, output={
        "patterns": ["raw_sql_query", "no_input_validation"],
    }))
    r.register(StubTool("llm_evaluation", idempotent=True, output={
        "score": 4.2, "issues": ["missing_tests", "high_complexity"],
    }))
    r.register(StubTool("llm_summarization", idempotent=True, output={
        "summary": "Critical security issue found. Quality review incomplete.",
    }))
    return r
