# PolicyMatrix Reference

The PolicyMatrix is the organizational configuration that tells DAF what the system is permitted to do. It is a YAML file owned by you — not by DAF. DAF enforces it. You define it.

---

## Overview

```yaml
version: "1.0.0"
tenant_id: "your-org"
effective: "2026-01-01T00:00:00Z"

agent_roles: { ... }
orchestrator_routing: { ... }
budget_policy: { ... }
compliance_rules: [ ... ]
risk_policy: { ... }
loop_policy: { ... }
```

---

## agent_roles

Defines what each agent role is permitted to do.

```yaml
agent_roles:
  document_reader:
    permitted_tools:
      - read_db
      - llm_extraction
    permitted_data_sources:
      - internal_documents
      - public_documents
    permitted_task_types:
      - deterministic
      - llm_extraction
      - llm_summarization
    max_llm_calls_per_step: 3

  report_writer:
    permitted_tools:
      - llm_generation
      - write_file
    permitted_data_sources: []   # receives data from other agents only
    permitted_task_types:
      - llm_generation
    max_llm_calls_per_step: 2
```

**Notes:**
- An agent with no data sources in its context cannot access any data directly
- Tools not in `permitted_tools` do not exist in the agent's ScopedContext
- `max_llm_calls_per_step` prevents runaway reasoning loops

---

## orchestrator_routing

Defines which orchestrators can spawn which agent roles.

```yaml
orchestrator_routing:
  document_orchestrator:
    may_spawn_roles:
      - document_reader
      - report_writer

  finance_orchestrator:
    may_spawn_roles:
      - finance_reader
      - risk_analyzer

  # Admin orchestrator not listed = cannot be requested
```

**Notes:**
- An orchestrator not listed cannot be used at all
- An agent role not listed under an orchestrator cannot be spawned by it
- This prevents privilege escalation through orchestrator chains

---

## budget_policy

Hard cost limits enforced at the API level before execution.

```yaml
budget_policy:
  max_cost_per_call_usd: 0.02       # single LLM call
  max_cost_per_step_usd: 0.10       # one sub-task
  max_cost_per_workflow_usd: 0.50   # entire loop
  max_cost_per_user_day_usd: 5.00   # per user per day
  max_cost_per_tenant_day_usd: 100.00
```

**Notes:**
- These are hard counters. Not suggestions. Not logged-after-the-fact.
- BudgetTracker checks before every LLM call. If insufficient budget, the call does not happen.
- Set `max_cost_per_workflow_usd` conservatively — you can always raise it

---

## compliance_rules

Regulatory and organizational rules evaluated per sub-task.

```yaml
compliance_rules:
  - rule_ref: "DATA-GDPR-ART46"
    condition: "pii_data in task.data_required AND tenant.region != EU_APPROVED"
    action: block
    remediation_hint: "Route PII through EU-approved data pipeline only"

  - rule_ref: "DATA-RETENTION-001"
    condition: "task.output_destination == external_storage"
    action: require_human_gate
    remediation_hint: "External storage requires data governance approval"

  - rule_ref: "FINANCE-SOX-001"
    condition: "task.agent_required == finance_reader AND amount > 10000"
    action: require_human_gate
    remediation_hint: "Financial decisions above $10K require manager approval"
```

**action values:**
- `block` — sub-task is rejected, violation returned to Planning Orchestrator
- `warn` — sub-task is approved but violation is logged
- `require_human_gate` — sub-task is approved but execution pauses for human review

---

## risk_policy

Governs how risk is assessed for irreversible actions.

```yaml
risk_policy:
  irreversible_min_confidence: 0.90
  always_gate_action_classes:
    - send_email
    - delete_record
    - external_api_write
    - financial_transaction
  auto_approve_action_classes:
    - read_only
    - internal_write
    - generate_draft
```

**Notes:**
- Actions in `always_gate_action_classes` always require human approval regardless of confidence
- Actions in `auto_approve_action_classes` bypass the confidence check
- Everything else uses `irreversible_min_confidence` when `reversible: false`

---

## loop_policy

Controls the Governed Agentic Loop termination behaviour.

```yaml
loop_policy:
  max_replan_attempts: 3      # loop halts and escalates after this many violations
  max_duration_s: 300         # 5 minutes maximum per workflow
```

**Notes:**
- `max_replan_attempts: 3` is the recommended default based on research findings
- Increase only if your use case regularly involves complex multi-constraint scenarios
- `max_duration_s` is a hard limit enforced by the Execution Orchestrator

---

## Full Example

See [policy/matrix/example.yaml](../policy/matrix/example.yaml) for a complete working configuration.

---

## Validating Your PolicyMatrix

```bash
python scripts/validate_policy_matrix.py policy/matrix/my_policy.yaml
```

This checks schema compliance and detects conflicting or redundant rules before deployment.
