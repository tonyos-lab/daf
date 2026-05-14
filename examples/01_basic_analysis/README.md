# Example 01: Basic Analysis

**DAF concept demonstrated:** The happy path — Plan → Evaluate → Execute in a single iteration.

---

## What This Example Does

Given a task description, DAF:
1. Plans 3 sub-tasks (read documents → extract features → summarise)
2. PolicyEngine checks all tasks — all pass (correct tools, within budget, no gates)
3. Agents execute each step with scoped permissions
4. Returns a `FinalResponse` with the audit trail

This is the simplest possible DAF workflow. One agent role, read-only operations, no HITL.

---

## Prerequisites

```bash
cd daf
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## Run in Mock Mode (no API key needed)

Mock mode uses `MockLLMClient` to return pre-written plan responses.
The PolicyEngine, ExecutionOrchestrator, and audit trail all run for real.

```bash
python examples/01_basic_analysis/run_mock.py
```

**Expected output:**
```
Scenario: Happy Path (3 steps, all succeed)
  Outcome:         completed
  Loop iterations: 1
  Total cost:      $0.0600
  Steps (3):
    ✓ ST-01  $0.0200
    ✓ ST-02  $0.0200
    ✓ ST-03  $0.0200

Scenario: Over-Budget Plan (always rejected → escalated)
  Outcome:         escalated
  Loop iterations: 3

Scenario: Re-plan (forbidden tool → self-corrects → completed)
  Outcome:         completed
  Loop iterations: 2
```

---

## Run in Real Mode (requires API key)

```bash
cp .env.example .env
# Add: LLM_API_KEY=sk-ant-your-key-here
python examples/01_basic_analysis/run.py
```

---

## Run the Tests

```bash
python -m pytest tests/integration/test_example01_mocked.py -v
```

---

## Understanding the Mock Responses

Mock responses live in `mock_responses.py`. They simulate what the LLM
would return. The PolicyEngine, ExecutionOrchestrator, and audit trail
all run for real — only the LLM call is replaced.

```python
from examples.01_basic_analysis.mock_responses import (
    HAPPY_PATH_PLAN,       # 3 steps, all valid → completed
    MINIMAL_PLAN,          # 1 step → completed
    OVER_BUDGET_PLAN,      # cost > budget limit → rejected
    FORBIDDEN_TOOL_PLAN,   # uses write_db (not permitted) → rejected
)
```

**Use in your own tests:**

```python
import pytest
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from examples.01_basic_analysis.mock_responses import HAPPY_PATH_PLAN
from examples.01_basic_analysis.agents import build_agent_registry
from examples.01_basic_analysis.tools  import build_tool_registry

@pytest.mark.asyncio
async def test_my_analysis():
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=[HAPPY_PATH_PLAN]),
        policy_matrix="examples/01_basic_analysis/policy/matrix.yaml",
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
    )
    result = await loop.run({"task": "Analyse the documents"})
    assert result.outcome == "completed"
```

**Test the re-plan scenario:**

```python
from examples.01_basic_analysis.mock_responses import (
    FORBIDDEN_TOOL_PLAN, HAPPY_PATH_PLAN
)

loop = GovernedAgenticLoop(
    llm_client=MockLLMClient(responses=[
        FORBIDDEN_TOOL_PLAN,  # iteration 1 → rejected by PolicyEngine
        HAPPY_PATH_PLAN,      # iteration 2 → approved
    ]),
    ...
)
result = await loop.run({"task": "..."})
assert result.outcome         == "completed"
assert result.loop_iterations == 2
```

---

## Project Structure

```
examples/01_basic_analysis/
  README.md            this file
  policy/matrix.yaml   PolicyMatrix — one analyst role, no gates
  mock_responses.py    sample LLM responses (4 scenarios)
  agents.py            AnalystAgent stub + build_agent_registry()
  tools.py             read_db, llm_extraction, llm_summarization stubs
  run_mock.py          three scenarios, zero dependencies
  run.py               real LLM mode (requires LLM_API_KEY)
```

---

## Adapting to Your Use Case

**1. Update `policy/matrix.yaml`** with your agent role and tool names.

**2. Implement real tools in `tools.py`:**

```python
from daf.runtime.tool import BaseTool, ToolResult

class ReadDbTool(BaseTool):
    name       = "read_db"
    idempotent = True

    async def call(self, query: str, **kwargs) -> ToolResult:
        rows = await my_db.fetch(query)
        return ToolResult.ok(output={"rows": rows})
```

**3. Implement real agents in `agents.py`:**

```python
from daf.runtime.agent import BaseAgent, AgentResult

class AnalystAgent(BaseAgent):
    role = "analyst"

    async def execute(self, task, context) -> AgentResult:
        tool   = context.tools.get("read_db")
        result = await tool.call(query="SELECT * FROM documents")
        return AgentResult.ok(task.task_id, output=result.output)
```

**4. Write a mock response for your tools:**

```python
from daf.testing import FixturePlanBuilder

MY_PLAN = FixturePlanBuilder()\
    .with_task("ST-01", agent="analyst", tools=["read_db"])\
    .build()
```
