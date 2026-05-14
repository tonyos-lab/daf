# Boilerplate 06: DB Migration Validator

**Use case:** DBA and DevOps teams validating SQL migrations before deployment.

**DAF concepts:** Compliance rules that gate destructive operations (DROP, TRUNCATE, production schema).

## Run immediately
```bash
python boilerplates/06_db_migration/run_mock.py
```

## Mock responses
```python
from mock_responses import (
    SAFE_MIGRATION_PLAN,         # ADD/CREATE only → auto-approved → completed
    DESTRUCTIVE_MIGRATION_PLAN,  # contains destructive_ops → DB-DROP-001 gate
    PROD_MIGRATION_PLAN,         # production_schema → DB-PROD-BLOCK gate
    FORBIDDEN_PLAN,              # execute_sql not permitted → rejected
)
```

## Compliance rules in action
```yaml
compliance_rules:
  - rule_ref: "DB-DROP-001"
    condition:
      field: "data_required"
      operator: "contains"
      value: "destructive_ops"
    action: require_human_gate

  - rule_ref: "DB-PROD-BLOCK"
    condition:
      field: "data_required"
      operator: "contains"
      value: "production_schema"
    action: require_human_gate
```
When the LLM includes `destructive_ops` or `production_schema` in `data_required`,
the compliance rule fires and the task is gated for human review.
