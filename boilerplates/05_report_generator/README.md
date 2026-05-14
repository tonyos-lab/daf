# Boilerplate 05: Report Generator with Approval

**Use case:** Finance, operations, executive reporting — generate reports and email only after human approval.

**DAF concepts:** Irreversible action gate — `always_gate_action_classes: [llm_generation]`.

## Run immediately
```bash
python boilerplates/05_report_generator/run_mock.py
```

Expected output:
```
  Full report — approved and sent
  outcome: completed   iterations: 1   cost: $0.0900
  ✓ ST-01  ✓ ST-02  ✓ ST-03
  HITL: ['ST-03'] reviewed

  Full report — human rejects → re-plans without generation
  outcome: completed   iterations: 2   cost: $0.0400

  Analyse only — no generation gate
  outcome: completed   iterations: 1   cost: $0.0400
```

## Mock responses
```python
from mock_responses import (
    FULL_REPORT_PLAN,    # analyse → extract → generate (GATED) → completed
    ANALYSE_ONLY_PLAN,   # analyse only → no gate → completed
    FORBIDDEN_PLAN,      # data_analyst tries send_email → rejected
)
```

## The irreversible action pattern
```yaml
risk_policy:
  always_gate_action_classes:
    - llm_generation     # gate before generation
    # Add send_email here to also gate before sending
```
Anything in `always_gate_action_classes` triggers human review.
Change this to match your own irreversible actions.

## Two-role separation
- `data_analyst`: reads data, extracts metrics — no generation, no email
- `reporter`: generates and sends reports — no data access
- Neither role can do the other's job — enforced structurally

## Files
```
05_report_generator/
  README.md              this file
  policy/matrix.yaml     two roles, llm_generation always gated
  mock_responses.py      FULL_REPORT_PLAN, ANALYSE_ONLY_PLAN, FORBIDDEN_PLAN
  agents.py              DataAnalystAgent, ReporterAgent
  tools.py               read_csv, llm_extraction, llm_generation, send_email stubs
  run_mock.py            4 scenarios including rejection and re-plan
  run.py                 real LLM + CLIHumanReviewGateway
```
