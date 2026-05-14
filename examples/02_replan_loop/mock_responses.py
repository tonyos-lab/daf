"""
Example 02: Re-planning Loop — Sample Mock Responses

This example demonstrates the self-correction mechanism.
The LLM proposes a plan that violates policy on the first attempt.
The PolicyEngine rejects it with violation context.
The LLM uses that context to produce a compliant revised plan.

HOW THE RE-PLANNING LOOP WORKS:
  Iteration 1:
    LLM returns FORBIDDEN_PLAN (uses write_db — not permitted)
    PolicyEngine: REJECTED — tool_permission violation on write_db
    GovernedAgenticLoop: appends violation to violation_history

  Iteration 2:
    LLM is called again with violation_history in the prompt
    LLM returns REVISED_PLAN (uses only read_db — permitted)
    PolicyEngine: APPROVED
    ExecutionOrchestrator runs the plan
    FinalResponse(outcome="completed", loop_iterations=2)

TESTING THE RE-PLAN SCENARIO:
  MockLLMClient returns responses in sequence.
  Pass two responses to simulate one rejection and one approval:

    from daf.testing import MockLLMClient
    from examples.02_replan_loop.mock_responses import (
        FORBIDDEN_PLAN, REVISED_PLAN
    )

    client = MockLLMClient(responses=[FORBIDDEN_PLAN, REVISED_PLAN])
    # First call  → FORBIDDEN_PLAN  → PolicyEngine rejects
    # Second call → REVISED_PLAN    → PolicyEngine approves
"""
from __future__ import annotations

# ── PLAN 1: First attempt — uses forbidden tool ───────────────
#
# This plan will be REJECTED because write_db is NOT in
# analyst.permitted_tools (see policy/matrix.yaml).
#
# PolicyEngine violation:
#   dimension: tool_permission
#   detail: "Role 'analyst' is not permitted to invoke 'write_db'"
#   suggestion: "No role in the current PolicyMatrix has permission for 'write_db'"
#
FORBIDDEN_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read documents from the database, extract key findings, "
        "then write the results back to the database for persistence."
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_documents",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],       # permitted ✓
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read source documents from the database",
        },
        {
            "task_id":        "ST-02",
            "name":           "write_results",
            "task_type":      "deterministic",
            "agent_required": "analyst",
            "tools_required": ["write_db"],      # NOT permitted ✗ → REJECTED
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.01,
            "reversible":     False,
            "rationale":      "Persist extracted results to the database",
        },
    ],
    "total_estimated_cost": 0.03,
    "confidence": 0.88,
    "requires_human_gate": False,
}


# ── PLAN 2: Revised plan — uses only permitted tools ──────────
#
# After receiving the violation context, the LLM revises the plan
# to avoid write_db. It uses only read_db and llm_extraction.
#
# This plan will be APPROVED.
#
REVISED_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Revised plan: removed write_db step as it is not permitted. "
        "Using only read_db and llm_extraction as permitted by policy. "
        "Results will be returned in the FinalResponse instead of persisted."
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_documents",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["read_db"],          # permitted ✓
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read source documents from the database",
        },
        {
            "task_id":        "ST-02",
            "name":           "extract_and_return",
            "task_type":      "llm_extraction",
            "agent_required": "analyst",
            "tools_required": ["llm_extraction"],   # permitted ✓
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Extract findings and return in response (no DB write)",
        },
    ],
    "total_estimated_cost": 0.04,
    "confidence": 0.91,
    "requires_human_gate": False,
}


# ── PLAN 3: Always-forbidden (for escalation testing) ────────
#
# Use this to test what happens when no compliant plan is possible.
# MockLLMClient will return this for every call.
# After max_replan_attempts (3), the loop escalates.
#
ALWAYS_FORBIDDEN_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Must use write_db — no alternative.",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "write_data",
            "task_type":      "deterministic",
            "agent_required": "analyst",
            "tools_required": ["write_db"],    # always forbidden
            "data_required":  [],
            "depends_on":     [],
            "estimated_cost": 0.01,
            "reversible":     False,
            "rationale":      "Must write data",
        },
    ],
    "total_estimated_cost": 0.01,
    "confidence": 0.95,
    "requires_human_gate": False,
}
