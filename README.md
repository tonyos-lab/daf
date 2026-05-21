# DAF — Deterministic Agentic Framework

> The model proposes. The system governs.

DAF is the reference implementation of **Policy-Based Agentic Systems (PBAS)** — a framework for building agentic AI applications where the LLM generates plans but a deterministic policy engine controls what actually executes.

[![Tests](https://img.shields.io/badge/tests-558%20passing-brightgreen)](tests/)
[![Version](https://img.shields.io/badge/version-0.1.0-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Lab](https://img.shields.io/badge/lab-TonyOS%20Lab-orange)](https://tonyos-lab.org)

---

## The Problem DAF Solves

Current agentic frameworks give the LLM too much execution authority. When the model hallucinates a tool call, invents a permission, or misunderstands scope — the system executes it.

DAF separates concerns:

```
LLM                    Policy Engine          Execution
─────────────────      ─────────────────      ────────────────
Proposes a plan   →    Evaluates the plan  →  Executes if approved
(cognitive)            (governance)           (within granted scope)
```

The Policy Engine is **deterministic** — no LLM calls, no probabilities. Either the plan conforms to the PolicyMatrix or it doesn't.

---

## Run in 2 Minutes

```bash
git clone https://github.com/tonyos-lab/daf.git
cd daf
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run a boilerplate immediately — no API key needed
python boilerplates/01_contract_reviewer/run_mock.py
python boilerplates/05_report_generator/run_mock.py
python boilerplates/07_multi_tenant/run_mock.py
```

---

## The Governed Agentic Loop

```
WorkflowRequest
      │
      ▼
┌─────────────────┐
│ InputProcessor  │  validates, sanitizes, classifies intent
└────────┬────────┘
         │
         ▼
┌─────────────────┐     violation
│   PLAN          │◄────────────────────────────┐
│ PlanningOrch.   │     (with context)           │
└────────┬────────┘                              │
         │ PlanProposal                          │
         ▼                                       │
┌─────────────────┐                              │
│   EVALUATE      │── REJECTED ─────────────────►│
│ PolicyEngine    │                               │
│ + HITL          │── APPROVED (gated) ──► human review
└────────┬────────┘
         │ ApprovalGrant
         ▼
┌─────────────────┐
│   EXECUTE       │  agents run inside ScopedContext
│ ExecutionOrch.  │  only permitted tools exist
└────────┬────────┘
         │
         ▼
  FinalResponse
```

---

## Quick Start (With API Key)

```python
import asyncio, os
from daf import GovernedAgenticLoop
# from your_module import YourLLMClient  # implement BaseLLMClient
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.tool_registry import ToolRegistry

loop = GovernedAgenticLoop(
    llm_client=AnthropicLLMClient(api_key=os.getenv("LLM_API_KEY")),
    policy_matrix="policy/matrix/example.yaml",
    agent_registry=AgentRegistry(),   # register your agents
    tool_registry=ToolRegistry(),     # register your tools
)

result = asyncio.run(loop.run({
    "task":      "Analyse the quarterly contracts",
    "tenant_id": "acme-corp",
    "user_id":   "alice@acme.com",
}))

print(result.outcome)        # "completed", "partial", "escalated", "invalid_input"
print(result.total_cost_usd)
```

## Quick Start (Mock — No API Key)

```python
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient, FixturePlanBuilder

plan = FixturePlanBuilder()\
    .with_task("ST-01", agent="analyst", tools=["read_db"])\
    .build()

loop = GovernedAgenticLoop(
    llm_client=MockLLMClient(responses=[plan]),
    policy_matrix="policy/matrix/example.yaml",
    ...
)
```

---

## The PolicyMatrix

Governance rules live in a YAML file — not in code.

```yaml
agent_roles:
  analyst:
    permitted_tools: [read_db, llm_extraction]
    permitted_task_types: [llm_extraction, deterministic]

budget_policy:
  max_cost_per_workflow_usd: 0.50

compliance_rules:
  - rule_ref: "GDPR-PII-001"
    condition:
      field: "data_required"
      operator: "contains"
      value: "pii_data"
    action: block

risk_policy:
  always_gate_action_classes: [send_email, delete_record]
```

Any plan that violates these rules is rejected. The LLM re-plans with the violation context. After `max_replan_attempts`, the loop escalates.

---

## Repository Structure

```
daf/
  daf/                    framework source code
    components/           PolicyEngine, PlanningOrch, EvaluateStage, etc.
    runtime/              LLMClient, ToolRegistry, AgentRegistry, AuditStore, etc.
    models/               WorkflowRequest, PlanProposal, ApprovalGrant, etc.
    tools/                StubTool
    agents/               StubAgent
    testing/              MockLLMClient, FixturePlanBuilder
  tests/
    unit/                 461 tests
    adversarial/          53 adversarial tests
    integration/          mocked integration tests
  examples/
    01_basic_analysis/    happy path
    02_replan_loop/       self-correction
    03_governed_action/   HITL gate
  boilerplates/
    01_contract_reviewer/ extract terms from contracts
    02_research_summariser/ multi-source research brief
    03_support_triage/    classify tickets, draft responses
    04_code_review/       PR review with security scanning
    05_report_generator/  generate + approve + send
    06_db_migration/      validate SQL migrations
    07_multi_tenant/      per-tenant governance policies
  docs/
    api-reference.md      complete programmatic API reference
    design-philosophy.md  8 design principles
    developer-guide.md    how to extend DAF
  policy/
    matrix/
      example.yaml        working example PolicyMatrix
```

---

## Run the Tests

```bash
# All tests — no API key needed (561 tests)
python -m pytest tests/unit/ tests/adversarial/ \
  tests/integration/test_example01_mocked.py \
  tests/integration/test_example02_mocked.py \
  tests/integration/test_example03_mocked.py -q

# With API key (live LLM integration tests)
cp .env.example .env   # add LLM_API_KEY
python -m pytest tests/integration/test_phase1_loop.py -v
```

---

## The Seven Boilerplates

| # | Project | Key Concept |
|---|---|---|
| [01](boilerplates/01_contract_reviewer/) | Contract Reviewer | Basic happy path |
| [02](boilerplates/02_research_summariser/) | Research Summariser | Multi-step + two roles |
| [03](boilerplates/03_support_triage/) | Support Triage | Compliance rules + HITL |
| [04](boilerplates/04_code_review/) | Code Review | Re-planning + multiple roles |
| [05](boilerplates/05_report_generator/) | Report Generator | Irreversible action gate |
| [06](boilerplates/06_db_migration/) | DB Migration Validator | Risk policy + compliance |
| [07](boilerplates/07_multi_tenant/) | Multi-Tenant Processor | Per-tenant PolicyMatrix |

```bash
# Run any boilerplate immediately
python boilerplates/01_contract_reviewer/run_mock.py
```

---

## Extending DAF

```python
# Implement a tool
from daf.runtime.tool import BaseTool, ToolResult

class ReadDbTool(BaseTool):
    name       = "read_db"
    idempotent = True

    async def call(self, query: str, **kwargs) -> ToolResult:
        rows = await my_db.fetch(query)
        return ToolResult.ok(output={"rows": rows})

# Implement an agent
from daf.runtime.agent import BaseAgent, AgentResult

class AnalystAgent(BaseAgent):
    role = "analyst"

    async def execute(self, task, context) -> AgentResult:
        tool   = context.tools.get("read_db")
        result = await tool.call(query="SELECT * FROM contracts")
        return AgentResult.ok(task.task_id, output=result.output)
```

See [docs/api-reference.md](docs/api-reference.md) for the full API.

---

## Research

DAF is the reference implementation of the PBAS (Policy-Based Agentic Systems) framework described in:

> *Policy-Based Agentic Systems: A Framework for Deterministic Governance of LLM Agents*  
> TonyOS Lab — [tonyos-lab.org](https://tonyos-lab.org)  
> *(arXiv submission pending)*

---

## License

Apache License 2.0 — see [LICENSE](LICENSE)

---

## TonyOS Lab

[tonyos-lab.org](https://tonyos-lab.org) · [tony.ochinang@tonyos-lab.org](mailto:tony.ochinang@tonyos-lab.org)
