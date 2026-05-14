"""
Example 03: Governed Action — Sample Mock Responses

This example demonstrates the HITL (Human-in-the-Loop) gate.
When the PolicyEngine detects a gated task, it marks it in the
ApprovalGrant. EvaluateStage then requests human review before
any execution begins.

HOW THE HITL GATE WORKS:
  1. LLM proposes a plan with an llm_generation step
  2. PolicyEngine: APPROVED — but marks ST-02 as gated
     (because llm_generation is in always_gate_action_classes)
  3. EvaluateStage: sends HumanReviewRequest to the gateway
  4. Human reviews the gated task and responds
  5. If APPROVED → ExecutionOrchestrator runs all tasks
     If REJECTED → ViolationReport → loop re-plans or escalates

HITL REVIEW REQUEST CONTAINS:
  - The task details (task_id, action_class, impact, reversible)
  - The original workflow task description
  - An expiry time (auto-rejects if not responded to in time)

MOCK GATEWAY OPTIONS:
  from daf.runtime.human_review_gateway import StubHumanReviewGateway

  # Always approve
  StubHumanReviewGateway(approve_all=True)

  # Always reject
  StubHumanReviewGateway(approve_all=False)

  # Simulate timeout
  StubHumanReviewGateway(simulate_timeout=True)

  # Custom response for next call
  gateway = StubHumanReviewGateway()
  gateway.set_next_response(my_custom_response)
"""
from __future__ import annotations

# ── PLAN 1: Contains a gated task ────────────────────────────
#
# ST-01 (llm_extraction) → auto-approved
# ST-02 (llm_generation) → GATED (always_gate_action_classes)
#
# What happens:
#   PolicyEngine: APPROVED, gated_tasks=["ST-02"]
#   EvaluateStage: sends HumanReviewRequest for ST-02
#   → If human approves: both tasks execute → completed
#   → If human rejects:  ViolationReport → re-plan or escalate
#
GATED_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read documents and extract key data (auto-approved), "
        "then generate a report for distribution (requires approval)."
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "extract_data",
            "task_type":      "llm_extraction",   # auto-approved ✓
            "agent_required": "analyst",
            "tools_required": ["read_db"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Extract key data from source documents",
        },
        {
            "task_id":        "ST-02",
            "name":           "generate_report",
            "task_type":      "llm_generation",   # GATED — requires human approval
            "agent_required": "analyst",
            "tools_required": ["llm_generation"],
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.03,
            "reversible":     False,
            "rationale":      "Generate final report for distribution to stakeholders",
        },
    ],
    "total_estimated_cost": 0.05,
    "confidence": 0.90,
    "requires_human_gate": True,
}


# ── PLAN 2: No gated tasks ────────────────────────────────────
#
# Used as the revised plan when the human rejects ST-02.
# LLM produces a plan that avoids llm_generation entirely.
# Uses only llm_extraction (auto-approved) → no HITL needed.
#
UNGATED_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Revised: removed report generation step as it was rejected. "
        "Returning extracted data directly in the response instead."
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "extract_and_return",
            "task_type":      "llm_extraction",   # auto-approved ✓
            "agent_required": "analyst",
            "tools_required": ["llm_extraction"],
            "data_required":  ["documents"],
            "depends_on":     [],
            "estimated_cost": 0.03,
            "reversible":     True,
            "rationale":      "Extract data and return in response (no generation)",
        },
    ],
    "total_estimated_cost": 0.03,
    "confidence": 0.88,
    "requires_human_gate": False,
}
