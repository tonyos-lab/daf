"""
Support Triage — Sample Mock Responses

SCENARIO:
  1. Read ticket from queue
  2. Classify: urgency (low/medium/high) + category (billing/technical/general)
  3. Draft a response (GATED — requires human review before sending)

The compliance rule gates all llm_generation steps.
Human must approve the draft before it can be sent.

MOCK RESPONSES:
  TRIAGE_PLAN          — read → classify → draft → completed (with HITL gate)
  CLASSIFY_ONLY_PLAN   — read → classify only (no draft) → no gate
  FORBIDDEN_TOOL_PLAN  — tries to use send_email (never permitted) → rejected
"""

TRIAGE_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read the ticket, classify urgency and category, "
        "then draft a response for human review."
    ),
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_ticket",
            "task_type": "deterministic", "agent_required": "support_analyst",
            "tools_required": ["read_ticket"], "data_required": ["tickets"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Read ticket from queue",
        },
        {
            "task_id": "ST-02", "name": "classify_ticket",
            "task_type": "llm_classification", "agent_required": "support_analyst",
            "tools_required": ["llm_classification"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.02,
            "reversible": True, "rationale": "Classify urgency and category",
        },
        {
            "task_id": "ST-03", "name": "draft_response",
            "task_type": "llm_generation",  # GATED by compliance rule
            "agent_required": "support_analyst",
            "tools_required": ["llm_generation"], "data_required": [],
            "depends_on": ["ST-02"], "estimated_cost": 0.04,
            "reversible": True,
            "rationale": "Draft response for human review and approval",
        },
    ],
    "total_estimated_cost": 0.07,
    "confidence": 0.90,
    "requires_human_gate": True,
}

CLASSIFY_ONLY_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read and classify only — no draft response needed.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_ticket",
            "task_type": "deterministic", "agent_required": "support_analyst",
            "tools_required": ["read_ticket"], "data_required": ["tickets"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Read ticket",
        },
        {
            "task_id": "ST-02", "name": "classify",
            "task_type": "llm_classification", "agent_required": "support_analyst",
            "tools_required": ["llm_classification"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.02,
            "reversible": True, "rationale": "Classify urgency and category",
        },
    ],
    "total_estimated_cost": 0.03,
    "confidence": 0.88,
    "requires_human_gate": False,
}

FORBIDDEN_TOOL_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read ticket and send immediate auto-reply.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "send_auto_reply",
            "task_type": "deterministic", "agent_required": "support_analyst",
            "tools_required": ["send_email"],   # NOT permitted → rejected
            "data_required": ["tickets"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": False, "rationale": "Send immediate automated reply",
        },
    ],
    "total_estimated_cost": 0.01,
    "confidence": 0.92,
    "requires_human_gate": False,
}
