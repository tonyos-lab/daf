# Example 02: Re-planning Loop

**DAF concept demonstrated:** Self-correction — when the PolicyEngine rejects a plan, the loop re-plans using the violation context.

---

## What This Example Does

1. LLM proposes a plan that uses `write_db` (not permitted)
2. PolicyEngine rejects: `tool_permission` violation on `write_db`
3. LLM re-plans — removes `write_db`, uses only `read_db` and `llm_extraction`
4. PolicyEngine approves the revised plan
5. Returns `FinalResponse(outcome="completed", loop_iterations=2)`

---

## Prerequisites

```bash
cd daf && pip install -r requirements.txt
```

---

## Run in Mock Mode (no API key needed)

```bash
python examples/02_replan_loop/run_mock.py
```

**Expected output:**
```
Scenario: Re-plan: forbidden tool → self-corrects → completed
  Outcome:         completed
  Loop iterations: 2
  Steps (2): ✓ ST-01, ✓ ST-02

Scenario: Escalation: always-forbidden plan → max attempts
  Outcome:         escalated
  Loop iterations: 3
```

---

## Run the Tests

```bash
python -m pytest tests/integration/test_example02_mocked.py -v
```

---

## Understanding the Mock Responses

```python
from examples.02_replan_loop.mock_responses import (
    FORBIDDEN_PLAN,        # uses write_db → rejected
    REVISED_PLAN,          # uses read_db only → approved
    ALWAYS_FORBIDDEN_PLAN, # always rejected → escalates after 3 attempts
)
```

**The re-plan scenario — two responses in sequence:**

```python
from daf.testing import MockLLMClient

client = MockLLMClient(responses=[
    FORBIDDEN_PLAN,   # call 1 → PolicyEngine rejects → violation added to history
    REVISED_PLAN,     # call 2 → PolicyEngine approves → execution starts
])
```

**The escalation scenario — one response repeated:**

```python
client = MockLLMClient(responses=[ALWAYS_FORBIDDEN_PLAN])
# MockLLMClient repeats the last response when the list is exhausted.
# All 3 attempts use ALWAYS_FORBIDDEN_PLAN → all rejected → escalated.
```

**Write your own test:**

```python
@pytest.mark.asyncio
async def test_replan():
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=[FORBIDDEN_PLAN, REVISED_PLAN]),
        policy_matrix="examples/02_replan_loop/policy/matrix.yaml",
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
    )
    result = await loop.run({"task": "Read and process documents"})
    assert result.outcome         == "completed"
    assert result.loop_iterations == 2
```

---

## Project Structure

```
examples/02_replan_loop/
  README.md               this file
  policy/matrix.yaml      PolicyMatrix — write_db intentionally excluded
  mock_responses.py       FORBIDDEN_PLAN, REVISED_PLAN, ALWAYS_FORBIDDEN_PLAN
  agents_and_tools.py     AnalystAgent + tool stubs
  run_mock.py             two scenarios, zero dependencies
  run.py                  real LLM mode (requires LLM_API_KEY)
```

---

## Why the PolicyMatrix Excludes `write_db`

```yaml
agent_roles:
  analyst:
    permitted_tools:
      - read_db
      - llm_extraction
    # write_db is intentionally absent.
    # Any plan requesting it → tool_permission violation → rejected.
```

This is the point of the example: the violation is deterministic and unavoidable until the LLM stops requesting `write_db`.
