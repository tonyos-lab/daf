"""
Multi-Tenant Document Processor — Sample Mock Responses

SAME TASK, THREE DIFFERENT GOVERNANCE OUTCOMES:

  standard-tenant: No restrictions → auto-approved → completed in 1 iteration
  gdpr-tenant:     PII access blocked → compliance rule fires → re-plans without PII
  sox-tenant:      Financial records → compliance gate → human approval required

The same mock response dict is used for all tenants.
The PolicyMatrix for each tenant produces a different governance outcome.

TENANT_AWARE_PLAN contains data_required: ["documents", "financial_records", "pii_data"]
  → standard-tenant: no compliance rules → auto-approved
  → gdpr-tenant:     pii_data triggers GDPR-PII-001 → BLOCKED → re-plans
  → sox-tenant:      financial_records triggers SOX-FINANCIAL-001 → GATED

COMPLIANT_PLAN contains only data_required: ["documents"]
  → all tenants: auto-approved → no gates
"""

# Plan that triggers different outcomes per tenant
TENANT_AWARE_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Process document with full data access.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "process_document",
            "task_type": "llm_extraction", "agent_required": "document_processor",
            "tools_required": ["read_document", "llm_extraction"],
            "data_required": ["documents", "financial_records", "pii_data"],
            "depends_on": [], "estimated_cost": 0.05,
            "reversible": True, "rationale": "Full document processing with all data",
        },
    ],
    "total_estimated_cost": 0.05,
    "confidence": 0.90,
    "requires_human_gate": False,
}

# Safe plan — works for all tenants without gates or blocks
COMPLIANT_PLAN = {
    "orchestrator": "default_orchestrator",
    "planning_rationale": "Process document with minimal data access — GDPR/SOX safe.",
    "sub_tasks": [
        {
            "task_id": "ST-01", "name": "process_document_safe",
            "task_type": "llm_extraction", "agent_required": "document_processor",
            "tools_required": ["read_document", "llm_extraction"],
            "data_required": ["documents"],   # no PII, no financial_records
            "depends_on": [], "estimated_cost": 0.04,
            "reversible": True, "rationale": "Document processing without sensitive data",
        },
    ],
    "total_estimated_cost": 0.04,
    "confidence": 0.91,
    "requires_human_gate": False,
}
