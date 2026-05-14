# Boilerplate 04: Code Review Assistant

**Use case:** Automated PR review with security scanning, quality checks, and gated comment generation.

**DAF concepts:** Three roles (security, quality, summariser) + re-planning + HITL on comment generation.

## Run immediately
```bash
python boilerplates/04_code_review/run_mock.py
```

## Mock responses
```python
from mock_responses import (
    FULL_REVIEW_PLAN,       # security + quality + generate comment (GATED)
    SECURITY_ONLY_PLAN,     # security scan only, no gate
    REPLAN_TRIGGER_PLAN,    # wrong tool for role → rejected → re-plans
)
```

## Key PolicyMatrix features
- Three isolated roles: security_reviewer, quality_reviewer, summariser
- Each role has only its own tools — cross-role tool access impossible
- Comment generation (llm_generation) always gated for human approval
