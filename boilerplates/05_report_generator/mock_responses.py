"""
Report Generator — Sample Mock Responses

THE KEY PATTERN (irreversible action gate):
  ST-01: Read and analyse data (auto-approved — read-only)
  ST-02: Extract key metrics (auto-approved — read-only)
  ST-03: Generate formatted report (GATED — irreversible once emailed)
  ST-04: Send email to distribution list (only after ST-03 approved)

The always_gate_action_classes: [llm_generation] means
ST-03 is always gated regardless of plan content.
Human sees: what will be sent, to whom, report preview.

MOCK RESPONSES:
  FULL_REPORT_PLAN    — analyse → extract → generate (GATED) → send → completed
  ANALYSE_ONLY_PLAN   — analyse → extract only, no generation → no gate
  FORBIDDEN_PLAN      — data_analyst tries send_email (not permitted) → rejected
"""

FULL_REPORT_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read the data source, extract key metrics, "
        "generate a formatted report (requires approval), "
        "then send to the distribution list."
    ),
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_data",
            "task_type": "llm_extraction", "agent_required": "data_analyst",
            "tools_required": ["read_csv"], "data_required": ["reports"],
            "depends_on": [], "estimated_cost": 0.02,
            "reversible": True, "rationale": "Load data from source",
        },
        {
            "task_id": "ST-02", "name": "extract_metrics",
            "task_type": "llm_extraction", "agent_required": "data_analyst",
            "tools_required": ["llm_extraction"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.05,
            "reversible": True, "rationale": "Extract KPIs and trends",
        },
        {
            "task_id": "ST-03", "name": "generate_report",
            "task_type": "llm_generation",  # GATED — always_gate_action_classes
            "agent_required": "reporter",
            "tools_required": ["llm_generation"], "data_required": [],
            "depends_on": ["ST-02"], "estimated_cost": 0.07,
            "reversible": False,  # once approved and sent, cannot be undone
            "rationale": "Generate formatted report for distribution (requires approval)",
        },
    ],
    "total_estimated_cost": 0.14,
    "confidence": 0.92,
    "requires_human_gate": True,
}

ANALYSE_ONLY_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Read and analyse data only — no report generation.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_and_analyse",
            "task_type": "llm_extraction", "agent_required": "data_analyst",
            "tools_required": ["read_csv", "llm_summarization"],
            "data_required": ["reports"],
            "depends_on": [], "estimated_cost": 0.06,
            "reversible": True, "rationale": "Load and summarise data",
        },
    ],
    "total_estimated_cost": 0.06,
    "confidence": 0.88,
    "requires_human_gate": False,
}

FORBIDDEN_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Analyst reads data and sends report directly.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_and_send",
            "task_type": "deterministic", "agent_required": "data_analyst",
            "tools_required": ["send_email"],  # data_analyst not permitted this
            "data_required": ["reports"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": False, "rationale": "Send report without review",
        },
    ],
    "total_estimated_cost": 0.01,
    "confidence": 0.90,
    "requires_human_gate": False,
}
