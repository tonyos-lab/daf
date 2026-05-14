# Boilerplate 01: Contract Reviewer

**Use case:** Legal and procurement teams reviewing vendor contracts before signing.

**DAF concepts:** Basic happy path — single agent role, read-only tools, no gates.

---

## What It Does

1. Reads a contract file from storage
2. Extracts: payment terms, liability cap, notice period, governing law
3. Classifies overall risk level (low / medium / high)
4. Returns structured summary in `FinalResponse`

Nothing is written. Nothing is sent. Read-only throughout.

---

## Run Immediately (no API key)

```bash
python boilerplates/01_contract_reviewer/run_mock.py
```

Expected output:
```
  Standard contract review (3 steps)
  outcome:    completed
  iterations: 1
  cost:       $0.0900
  ✓ ST-01  ✓ ST-02  ✓ ST-03

  Minimal review (1 step)
  outcome:    completed
  iterations: 1
  cost:       $0.0300

  Re-plan: forbidden tool → self-corrects
  outcome:    completed
  iterations: 2
```

---

## Run With Real LLM

```bash
cp .env.example .env          # add LLM_API_KEY
python boilerplates/01_contract_reviewer/run.py
```

---

## Test With Mock Responses

```python
import pytest
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from mock_responses import STANDARD_CONTRACT_PLAN
from agents import build_agent_registry
from tools import build_tool_registry

@pytest.mark.asyncio
async def test_contract_review():
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=[STANDARD_CONTRACT_PLAN]),
        policy_matrix="boilerplates/01_contract_reviewer/policy/matrix.yaml",
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
    )
    result = await loop.run({
        "task": "Review the vendor contract",
        "tenant_id": "your-org",
        "user_id": "analyst-1",
    })
    assert result.outcome == "completed"
    assert result.loop_iterations == 1
```

---

## Mock Responses Reference

```python
from mock_responses import (
    STANDARD_CONTRACT_PLAN,  # 3 steps: read → extract → classify → completed
    MINIMAL_PLAN,            # 1 step: extract all → completed
    FORBIDDEN_TOOL_PLAN,     # uses write_db → rejected → triggers re-plan
)
```

---

## Adapting to Your Use Case

1. **Update `policy/matrix.yaml`** — change tool names to match your storage system
2. **Implement `tools.py`** — replace StubTool with your file storage client
3. **Implement `agents.py`** — replace StubAgent with your extraction logic
4. **Update `mock_responses.py`** — change tool names to match your updated policy

---

## Files

```
01_contract_reviewer/
  README.md              this file
  policy/matrix.yaml     one analyst role, read-only, no gates
  mock_responses.py      STANDARD_CONTRACT_PLAN, MINIMAL_PLAN, FORBIDDEN_TOOL_PLAN
  agents.py              ContractAnalystAgent stub
  tools.py               read_file, llm_extraction, llm_classification stubs
  run_mock.py            3 scenarios, no API key needed
  run.py                 real LLM mode
```
