"""
Code Review Assistant — Sample Mock Responses

THREE ROLES:
  security_reviewer  — scans for vulnerabilities, injection, auth issues
  quality_reviewer   — checks readability, patterns, test coverage
  summariser         — combines findings, generates review comment (GATED)

MOCK RESPONSES:
  FULL_REVIEW_PLAN     — security + quality + summary (generation GATED) → completed
  SECURITY_ONLY_PLAN   — security scan only, no generation → no gate
  REPLAN_TRIGGER_PLAN  — wrong tool for role → rejected → re-plans
"""

FULL_REVIEW_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Run security and quality reviews in parallel steps, "
        "then generate a unified review comment for approval."
    ),
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "security_scan",
            "task_type": "llm_evaluation", "agent_required": "security_reviewer",
            "tools_required": ["read_diff", "llm_extraction"],
            "data_required": ["pull_requests"],
            "depends_on": [], "estimated_cost": 0.08,
            "reversible": True, "rationale": "Scan diff for security vulnerabilities",
        },
        {
            "task_id": "ST-02", "name": "quality_review",
            "task_type": "llm_evaluation", "agent_required": "quality_reviewer",
            "tools_required": ["read_diff", "llm_evaluation"],
            "data_required": ["pull_requests"],
            "depends_on": [], "estimated_cost": 0.07,
            "reversible": True, "rationale": "Review code quality and test coverage",
        },
        {
            "task_id": "ST-03", "name": "generate_comment",
            "task_type": "llm_generation",   # GATED
            "agent_required": "summariser",
            "tools_required": ["llm_summarization"],
            "data_required": [],
            "depends_on": ["ST-01", "ST-02"], "estimated_cost": 0.05,
            "reversible": True,
            "rationale": "Generate unified PR review comment for human approval",
        },
    ],
    "total_estimated_cost": 0.20,
    "confidence": 0.92,
    "requires_human_gate": True,
}

SECURITY_ONLY_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Quick security scan only — no quality review or comment.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "security_scan",
            "task_type": "llm_evaluation", "agent_required": "security_reviewer",
            "tools_required": ["read_diff", "llm_extraction"],
            "data_required": ["pull_requests"],
            "depends_on": [], "estimated_cost": 0.08,
            "reversible": True, "rationale": "Security-only scan",
        },
    ],
    "total_estimated_cost": 0.08,
    "confidence": 0.90,
    "requires_human_gate": False,
}

REPLAN_TRIGGER_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Security reviewer generates comment directly.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "scan_and_comment",
            "task_type": "llm_generation", "agent_required": "security_reviewer",
            "tools_required": ["llm_summarization"],  # not in security_reviewer tools
            "data_required": ["pull_requests"],
            "depends_on": [], "estimated_cost": 0.06,
            "reversible": True, "rationale": "Combined scan and comment",
        },
    ],
    "total_estimated_cost": 0.06,
    "confidence": 0.85,
    "requires_human_gate": False,
}
