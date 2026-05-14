# Boilerplate 03: Support Triage

**Use case:** Customer service — classify tickets, draft responses, require human review before sending.

**DAF concepts:** Compliance rule gates all response drafts (llm_generation → require_human_gate).

## Run immediately
```bash
python boilerplates/03_support_triage/run_mock.py
```

## Mock responses
```python
from mock_responses import (
    TRIAGE_PLAN,          # read → classify → draft (GATED) → approved → completed
    CLASSIFY_ONLY_PLAN,   # read → classify only → no gate → completed
    FORBIDDEN_TOOL_PLAN,  # send_email not permitted → rejected → re-plans
)
```

## HITL gateway options
```python
from daf.runtime.human_review_gateway import StubHumanReviewGateway

StubHumanReviewGateway(approve_all=True)     # auto-approve all drafts
StubHumanReviewGateway(approve_all=False)    # auto-reject all drafts
StubHumanReviewGateway(simulate_timeout=True) # simulate no response
```

## Key PolicyMatrix feature
```yaml
compliance_rules:
  - rule_ref: "REFUND-GATE-001"
    condition:
      field: "task_type"
      operator: "equals"
      value: "llm_generation"
    action: require_human_gate
```
Every response draft requires human approval. Change the condition to gate only specific cases.
