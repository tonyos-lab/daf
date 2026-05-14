"""
Example 01: Basic Analysis — Sample Mock Responses

This file contains sample mock responses you can use as reference
when building and testing without a real API key.

HOW MOCK RESPONSES WORK IN DAF:
  The LLM's job in DAF is to produce a PlanProposal — a structured
  JSON object that describes how to break down the task into sub-tasks.

  MockLLMClient intercepts the LLM call and returns your dict instead.
  The rest of the loop (PolicyEngine, ExecutionOrchestrator, AuditStore)
  runs exactly as it would with a real LLM response.

HOW TO BUILD YOUR OWN:
  Use FixturePlanBuilder for a guided, validated approach:

    from daf.testing import FixturePlanBuilder
    plan = FixturePlanBuilder()\\
        .with_task("ST-01", agent="analyst", tools=["read_db"])\\
        .build()

  Or write the dict directly if you want full control (see below).

REQUIRED FIELDS:
  orchestrator          str   — name of the orchestrator routing config
  planning_rationale    str   — why the plan was structured this way
  sub_tasks             list  — the steps to execute (see sub-task fields)
  total_estimated_cost  float — sum of all sub-task estimated_cost values
  confidence            float — 0.0 to 1.0, planner's confidence
  requires_human_gate   bool  — True if human approval needed

REQUIRED SUB-TASK FIELDS:
  task_id          str   — unique ID e.g. "ST-01", "ST-02"
  name             str   — human-readable step name
  task_type        str   — one of: deterministic, llm_classification,
                           llm_extraction, llm_summarization,
                           llm_transformation, llm_generation,
                           llm_evaluation
  agent_required   str   — must match a role in policy/matrix.yaml
  tools_required   list  — must be in that role's permitted_tools
  data_required    list  — data sources this step needs
  depends_on       list  — task_ids that must complete first
  estimated_cost   float — estimated USD cost for this step
  reversible       bool  — True if this action can be undone
  rationale        str   — why this step is needed
"""
from __future__ import annotations

# ── PLAN 1: Three-step analysis (happy path) ─────────────────
#
# This plan will PASS the PolicyEngine because:
#   - All tools are in analyst.permitted_tools
#   - All task_types are in analyst.permitted_task_types
#   - total_estimated_cost (0.07) < max_cost_per_workflow_usd (0.50)
#   - All tasks are reversible — no HITL needed
#   - No compliance rules are triggered
#
HAPPY_PATH_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Break the analysis into three sequential steps: "
        "read source documents, extract key features, "
        "then summarise findings for the final report."
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_documents",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Fetch source documents from the database",
        },
        {
            "task_id":        "ST-02",
            "name":           "extract_features",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["llm_extraction"],
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.03,
            "reversible":     True,
            "rationale":      "Extract key features from the documents",
        },
        {
            "task_id":        "ST-03",
            "name":           "summarise_findings",
            "task_type":      "llm_summarization",
            "agent_required": "analyst",
            "tools_required": ["llm_summarization"],
            "data_required":  [],
            "depends_on":     ["ST-02"],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Produce a structured summary of extracted features",
        },
    ],
    "total_estimated_cost": 0.07,
    "confidence": 0.92,
    "requires_human_gate": False,
}


# ── PLAN 2: Single-step analysis (minimal) ───────────────────
#
# Use this to test the simplest possible execution path.
# One task, one agent, one tool.
#
MINIMAL_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Single-step extraction from the document database.",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "extract_all",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.04,
            "reversible":     True,
            "rationale":      "Extract all relevant information in one pass",
        },
    ],
    "total_estimated_cost": 0.04,
    "confidence": 0.88,
    "requires_human_gate": False,
}


# ── PLAN 3: Over-budget plan (will be REJECTED) ───────────────
#
# Use this to test PolicyEngine rejection.
# total_estimated_cost (0.99) > max_cost_per_workflow_usd (0.50)
# The loop will reject this and re-plan.
#
OVER_BUDGET_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Comprehensive multi-pass analysis of all documents.",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "deep_analysis",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.99,   # over the $0.50 workflow budget
            "reversible":     True,
            "rationale":      "Deep multi-pass document analysis",
        },
    ],
    "total_estimated_cost": 0.99,
    "confidence": 0.95,
    "requires_human_gate": False,
}


# ── PLAN 4: Forbidden tool plan (will be REJECTED) ───────────
#
# Use this to test tool permission enforcement.
# write_db is NOT in analyst.permitted_tools.
# PolicyEngine will reject with a tool_permission violation.
#
FORBIDDEN_TOOL_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read documents and write results to database.",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_docs",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read source documents",
        },
        {
            "task_id":        "ST-02",
            "name":           "write_results",
            "task_type":      "deterministic",
            "agent_required": "analyst",
            "tools_required": ["write_db"],   # NOT permitted
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.01,
            "reversible":     False,
            "rationale":      "Write extracted results to the database",
        },
    ],
    "total_estimated_cost": 0.03,
    "confidence": 0.90,
    "requires_human_gate": False,
}
