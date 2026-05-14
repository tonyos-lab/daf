"""
DB Migration Validator — Sample Mock Responses

COMPLIANCE RULES IN PLAY:
  DB-DROP-001:   data_required contains "destructive_ops" → require_human_gate
  DB-PROD-BLOCK: data_required contains "production_schema" → require_human_gate

MOCK RESPONSES:
  SAFE_MIGRATION_PLAN        — only ADD/CREATE ops → no gate → auto-approved
  DESTRUCTIVE_MIGRATION_PLAN — contains DROP/TRUNCATE → compliance gate triggered
  PROD_MIGRATION_PLAN        — touches production schema → compliance gate triggered
  FORBIDDEN_PLAN             — db_analyst tries direct DB write → rejected
"""

SAFE_MIGRATION_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read the migration script, check for safe operations only, "
        "estimate row counts, produce risk report."
    ),
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_migration",
            "task_type": "deterministic", "agent_required": "db_analyst",
            "tools_required": ["read_sql_file"],
            "data_required": ["migrations"],     # no destructive_ops key → auto-approved
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Read migration SQL file",
        },
        {
            "task_id": "ST-02", "name": "analyse_operations",
            "task_type": "llm_extraction", "agent_required": "db_analyst",
            "tools_required": ["llm_extraction"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.04,
            "reversible": True, "rationale": "Identify all SQL operations",
        },
        {
            "task_id": "ST-03", "name": "produce_risk_report",
            "task_type": "llm_evaluation", "agent_required": "db_analyst",
            "tools_required": ["llm_evaluation"], "data_required": [],
            "depends_on": ["ST-02"], "estimated_cost": 0.04,
            "reversible": True, "rationale": "Produce risk assessment report",
        },
    ],
    "total_estimated_cost": 0.09,
    "confidence": 0.93,
    "requires_human_gate": False,
}

DESTRUCTIVE_MIGRATION_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": (
        "Read the migration containing DROP TABLE and TRUNCATE operations. "
        "These require DBA sign-off before approval."
    ),
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_migration",
            "task_type": "deterministic", "agent_required": "db_analyst",
            "tools_required": ["read_sql_file"],
            "data_required": ["migrations", "destructive_ops"],  # triggers DB-DROP-001
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Read migration with destructive operations",
        },
        {
            "task_id": "ST-02", "name": "analyse_and_report",
            "task_type": "llm_evaluation", "agent_required": "db_analyst",
            "tools_required": ["llm_evaluation"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.06,
            "reversible": True, "rationale": "Assess impact of DROP/TRUNCATE",
        },
    ],
    "total_estimated_cost": 0.07,
    "confidence": 0.91,
    "requires_human_gate": True,
}

PROD_MIGRATION_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Validate production schema migration — requires sign-off.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "read_prod_migration",
            "task_type": "deterministic", "agent_required": "db_analyst",
            "tools_required": ["read_sql_file"],
            "data_required": ["migrations", "production_schema"],  # triggers DB-PROD-BLOCK
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": True, "rationale": "Read production schema migration",
        },
        {
            "task_id": "ST-02", "name": "validate",
            "task_type": "llm_evaluation", "agent_required": "db_analyst",
            "tools_required": ["llm_evaluation"], "data_required": [],
            "depends_on": ["ST-01"], "estimated_cost": 0.06,
            "reversible": True, "rationale": "Validate production migration safety",
        },
    ],
    "total_estimated_cost": 0.07,
    "confidence": 0.94,
    "requires_human_gate": True,
}

FORBIDDEN_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Analyst runs the migration directly.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "run_migration",
            "task_type": "deterministic", "agent_required": "db_analyst",
            "tools_required": ["execute_sql"],  # NOT permitted → rejected
            "data_required": ["migrations"],
            "depends_on": [], "estimated_cost": 0.01,
            "reversible": False, "rationale": "Execute migration directly",
        },
    ],
    "total_estimated_cost": 0.01,
    "confidence": 0.95,
    "requires_human_gate": False,
}
