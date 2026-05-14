"""
Contract Reviewer — Sample Mock Responses

WHAT THE LLM PLANS:
  ST-01: Read the contract file (read_file)
  ST-02: Extract payment terms, liability, notice period (llm_extraction)
  ST-03: Classify overall risk level (llm_classification)

ALL PLANS BELOW ARE APPROVED BY DEFAULT.
The contract_analyst role has all required tools.
No compliance rules, no HITL gates.

USING THESE IN YOUR TESTS:
  from daf.testing import MockLLMClient
  from mock_responses import STANDARD_CONTRACT_PLAN

  client = MockLLMClient(responses=[STANDARD_CONTRACT_PLAN])
"""

# Three-step extraction plan (standard path)
STANDARD_CONTRACT_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read the contract, extract key commercial terms, "
        "then classify the overall risk level."
    ),
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "read_contract",
            "task_type":      "llm_extraction",
            "agent_required": "contract_analyst",
            "tools_required": ["read_file"],
            "data_required":  ["contracts"],
            "depends_on":     [],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Read contract file from storage",
        },
        {
            "task_id":        "ST-02",
            "name":           "extract_terms",
            "task_type":      "llm_extraction",
            "agent_required": "contract_analyst",
            "tools_required": ["llm_extraction"],
            "data_required":  [],
            "depends_on":     ["ST-01"],
            "estimated_cost": 0.05,
            "reversible":     True,
            "rationale":      "Extract payment terms, liability clauses, notice period",
        },
        {
            "task_id":        "ST-03",
            "name":           "classify_risk",
            "task_type":      "llm_classification",
            "agent_required": "contract_analyst",
            "tools_required": ["llm_classification"],
            "data_required":  [],
            "depends_on":     ["ST-02"],
            "estimated_cost": 0.02,
            "reversible":     True,
            "rationale":      "Classify contract risk level: low/medium/high",
        },
    ],
    "total_estimated_cost": 0.09,
    "confidence": 0.93,
    "requires_human_gate": False,
}

# Minimal plan — single extraction step
MINIMAL_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Single-pass extraction of all contract terms.",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "extract_all_terms",
            "task_type":      "llm_extraction",
            "agent_required": "contract_analyst",
            "tools_required": ["read_file"],
            "data_required":  ["contracts"],
            "depends_on":     [],
            "estimated_cost": 0.07,
            "reversible":     True,
            "rationale":      "Extract all key terms in one pass",
        },
    ],
    "total_estimated_cost": 0.07,
    "confidence": 0.88,
    "requires_human_gate": False,
}

# Forbidden tool plan — triggers re-plan
# Tries to use write_db (not permitted) → rejected → re-plans
FORBIDDEN_TOOL_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Extract terms and store results in database.",
    "sub_tasks": [
        {
            "task_id":        "ST-01",
            "name":           "extract_and_store",
            "task_type":      "llm_extraction",
            "agent_required": "contract_analyst",
            "tools_required": ["write_db"],   # NOT permitted → rejected
            "data_required":  ["contracts"],
            "depends_on":     [],
            "estimated_cost": 0.03,
            "reversible":     False,
            "rationale":      "Extract and immediately persist results",
        },
    ],
    "total_estimated_cost": 0.03,
    "confidence": 0.90,
    "requires_human_gate": False,
}
