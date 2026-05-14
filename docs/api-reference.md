# DAF API Reference

Complete programmatic reference for building with and extending DAF.

**Three audiences:**
- **Building with DAF** — use the Entry Point and configure via PolicyMatrix YAML
- **Extending DAF** — implement `BaseTool`, `BaseAgent`, `BaseHumanReviewGateway`
- **Infrastructure** — inject `AuditStore`, `CheckpointStore`, `LLMClient`

---

## Quick Start

```python
import asyncio
from daf import GovernedAgenticLoop
from daf.runtime.anthropic_client import AnthropicLLMClient
from daf.runtime.agent_registry import AgentRegistry
from daf.runtime.tool_registry import ToolRegistry
from daf.runtime.audit_store import InMemoryAuditStore

# 1. Build registries
agent_registry = AgentRegistry()
agent_registry.register(MyAnalystAgent)      # your BaseAgent subclass

tool_registry = ToolRegistry()
tool_registry.register(MyReadDbTool())       # your BaseTool subclass

# 2. Configure the loop
loop = GovernedAgenticLoop(
    llm_client=AnthropicLLMClient(api_key="sk-ant-..."),
    policy_matrix="policy/matrix/prod.yaml",
    agent_registry=agent_registry,
    tool_registry=tool_registry,
    audit_store=InMemoryAuditStore(),
)

# 3. Run
result = asyncio.run(loop.run({
    "task":       "Analyse the quarterly contracts",
    "tenant_id":  "acme-corp",
    "user_id":    "alice@acme.com",
    "constraints": {"max_cost_usd": 0.50},
}))

print(result.outcome)         # "completed", "partial", "escalated", "invalid_input"
print(result.total_cost_usd)
print(result.loop_iterations)
```

---

## Entry Point

### `GovernedAgenticLoop`

```
from daf import GovernedAgenticLoop
```

The main entry point. Sequences all five components.

**Constructor:**

```python
GovernedAgenticLoop(
    llm_client:           LLMClient,                    # required
    policy_matrix:        str = "policy/matrix/example.yaml",
    audit_store:          AuditStore | None = None,     # InMemory if not provided
    checkpoint_store:     CheckpointStore | None = None,
    hitl_gateway:         BaseHumanReviewGateway | None = None,
    hitl_timeout_seconds: float = 3600.0,
    agent_registry:       AgentRegistry | None = None,
    tool_registry:        ToolRegistry | None = None,
)
```

**Methods:**

```python
async def run(raw_request: dict) -> FinalResponse
```

Run a workflow. Returns `FinalResponse` for all expected outcomes — never raises for
policy violations, HITL rejections, or invalid input. Only raises for
`LLMClientError` (API failure) or `LLMOutputError` (schema failure after retries).

**`raw_request` fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `task` | str | Yes | Natural language task description. Max 10,000 chars. |
| `tenant_id` | str | No | Organisation identifier. Default: `"default"` |
| `user_id` | str | No | User identifier. Default: `"anonymous"` |
| `constraints` | dict | No | `max_cost_usd`, `max_duration_s` |
| `context` | dict | No | Additional context passed to PlanningOrchestrator |
| `intent_class` | str | No | `"deterministic"`, `"llm"`, `"mixed"`. Auto-classified if not set. |

---

## Extending DAF

### `BaseTool`

```
from daf.runtime.tool import BaseTool, ToolResult, ToolCallError
```

Implement to create a tool agents can use.

**Required class attributes:**

```python
class MyTool(BaseTool):
    name:       str  = "my_tool"    # matches PolicyMatrix tool name
    idempotent: bool = True         # True = safe to retry on failure

    async def call(self, **kwargs) -> ToolResult:
        try:
            result = await do_something(**kwargs)
            return ToolResult.ok(output=result)
        except Exception as e:
            return ToolResult.fail(error=str(e))
```

**`ToolResult` constructors:**

```python
ToolResult.ok(output: Any, **metadata) -> ToolResult
ToolResult.fail(error: str, **metadata) -> ToolResult
```

**Raise `ToolCallError` only for infrastructure failures** (not business errors):

```python
raise ToolCallError(tool_name="my_tool", reason="DB connection lost")
```

---

### `BaseAgent`

```
from daf.runtime.agent import BaseAgent, AgentResult, AgentExecutionError
```

Implement to create an agent that executes sub-tasks.

**Required class attribute:**

```python
class MyAgent(BaseAgent):
    role: str = "my_agent"   # matches PolicyMatrix agent_role name

    async def execute(self, task: SubTask, context: ScopedContext) -> AgentResult:
        # Access permitted tools only
        tool   = context.tools.get("read_db")
        result = await tool.call(query="SELECT * FROM contracts")

        # Check budget before LLM calls
        if context.budget and not context.budget.check_and_reserve(0.02):
            return AgentResult.fail(task_id=task.task_id, error="Budget exhausted")

        return AgentResult.ok(task_id=task.task_id, output=result.output)
```

**`AgentResult` constructors:**

```python
AgentResult.ok(task_id: str, output: Any, cost_usd: float = 0.0, **metadata)
AgentResult.fail(task_id: str, error: str, cost_usd: float = 0.0, **metadata)
```

**Never override `run()`** — override `execute()` only. `run()` handles error wrapping.

---

### `BaseHumanReviewGateway`

```
from daf.runtime.human_review_gateway import BaseHumanReviewGateway
```

Implement to deliver HITL review requests to your reviewers.

```python
class SlackGateway(BaseHumanReviewGateway):
    async def request_and_wait(
        self,
        request: HumanReviewRequest,
    ) -> HumanReviewResponse:
        # Send to Slack
        await post_to_slack(request)
        # Poll for response
        response = await poll_for_response(request.review_id)
        # Handle timeout
        if response is None:
            return HumanReviewResponse.timeout_response(
                review_id=request.review_id,
                grant_id=request.grant_id,
                task_ids=request.gated_task_ids,
            )
        return response
```

---

### `LLMClient`

```
from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage
from daf.runtime.llm_client import LLMClientError, LLMOutputError
```

Implement to add a new LLM provider.

```python
class OpenAILLMClient(LLMClient):
    @property
    def model_id(self) -> str:
        return "gpt-4o-2024-11-20"

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return input_tokens * 0.0000025 + output_tokens * 0.00001

    async def complete(
        self,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int = 4096,
        max_retries: int = 2,
    ) -> LLMResponse:
        # Call OpenAI API, enforce schema, return LLMResponse
        ...
```

---

## Registries

### `ToolRegistry`

```
from daf.runtime.tool_registry import ToolRegistry
```

```python
registry = ToolRegistry()
registry.register(tool: BaseTool, replace: bool = False)
registry.get(tool_name: str) -> BaseTool      # raises ToolNotFoundError
registry.has(tool_name: str) -> bool
registry.names() -> list[str]
registry.scoped(permitted_names: list[str]) -> ScopedToolRegistry
```

### `AgentRegistry`

```
from daf.runtime.agent_registry import AgentRegistry
```

Stores **classes**, not instances. Agents are instantiated per sub-task.

```python
registry = AgentRegistry()
registry.register(agent_class: type[BaseAgent], replace: bool = False)
registry.instantiate(role: str, context: ScopedContext) -> BaseAgent
registry.has(role: str) -> bool
registry.roles() -> list[str]
registry.get_class(role: str) -> type[BaseAgent]
```

---

## Agent Runtime

### `ScopedContext`

```
from daf.runtime.scoped_context import ScopedContext
```

Passed to every agent's `execute()`. Contains only permitted tools.

```python
context.tools          # ScopedToolRegistry — only permitted tools
context.task_input     # dict — outputs from dependency tasks
context.role           # str — this agent's role name
context.max_calls      # int — maximum LLM calls permitted
context.budget         # BudgetTracker | None
context.permitted_data_sources  # list[str]

# Accessing a tool
tool = context.tools.get("read_db")        # raises ToolNotFoundError if not permitted
tool = context.tools.has("read_db")        # bool check before get
```

### `BudgetTracker`

```
from daf.runtime.budget_tracker import BudgetTracker
```

```python
# Typical agent usage:
if not context.budget.check_and_reserve(0.02):
    return AgentResult.fail(task_id=task.task_id, error="Budget exhausted")

response = await call_llm()

context.budget.record_actual(
    actual_cost=response.usage.cost_usd,
    reserved_cost=0.02,
)

# Properties
context.budget.spent         # float
context.budget.remaining     # float
context.budget.max_cost      # float
context.budget.is_exhausted  # bool
context.budget.summary()     # dict for audit records
```

---

## Audit Store

### `AuditStore` / `InMemoryAuditStore` / `PostgresAuditStore`

```
from daf.runtime.audit_store import AuditStore, InMemoryAuditStore
from daf.runtime.postgres_audit_store import PostgresAuditStore
```

```python
# InMemory (unit tests, development)
store = InMemoryAuditStore()

# PostgreSQL (production)
store = PostgresAuditStore(dsn="postgresql://daf:daf@localhost:5432/daf")
await store.connect()

# Async context manager
async with PostgresAuditStore.connect_ctx(dsn) as store:
    records = await store.query(request_id)

# Methods
await store.write(record: AuditRecord)
await store.query(request_id: UUID, event_type: str | None = None) -> list[AuditRecord]
await store.count(request_id: UUID) -> int
```

### `AuditRecord` / `AuditEventType`

```
from daf.models.audit_record import AuditRecord, AuditEventType
```

```python
# Create a record
record = AuditRecord.make(
    request_id=uuid,
    tenant_id="acme",
    user_id="alice",
    event_type=AuditEventType.WORKFLOW_STARTED,
    payload={"task": "..."},
)

# AuditEventType constants
AuditEventType.WORKFLOW_STARTED
AuditEventType.WORKFLOW_COMPLETED
AuditEventType.WORKFLOW_ESCALATED
AuditEventType.PLAN_PROPOSED
AuditEventType.PLAN_EVALUATED
AuditEventType.HUMAN_REVIEW_REQUESTED
AuditEventType.HUMAN_REVIEW_RESPONDED
AuditEventType.EXECUTION_STARTED
AuditEventType.STEP_STARTED
AuditEventType.STEP_COMPLETED
AuditEventType.STEP_FAILED
```

---

## Checkpoint Store

### `CheckpointStore` / `InMemoryCheckpointStore` / `RedisCheckpointStore`

```
from daf.runtime.checkpoint_store import CheckpointStore, InMemoryCheckpointStore
from daf.runtime.checkpoint_store import RedisCheckpointStore
```

```python
# InMemory (tests)
store = InMemoryCheckpointStore()

# Redis (production)
store = RedisCheckpointStore(url="redis://localhost:6379/0", ttl_seconds=86400)
await store.connect()

# Methods
await store.save(checkpoint: WorkflowCheckpoint)
await store.load(request_id: UUID) -> WorkflowCheckpoint | None
await store.delete(request_id: UUID) -> bool
await store.exists(request_id: UUID) -> bool
```

---

## HITL Models

### `HumanReviewRequest`

```
from daf.models.human_review import HumanReviewRequest, GatedTaskDetail
```

```python
request = HumanReviewRequest.create(
    grant_id=grant.grant_id,
    request_id=workflow_request.request_id,
    tenant_id="acme",
    user_id="alice",
    gated_tasks=[...],
    timeout_seconds=3600,
    workflow_task="Analyse contracts",
)

request.review_id           # UUID
request.gated_task_ids      # list[str]
request.task_count          # int
request.is_expired          # bool
request.expires_at          # datetime
```

### `HumanReviewResponse`

```
from daf.models.human_review import HumanReviewResponse, TaskDecision
```

```python
# Constructors
HumanReviewResponse.approved_all(review_id, grant_id, reviewer_id, task_ids)
HumanReviewResponse.rejected_all(review_id, grant_id, reviewer_id, task_ids, reason)
HumanReviewResponse.timeout_response(review_id, grant_id, task_ids)

# Custom
HumanReviewResponse(
    review_id=..., grant_id=..., reviewer_id="alice",
    task_decisions=[
        TaskDecision(task_id="ST-03", decision="approved"),
        TaskDecision(task_id="ST-05", decision="rejected", reason="..."),
    ]
)

# Methods
response.is_fully_approved()         # bool
response.has_rejections()            # bool
response.approved_task_ids()         # list[str]
response.rejected_task_ids()         # list[str]
response.decision_for("ST-03")       # TaskDecision | None
response.timed_out                   # bool
```

---

## Built-in Test Helpers

### `StubTool`

```
from daf.tools.stub_tool import StubTool
```

```python
tool = StubTool(
    name="read_db",
    idempotent=True,
    output={"rows": [...]},   # returned on success
    should_fail=False,
    error="DB unavailable",   # returned when should_fail=True
)
result = await tool.call(query="SELECT 1")
print(tool.calls)             # list of call kwargs for inspection
tool.reset()                  # clear call history
```

### `StubAgent`

```
from daf.agents.stub_agent import StubAgent
```

```python
class MyTestAgent(StubAgent):
    role = "analyst"
    def __init__(self):
        super().__init__(
            role="analyst",
            output={"result": "extracted data"},
            cost_usd=0.02,
            should_fail=False,
        )

print(agent.runs)   # list of run records for inspection
agent.reset()       # clear run history
```

### `StubHumanReviewGateway`

```
from daf.runtime.human_review_gateway import StubHumanReviewGateway
```

```python
gateway = StubHumanReviewGateway(
    approve_all=True,        # always approve
    approve_all=False,       # always reject
    simulate_timeout=True,   # simulate timeout
)
gateway.set_next_response(my_response)  # custom response for next call
gateway.requests                        # list of received requests
gateway.reset()
```

---

## `FinalResponse`

```
from daf.models.final_response import FinalResponse
```

Returned by `GovernedAgenticLoop.run()` for all non-exception outcomes.

```python
result.request_id         # UUID
result.outcome            # "completed" | "partial" | "escalated" | "invalid_input"
result.loop_iterations    # int
result.total_cost_usd     # float
result.result             # list[dict] | None — step summaries on completion
result.escalation_context # dict | None — on escalation or invalid_input
result.audit_summary      # dict — event counts if AuditStore configured
```

---

## Exceptions

| Exception | Module | Raised When |
|---|---|---|
| `InputValidationError` | `input_processor` | Invalid `raw_request` field |
| `LLMClientError` | `llm_client` | LLM API call failed |
| `LLMOutputError` | `llm_client` | Schema validation failed after retries |
| `ToolNotFoundError` | `tool` | Tool not in registry or not in ScopedContext |
| `ToolCallError` | `tool` | Tool infrastructure failure |
| `ToolAlreadyRegisteredError` | `tool_registry` | Duplicate tool registration |
| `AgentNotFoundError` | `agent` | Role not in AgentRegistry |
| `AgentAlreadyRegisteredError` | `agent` | Duplicate role registration |
| `AgentExecutionError` | `agent` | Unexpected error in agent.execute() |
| `ExecutionError` | `execution_orchestrator` | Unresolvable dependency or infrastructure failure |
| `AuditStoreError` | `audit_store` | Write or query failure |
| `CheckpointStoreError` | `checkpoint_store` | Save, load, or delete failure |

---

## PolicyMatrix YAML Reference

```yaml
version: "1.0.0"
tenant_id: "your-org"
effective: "2026-01-01T00:00:00Z"

agent_roles:
  analyst:
    permitted_tools:        ["read_db", "llm_extraction"]
    permitted_data_sources: ["documents"]
    permitted_task_types:   ["llm_extraction", "deterministic"]
    max_llm_calls_per_step: 5

budget_policy:
  max_cost_per_call_usd:       0.02
  max_cost_per_step_usd:       0.10
  max_cost_per_workflow_usd:   0.50

compliance_rules:
  - rule_ref: "DATA-PII-001"
    condition:
      field:    "data_required"   # task field to check
      operator: "contains"        # contains | equals | in_list
      value:    "pii_data"
    action: block                 # block | warn | require_human_gate
    remediation_hint: "Route PII through approved pipeline"

risk_policy:
  irreversible_min_confidence:   0.90
  always_gate_action_classes:    ["send_email", "delete_record"]
  auto_approve_action_classes:   ["read_only", "llm_extraction"]

loop_policy:
  max_replan_attempts: 3
  max_duration_s: 300
```

**Condition fields available:** `task_id`, `task_type`, `agent_required`,
`tools_required`, `data_required`, `reversible`, `estimated_cost`

**Condition operators:**
- `contains` — list field contains the value
- `equals` — string field equals the value
- `in_list` — string field is in the values list

---

*DAF is a TonyOS Lab open-source project — tonyos-lab.org*
*Apache License 2.0 — github.com/tonyos-lab/daf*

---

## daf.testing

> **Import in tests and development only. Never in production code.**

```
from daf.testing import MockLLMClient, FixturePlanBuilder
```

### `MockLLMClient`

Drop-in replacement for `AnthropicLLMClient`. Returns developer-provided
plan dicts without making any API calls.

```python
# Single fixed response
client = MockLLMClient(responses=[plan_dict])

# Multiple responses in sequence (re-plan scenario)
client = MockLLMClient(responses=[forbidden_plan, valid_plan])

# Callable — full control per call
client = MockLLMClient(responses=[
    lambda system, user: my_plan if "contracts" in user else other_plan
])

# Simulate LLM failure after N calls
client = MockLLMClient(responses=[plan], fail_after=1)

# Constructor parameters
MockLLMClient(
    responses:     list[dict | callable] = [],
    model:         str   = "mock-model",
    fail_after:    int | None = None,   # None = never fail
    input_tokens:  int   = 400,
    output_tokens: int   = 250,
    cost_per_call: float = 0.0,
)

# Inspection
client.call_count       # int — number of complete() calls
client.calls            # list[tuple[str, str]] — (system, user) per call
client.reset()          # clear call history
```

### `FixturePlanBuilder`

Fluent builder for valid `PlanProposal` dicts. Use with `MockLLMClient`.

```python
plan = (FixturePlanBuilder()
    .with_task(
        task_id        = "ST-01",
        agent          = "analyst",        # must exist in AgentRegistry
        tools          = ["read_db"],      # must be in PolicyMatrix permissions
        task_type      = "llm_extraction", # see VALID_TASK_TYPES
        data_sources   = ["documents"],
        depends_on     = [],
        estimated_cost = 0.02,
        reversible     = True,
        rationale      = "Read contracts",
        name           = "read_contracts",
    )
    .with_task("ST-02", agent="analyst", tools=["llm_extraction"],
               depends_on=["ST-01"])
    .with_rationale("Read documents then extract features")
    .with_confidence(0.92)          # 0.0–1.0, default 0.90
    .with_orchestrator("default_orchestrator")
    .with_human_gate(False)         # default False
    .build()                        # → dict
)

client = MockLLMClient(responses=[plan])
```

**`VALID_TASK_TYPES`:**
```python
"deterministic"       # no LLM, pure computation
"llm_classification"  # classify input into categories
"llm_extraction"      # extract structured data from text
"llm_summarization"   # summarise content
"llm_transformation"  # transform content format
"llm_generation"      # generate new content
"llm_evaluation"      # evaluate or score content
```

### Switching Between Real and Mock

```python
import os

def make_llm_client(mock: bool = False):
    if mock:
        from daf.testing import MockLLMClient, FixturePlanBuilder
        plan = FixturePlanBuilder()\\
            .with_task("ST-01", agent="analyst", tools=["read_db"])\\
            .build()
        return MockLLMClient(responses=[plan])
    else:
        from daf.runtime.anthropic_client import AnthropicLLMClient
        return AnthropicLLMClient(api_key=os.getenv("LLM_API_KEY"))

# Identical loop constructor — only llm_client differs
loop = GovernedAgenticLoop(
    llm_client=make_llm_client(mock=True),
    policy_matrix="policy/matrix/prod.yaml",
    agent_registry=...,
    tool_registry=...,
)
```

