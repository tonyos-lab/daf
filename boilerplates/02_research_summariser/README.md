# Boilerplate 02: Research Summariser

**Use case:** Market research, competitive intelligence, literature review.

**DAF concepts:** Multi-step plan with dependencies, two agent roles (fetcher + analyst).

## Run immediately
```bash
python boilerplates/02_research_summariser/run_mock.py
```

## Mock responses
```python
from mock_responses import (
    MULTI_SOURCE_PLAN,   # fetch 3 URLs → extract → cross-ref → brief → completed
    SINGLE_SOURCE_PLAN,  # fetch 1 URL → summarise → completed
    FORBIDDEN_PLAN,      # wrong tool for role → rejected → re-plans
)
```

## Test
```python
from daf.testing import MockLLMClient
from mock_responses import MULTI_SOURCE_PLAN
loop = GovernedAgenticLoop(
    llm_client=MockLLMClient(responses=[MULTI_SOURCE_PLAN]), ...)
result = await loop.run({"task": "Research AI market trends"})
assert result.outcome == "completed"
assert result.loop_iterations == 1
```

## Key PolicyMatrix features
- Two roles: `fetcher` (http_fetch only) and `analyst` (llm tools only)
- Role separation enforced structurally — fetcher cannot call LLM tools
- No compliance rules, no HITL gates
- Budget: $1.00 per workflow
