# Example 03: Governed Action

**DAF concept demonstrated:** HITL gate — human must approve gated tasks before any execution begins.

---

## What This Example Does

1. LLM proposes a plan with two tasks: extract data + generate report
2. PolicyEngine: APPROVED — but marks `ST-02` (llm_generation) as **gated**
3. EvaluateStage sends a `HumanReviewRequest` to the gateway
4. Human reviews the gated task and decides:
   - **Approved** → both tasks execute → `completed`
   - **Rejected** → ViolationReport → loop re-plans without the gated task
   - **Timeout** → auto-rejected → escalated

---

## Prerequisites

```bash
cd daf && pip install -r requirements.txt
```

---

## Run in Mock Mode (no API key needed)

```bash
python examples/03_governed_action/run_mock.py
```

**Expected output:**
```
Scenario: HITL approved → workflow completes
  Outcome:         completed
  Loop iterations: 1
  Steps (2): ✓ ST-01, ✓ ST-02
  HITL request:    1 task(s) reviewed
  Gated task(s):   ['ST-02']

Scenario: HITL rejected → re-plans with ungated approach → completes
  Outcome:         completed
  Loop iterations: 2

Scenario: HITL timeout → auto-rejected → escalates
  Outcome:         escalated
  Loop iterations: 3
```

---

## Run the Tests

```bash
python -m pytest tests/integration/test_example03_mocked.py -v
```

---

## Understanding the Mock Responses

```python
from examples.03_governed_action.mock_responses import (
    GATED_PLAN,    # ST-02 is llm_generation → PolicyEngine gates it
    UNGATED_PLAN,  # revised plan with only llm_extraction → no gate
)
```

**Configure the HITL gateway:**

```python
from daf.runtime.human_review_gateway import StubHumanReviewGateway

# Always approve every gated task
gateway = StubHumanReviewGateway(approve_all=True)

# Always reject every gated task
gateway = StubHumanReviewGateway(approve_all=False)

# Simulate timeout (auto-rejects)
gateway = StubHumanReviewGateway(simulate_timeout=True)

# Custom response — approve some tasks, reject others
from daf.models.human_review import HumanReviewResponse, TaskDecision

gateway = StubHumanReviewGateway()
gateway.set_next_response(HumanReviewResponse(
    review_id=..., grant_id=..., reviewer_id="alice",
    task_decisions=[
        TaskDecision(task_id="ST-02", decision="approved",
                     reason="Report recipients verified"),
    ]
))
```

**Write your own test:**

```python
@pytest.mark.asyncio
async def test_hitl_approved():
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=[GATED_PLAN]),
        policy_matrix="examples/03_governed_action/policy/matrix.yaml",
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
        hitl_gateway=StubHumanReviewGateway(approve_all=True),
    )
    result = await loop.run({"task": "Generate a report"})
    assert result.outcome == "completed"
    assert result.loop_iterations == 1

@pytest.mark.asyncio
async def test_hitl_rejection_replans():
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=[GATED_PLAN, UNGATED_PLAN]),
        ...
        hitl_gateway=StubHumanReviewGateway(approve_all=False),
    )
    result = await loop.run({"task": "Generate a report"})
    assert result.outcome         == "completed"
    assert result.loop_iterations == 2
```

---

## Why `llm_generation` Is Gated

```yaml
risk_policy:
  always_gate_action_classes:
    - llm_generation
```

Any sub-task with `task_type: llm_generation` is automatically gated.
The PolicyEngine sets `gated_tasks=["ST-02"]` in the ApprovalGrant.
EvaluateStage then requests human approval before any execution.

Change `always_gate_action_classes` to gate different action types
(e.g. `send_email`, `delete_record`, `publish_content`).

---

## Project Structure

```
examples/03_governed_action/
  README.md               this file
  policy/matrix.yaml      PolicyMatrix — llm_generation always gated
  mock_responses.py       GATED_PLAN, UNGATED_PLAN
  agents_and_tools.py     AnalystAgent + tool stubs
  run_mock.py             three HITL scenarios, zero dependencies
  run.py                  real LLM + real HITL gateway
```
