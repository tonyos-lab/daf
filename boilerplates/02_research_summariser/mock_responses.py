"""
Research Summariser — Sample Mock Responses

Two agent roles: fetcher (retrieves pages) and analyst (extracts + summarises).
Tasks have dependencies: fetch → extract → synthesise.

MOCK RESPONSES:
  MULTI_SOURCE_PLAN   — fetch 3 URLs, extract, cross-reference, summarise → completed
  SINGLE_SOURCE_PLAN  — fetch 1 URL, extract, summarise → completed (minimal)
  FORBIDDEN_PLAN      — fetcher tries to use llm_extraction (not permitted) → rejected
"""

MULTI_SOURCE_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Fetch three sources, extract key claims from each, "
        "cross-reference for consistency, then produce a research brief."
    ),
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "fetch_sources",
            "task_type": "deterministic", "agent_required": "fetcher",
            "tools_required": ["http_fetch"], "data_required": ["web"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Fetch HTML from 3 source URLs",
        },
        {
            "task_id": "ST-02", "name": "extract_claims",
            "task_type": "llm_extraction", "agent_required": "analyst",
            "tools_required": ["llm_extraction"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.08,
            "reversible": True, "rationale": "Extract key claims and supporting evidence",
        },
        {
            "task_id": "ST-03", "name": "cross_reference",
            "task_type": "llm_extraction", "agent_required": "analyst",
            "tools_required": ["llm_extraction"], "data_required": [],
            "depends_on": ["ST-02"], "estimated_cost": 0.06,
            "reversible": True, "rationale": "Cross-reference claims across sources",
        },
        {
            "task_id": "ST-04", "name": "produce_brief",
            "task_type": "llm_summarization", "agent_required": "analyst",
            "tools_required": ["llm_summarization"], "data_required": [],
            "depends_on": ["ST-03"], "estimated_cost": 0.05,
            "reversible": True, "rationale": "Produce structured research brief with sources",
        },
    ],
    "total_estimated_cost": 0.20,
    "confidence": 0.91,
    "requires_human_gate": False,
}

SINGLE_SOURCE_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Fetch one URL, extract key points, summarise.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "fetch",
            "task_type": "deterministic", "agent_required": "fetcher",
            "tools_required": ["http_fetch"], "data_required": ["web"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Fetch source page",
        },
        {
            "task_id": "ST-02", "name": "summarise",
            "task_type": "llm_summarization", "agent_required": "analyst",
            "tools_required": ["llm_summarization"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.04,
            "reversible": True, "rationale": "Summarise key findings",
        },
    ],
    "total_estimated_cost": 0.05,
    "confidence": 0.87,
    "requires_human_gate": False,
}

FORBIDDEN_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Fetch and analyse in one step.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "fetch_and_analyse",
            "task_type": "llm_extraction", "agent_required": "fetcher",
            "tools_required": ["llm_extraction"],  # fetcher not permitted this
            "data_required": ["web"],
            "depends_on": [], "estimated_cost": 0.05,
            "reversible": True, "rationale": "Combined fetch and analyse",
        },
    ],
    "total_estimated_cost": 0.05,
    "confidence": 0.85,
    "requires_human_gate": False,
}
