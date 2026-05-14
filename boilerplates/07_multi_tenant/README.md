# Boilerplate 07: Multi-Tenant Document Processor

**Use case:** SaaS platforms — one DAF instance, different governance policies per tenant.

**DAF concepts:** Per-tenant PolicyMatrix loading. Same agent code, different compliance outcomes.

## Run immediately
```bash
python boilerplates/07_multi_tenant/run_mock.py
```

Expected output (same task, three tenants):
```
  Tenant: standard-tenant
  outcome: completed   iterations: 1

  Tenant: gdpr-tenant
  outcome: completed   iterations: 2   ← re-planned without pii_data
  (GDPR-PII-001 blocked pii_data access → LLM re-planned)

  Tenant: sox-tenant
  outcome: completed   iterations: 1
  HITL: ['ST-01']      ← financial_records triggered SOX gate
```

## Mock responses
```python
from mock_responses import (
    TENANT_AWARE_PLAN,  # includes pii_data + financial_records
    COMPLIANT_PLAN,     # documents only — safe for all tenants
)
```

## Three PolicyMatrix files
```
policy/
  standard_tenant.yaml   no compliance rules, permissive
  gdpr_tenant.yaml       GDPR-PII-001 (block), GDPR-EXPORT-001 (gate)
  sox_tenant.yaml        SOX-FINANCIAL-001 (gate), generation always gated
```

## The per-tenant loading pattern
```python
TENANT_MATRICES = {
    "standard-tenant": "policy/standard_tenant.yaml",
    "gdpr-tenant":     "policy/gdpr_tenant.yaml",
    "sox-tenant":      "policy/sox_tenant.yaml",
}

loop = GovernedAgenticLoop(
    llm_client=...,
    policy_matrix=TENANT_MATRICES[tenant_id],  # loaded per request
    ...
)
```

## Real mode tenant selection
```bash
TENANT_ID=gdpr-tenant python boilerplates/07_multi_tenant/run.py
TENANT_ID=sox-tenant  python boilerplates/07_multi_tenant/run.py
```
