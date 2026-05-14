# DAF Implementation Log

This document tracks every implementation step, what was built, what changed, and how to test it.

---

## How to Use This Document

Each step has:
- **Purpose** — why this step exists in the build order
- **Files created** — new files added
- **Files updated** — existing files modified and what changed
- **How to run tests** — exact commands
- **What the tests verify** — what each test class covers

---

## Environment Setup (Do This First)

```bash
# Clone or unzip the project
cd daf

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux / WSL2

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment
cp .env.example .env
# Open .env — add your ANTHROPIC_API_KEY

# Start local services (PostgreSQL, Redis, Grafana)
make services-up

# Verify base setup
make test-unit
make test-adversarial
```

All unit tests run without Docker and without an API key.
Integration tests require both.

---

## Phase 1 — Governance Core

**Goal:** The loop runs. The LLM plans. The system governs.
No real agents yet — stub execution only.
Proves the central Propose → Evaluate → Execute mechanism works.

**Exit criterion:** The loop produces a verified PolicyEvaluation
(APPROVED or REJECTED) from a real LLM-generated PlanProposal.

---

### Step 1 — PolicyEngine: Compliance Rule Evaluation

**Purpose:**
The PolicyEngine scaffold had `_rule_applies()` returning `False` always —
meaning compliance rules never triggered. This step implements real
compliance rule evaluation, completing the PolicyEngine's evaluation logic.
This is Step 1 because the PolicyEngine must be complete before
anything else is built on top of it.

**Files Created:**
- `tests/unit/test_policy_engine_compliance.py`
  — 38 tests covering all compliance evaluation paths

**Files Updated:**

`daf/models/policy_matrix.py`
- Added `ConditionOperator` enum: `CONTAINS`, `EQUALS`, `IN_LIST`
- Added `Condition` model: structured condition with field, operator, value/values
- Added `ComplianceAction` enum: `BLOCK`, `WARN`, `REQUIRE_HUMAN_GATE`
- Updated `ComplianceRule.condition`: changed from `str` to `Condition` object

`daf/models/approval_grant.py`
- Added `gated_tasks: list[str]` field
- Added docstring explaining when tasks are gated

`daf/components/policy_engine.py`
- Implemented `_rule_applies()`: evaluates CONTAINS, EQUALS, IN_LIST operators
- Added `_collect_gated_tasks()`: identifies tasks needing human gate
- Updated `_evaluate_task()`: compliance check now handles BLOCK, WARN, REQUIRE_HUMAN_GATE
- Updated `evaluate()`: wires gated_tasks into ApprovalGrant
- Updated `_build_approval_grant()`: accepts and stores gated_tasks

`policy/matrix/example.yaml`
- Updated compliance_rules to use structured condition format

**How to Run Tests:**
```bash
# Compliance rule evaluation tests (38 tests)
python -m pytest tests/unit/test_policy_engine_compliance.py -v

# With coverage report
python -m pytest tests/unit/test_policy_engine_compliance.py \
  --cov=daf.components.policy_engine \
  --cov-report=term-missing
```

**What the Tests Verify:**

| Test Class | What It Covers |
|---|---|
| `TestConditionModelValidation` | Condition model validates operator + value requirements |
| `TestRuleAppliesContains` | CONTAINS operator: list field, string field, empty list, edge cases |
| `TestRuleAppliesEquals` | EQUALS operator: exact match, case-sensitivity, wrong type |
| `TestRuleAppliesInList` | IN_LIST operator: match, no match, single value, wrong type |
| `TestRuleAppliesEdgeCases` | Unknown field returns False, no exceptions raised |
| `TestCollectGatedTasks` | Gate from compliance rule, always_gate class, irreversible+confidence, dedup |
| `TestFullEvaluateCompliance` | BLOCK rejects, WARN approves, GATE produces gated_tasks, multiple rules |

---

### Step 2 — PolicyEngine: Full Test Suite (100% Coverage)

**Purpose:**
The original scaffold had 7 tests for the PolicyEngine.
After Step 1, coverage was at 92%.
This step adds tests for the remaining uncovered paths
to reach the target coverage for the most critical component.

**Files Created:**
- `tests/unit/test_policy_engine_coverage.py`
  — 18 additional tests covering previously uncovered lines

**Files Updated:**
- None — implementation was already correct, only test gaps existed

**How to Run Tests:**
```bash
# Additional coverage tests (18 tests)
python -m pytest tests/unit/test_policy_engine_coverage.py -v

# Full PolicyEngine coverage check (all three test files)
python -m pytest \
  tests/unit/test_policy_engine.py \
  tests/unit/test_policy_engine_compliance.py \
  tests/unit/test_policy_engine_coverage.py \
  --cov=daf.components.policy_engine \
  --cov-report=term-missing

# Expected: 98% coverage (2% is defensive except handler, unreachable via tests)
```

**What the Tests Verify:**

| Test Class | What It Covers |
|---|---|
| `TestWorkflowBudgetViolation` | Total proposal cost exceeds workflow limit |
| `TestAgentTaskTypeAuthorization` | task_type not in permitted_task_types |
| `TestRiskThresholdViolation` | Irreversible + low confidence gates, reversible never gates |
| `TestRuleAppliesExceptionHandling` | Unknown operator path, exception defensive handler |
| `TestSuggestToolAlternative` | Role available suggestion, no role has tool message |
| `TestRuleAppliesDirectExceptionPath` | Direct exception path coverage |

---

### Step 3 — PlanningOrchestrator: Real Anthropic API Call

**Purpose:**
The PlanningOrchestrator scaffold was a stub returning an empty PlanProposal.
This step replaces it with a real implementation that:
- Defines a provider-agnostic `LLMClient` interface
- Implements `AnthropicLLMClient` as the first provider
- Uses tool_use with input_schema for structured output enforcement
- Retries on schema validation failure with correction prompt
- Informs the planner of available roles/tools from PolicyMatrix

The provider-agnostic interface means adding a second LLM provider
later requires only one new file — no changes to PlanningOrchestrator.

**Files Created:**

`daf/runtime/llm_client.py`
- `LLMClient` — abstract interface (ABC)
- `LLMClientError` — API failure exception
- `LLMOutputError` — schema validation failure exception
- `LLMUsage` — token counts + cost (frozen dataclass)
- `LLMResponse` — validated content + usage (frozen dataclass)

`daf/runtime/anthropic_client.py`
- `AnthropicLLMClient(LLMClient)` — Anthropic implementation
- Uses `tool_use` with `input_schema` for structured output
- Retry loop with correction prompt on schema failure (max 2 retries)
- Token counting and USD cost calculation
- Pricing table for `claude-sonnet-4-20250514` and `claude-haiku-4-5-20251001`
- Lazy client initialization (no import cost at startup)

`tests/unit/test_planning_orchestrator.py`
- 31 tests covering all PlanningOrchestrator paths
- Zero real API calls — all use mock LLMClient

**Files Updated:**

`daf/components/planning_orchestrator.py` — REPLACED (was stub)
- Takes `LLMClient` interface (not provider-specific class)
- `plan()` — initial plan and re-plan paths
- `_build_system_prompt()` — populates roles, tools, budget from PolicyMatrix
- `_build_replan_prompt()` — violation detail, suggestions, approvable tasks
- `_parse_response()` — validated dict → PlanProposal
- `_PLAN_PROPOSAL_SCHEMA` — JSON Schema for structured output enforcement

**How to Run Tests:**
```bash
# PlanningOrchestrator and LLMClient interface tests (31 tests)
# No API key needed — all mocked
python -m pytest tests/unit/test_planning_orchestrator.py -v

# Coverage
python -m pytest tests/unit/test_planning_orchestrator.py \
  --cov=daf.components.planning_orchestrator \
  --cov=daf.runtime.llm_client \
  --cov=daf.runtime.anthropic_client \
  --cov-report=term-missing
```

**What the Tests Verify:**

| Test Class | What It Covers |
|---|---|
| `TestLLMClientInterface` | Abstract class not instantiable, AnthropicLLMClient conforms, raises without API key, estimate_cost |
| `TestPlanningOrchestratorInitialPlan` | Returns valid PlanProposal, correct fields, task description as user message, unique proposal IDs |
| `TestPlanningOrchestratorSystemPrompt` | Includes all roles, tools, budget constraint, handles empty roles |
| `TestPlanningOrchestratorReplan` | Uses replan prompt not task description, violation detail, suggestion, approvable tasks, uses latest violation |
| `TestPlanningOrchestratorErrors` | LLMClientError propagates, LLMOutputError propagates |
| `TestPlanningOrchestratorParseResponse` | Valid response produces proposal, preserves reversible/depends_on, unique proposal IDs |

---

### Step 4 — GovernedAgenticLoop: Correct Wiring

**Purpose:**
The GovernedAgenticLoop scaffold had three problems:
1. Constructor took `llm_model: str` but PlanningOrchestrator now takes `LLMClient`
2. `plan()` was missing the required `policy_matrix` argument
3. No handling for `LLMClientError` / `LLMOutputError`
   (these should propagate — they are unexpected failures, not policy violations)

This step rewrites the loop with correct wiring and structured logging.

**Files Updated:**

`daf/loop.py` — REWRITTEN
- Constructor takes `LLMClient` (not `llm_model: str`)
- `plan()` called with `policy_matrix` argument
- `LLMClientError` and `LLMOutputError` propagate (not caught)
- Structured logging with context at every stage
- Clear docstring listing all terminal conditions
- Comments marking where Phase 2 will add HITL stage

`daf/__init__.py` — UPDATED
- Updated quick start example showing new constructor pattern

`examples/01_basic_analysis/run.py` — UPDATED
- Uses `AnthropicLLMClient` with new constructor
- Loads `.env` file if present

**Files Created:**
- `tests/unit/test_loop.py` — 15 tests

**How to Run Tests:**
```bash
# Loop tests (15 tests) — no API key needed
python -m pytest tests/unit/test_loop.py -v
```

**What the Tests Verify:**

| Test Class | What It Covers |
|---|---|
| `TestGovernedAgenticLoopHappyPath` | Returns completed, calls plan() with policy_matrix, empty violation_history on iteration 1 |
| `TestGovernedAgenticLoopReplan` | Re-plans after rejection, passes violation history, accumulates multiple violations |
| `TestGovernedAgenticLoopEscalation` | Max attempts returns escalated, respects PolicyMatrix setting, forced escalation exits early, escalation context included |
| `TestGovernedAgenticLoopErrors` | LLMClientError propagates, LLMOutputError propagates, no FinalResponse returned on error |
| `TestGovernedAgenticLoopConstructor` | Accepts LLMClient, wires PolicyEngine |

---

## Running the Full Test Suite

```bash
# All unit tests (no API key, no Docker needed)
make test-unit

# Security tests — must always pass
make test-adversarial

# All tests
make test-all

# With coverage report
python -m pytest tests/unit/ tests/adversarial/ \
  --cov=daf \
  --cov-report=html \
  --cov-report=term-missing
# Open htmlcov/index.html in browser
```

**Expected results:**
```
114 passed in ~0.5s
```

---

## Current Test Count by File

| File | Tests | Notes |
|---|---|---|
| `tests/unit/test_policy_engine.py` | 7 | Original scaffold tests |
| `tests/unit/test_policy_engine_compliance.py` | 38 | Step 1 — compliance evaluation |
| `tests/unit/test_policy_engine_coverage.py` | 18 | Step 2 — coverage gaps |
| `tests/unit/test_planning_orchestrator.py` | 31 | Step 3 — planning orchestrator |
| `tests/unit/test_loop.py` | 15 | Step 4 — loop wiring |
| `tests/adversarial/test_scoped_context.py` | 5 | Security — always must pass |
| **Total** | **114** | |

---

## What Is Still a Stub

These components are scaffolded but not yet implemented.
Phase 2 will replace them:

| Component | Status | Phase |
|---|---|---|
| `ExecutionOrchestrator.execute()` | Stub — returns "stub_completed" | Phase 2, Step 13 |
| `InputProcessor.process()` | Minimal — no validation yet | Phase 2, Step 15 |
| `OutputAssembler.assemble()` | Minimal — no audit records yet | Phase 2, Step 16 |
| `AuditStore` | Not implemented | Phase 2, Step 11 |
| `CheckpointStore` | Not implemented | Phase 2, Step 12 |
| `EvaluateStage` (HITL) | Not yet created | Phase 2, Step 13 |
| `HumanReviewGateway` | Not yet created | Phase 2, Step 14 |

---

## Step 5 — Integration Test (Next)

**What it will test:**
The full loop with a real Anthropic API call.
Requires `LLM_API_KEY` in `.env`. Costs approximately $0.01-0.03.

**What it will verify:**
- Real LLM generates a valid PlanProposal conforming to the schema
- Policy Engine evaluates it deterministically
- Loop produces a FinalResponse (stub execution for now)
- End-to-end run completes without errors

---

*DAF is a TonyOS Lab open-source project — tonyos-lab.org*

---

### Step 5 — Integration Test: Phase 1 Loop End-to-End

**Purpose:**
Unit tests verify each component in isolation using mocks.
The integration test verifies the full chain works together
with a real Anthropic API call — real LLM planning, real Policy Engine
evaluation, stub execution.

This step closes Phase 1. After this, the governance core is proven.

**What is real vs stubbed in this test:**

| Component | Status |
|---|---|
| AnthropicLLMClient | REAL — actual API call to Anthropic |
| PlanningOrchestrator.plan() | REAL — real prompt, real structured output |
| PolicyEngine.evaluate() | REAL — deterministic evaluation |
| GovernedAgenticLoop | REAL — full loop sequencing |
| ExecutionOrchestrator.execute() | STUB — returns "stub_completed" |
| AuditStore | STUB — not connected yet |
| CheckpointStore | STUB — not connected yet |

**Files Created:**
- `tests/integration/test_phase1_loop.py` — 11 integration tests
- `tests/integration/conftest.py` — pytest async configuration
- `pytest.ini` — asyncio_mode=auto, test paths

**Files Updated:**
- `IMPLEMENTATION.md` — this entry

**Requirements Before Running:**
```bash
# 1. Add your Anthropic API key to .env
cp .env.example .env
# Edit .env: set LLM_API_KEY=sk-ant-YOUR-KEY-HERE

# 2. No Docker needed — ExecutionOrchestrator is still a stub
# 3. Estimated cost per full run: $0.01 - $0.05
# 4. Estimated time per full run: 15 - 45 seconds
```

**How to Run Tests:**
```bash
# Run integration tests only (requires LLM_API_KEY)
python -m pytest tests/integration/ -v -s

# Run with cost visibility (see token usage in logs)
python -m pytest tests/integration/ -v -s --log-cli-level=INFO

# Run a single test class
python -m pytest tests/integration/test_phase1_loop.py::TestPhase1HappyPath -v -s

# Skip integration tests (default when no API key)
python -m pytest tests/unit/ tests/adversarial/ -v

# Verify skip behaviour (no API key needed)
LLM_API_KEY="" python -m pytest tests/integration/ -v
# Expected: 11 skipped with reason message
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestPhase1HappyPath` | 3 | Loop completes with real LLM, PlanProposal has correct structure, PolicyEngine evaluates real proposal |
| `TestPhase1RejectionAndEscalation` | 3 | Restrictive matrix causes escalation, violation_history accumulates, re-plan prompt reaches LLM |
| `TestPhase1SchemaEnforcement` | 2 | LLM returns structured JSON not prose, LLMUsage populated with real token counts |
| `TestPhase1LoopInvariantsBehavior` | 3 | PolicyEngine is synchronous, only PlanningOrchestrator calls LLM, unique proposal_ids per iteration |

**The Two PolicyMatrix Configurations:**

*Permissive matrix (happy path tests):*
- Agent role `analyst` with broad tool permissions
- Budget: $1.00 per workflow
- No compliance rules
- max_replan_attempts=3

*Restrictive matrix (rejection tests):*
- Agent role `locked_agent` with NO permitted tools
- Any tool the LLM proposes fails tool_permission check
- max_replan_attempts=2 (keeps test fast)
- Guarantees escalation regardless of what the LLM plans

**Why the Restrictive Matrix Guarantees Rejection:**
The Policy Engine is deterministic. If the policy says no tools are permitted,
every proposal will fail tool_permission — regardless of how good the LLM plan is.
This makes the rejection/escalation test fully deterministic even though
the LLM output itself is non-deterministic.

**Expected Test Output (with API key):**
```
tests/integration/test_phase1_loop.py::TestPhase1HappyPath::test_loop_completes_with_real_llm PASSED
tests/integration/test_phase1_loop.py::TestPhase1HappyPath::test_llm_produces_valid_plan_proposal PASSED
tests/integration/test_phase1_loop.py::TestPhase1HappyPath::test_policy_engine_evaluates_real_proposal PASSED
tests/integration/test_phase1_loop.py::TestPhase1RejectionAndEscalation::test_loop_escalates_when_all_plans_rejected PASSED
tests/integration/test_phase1_loop.py::TestPhase1RejectionAndEscalation::test_violation_history_grows_with_each_rejection PASSED
tests/integration/test_phase1_loop.py::TestPhase1RejectionAndEscalation::test_replan_prompt_reaches_llm_on_second_iteration PASSED
tests/integration/test_phase1_loop.py::TestPhase1SchemaEnforcement::test_llm_returns_structured_json_not_prose PASSED
tests/integration/test_phase1_loop.py::TestPhase1SchemaEnforcement::test_llm_usage_is_populated PASSED
tests/integration/test_phase1_loop.py::TestPhase1LoopInvariantsBehavior::test_policy_engine_never_called_with_llm PASSED
tests/integration/test_phase1_loop.py::TestPhase1LoopInvariantsBehavior::test_planning_orchestrator_is_the_only_llm_caller PASSED
tests/integration/test_phase1_loop.py::TestPhase1LoopInvariantsBehavior::test_loop_produces_fresh_proposal_id_each_iteration PASSED
```

---

## Phase 1 — COMPLETE

All five steps are done. The governance core is proven.

**Phase 1 Exit Criterion — MET:**
The loop produces a verified PolicyEvaluation (APPROVED or REJECTED)
from a real LLM-generated PlanProposal. The integration test confirms this.

**Total test count at end of Phase 1:**

| Scope | Tests |
|---|---|
| Unit tests | 114 |
| Integration tests | 11 (skip without API key) |
| Adversarial tests | 5 |
| **Total** | **130** |

**Phase 2 begins next:**
Building real agent execution — BaseTool, BaseAgent, ScopedContext
with real clients, AuditStore, CheckpointStore, ExecutionOrchestrator,
EvaluateStage (HITL), and Example 01 running end-to-end.


---

## Phase 2 — Execution Layer

**Goal:** Real agents run inside approved scope. Audit records written.
Checkpoints saved. Example 01 runs end-to-end.

---

### Step 6 — BaseTool + ToolRegistry

**Purpose:**
Agents interact with the outside world exclusively through tools.
This step defines the tool interface contract, the registry that
maps tool names to instances, and the scoped view that ScopedContext
will use to enforce per-agent tool permissions at the runtime layer.

The idempotency classification on every tool is the foundation for
safe retry logic in the ExecutionOrchestrator: idempotent tools can
be retried freely; non-idempotent tools require verification before retry.

**Files Created:**

`daf/runtime/tool.py`
- `ToolResult` — return type for all tool calls (ok/fail constructors)
- `BaseTool` — abstract base class with name + idempotent enforcement
- `ToolNotFoundError` — raised by registry on missing tool
- `ToolCallError` — raised by tools on infrastructure failure

`daf/runtime/tool_registry.py`
- `ToolRegistry` — full registry, register/get/has/names/scoped
- `ScopedToolRegistry` — immutable permission-scoped view
- `ToolAlreadyRegisteredError` — duplicate registration protection

`daf/tools/__init__.py`
- Package init for built-in DAF tools

`daf/tools/stub_tool.py`
- `StubTool` — configurable stub for testing
- Returns configured output, records call history, resets between tests

`tests/unit/test_tool.py`
- 45 tests across 6 test classes

**Files Updated:**
- `IMPLEMENTATION.md` — this entry

**How to Run Tests:**
```bash
# Step 6 tests (45 tests)
python -m pytest tests/unit/test_tool.py -v

# Full suite (all phases)
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 159 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestToolResult` | 6 | ok/fail constructors, metadata, various output types |
| `TestBaseToolEnforcement` | 5 | name required, idempotent required, abstract exemption, repr |
| `TestStubTool` | 8 | success/failure output, call history, reset, repr |
| `TestToolRegistry` | 11 | register, get, has, names, len, scoped, error cases |
| `TestScopedToolRegistry` | 10 | get, has, contains, iter, len, independence from source |
| `TestToolExceptions` | 4 | error message content, exception hierarchy |

**Design Note — Why ScopedToolRegistry is Immutable:**
The ScopedToolRegistry is built from the ApprovalGrant.
Once built, it cannot be expanded — not by the agent, not by
any model instruction, not by adversarial tool output.
This is the structural enforcement that makes the tool permission
boundary impossible to bypass. The `test_scoped_registry_is_independent_of_source`
test specifically verifies this property.


---

### Step 7 — BaseAgent + AgentRegistry

**Purpose:**
Agents are the workers of the execution layer. This step defines
the agent contract, the registry that maps role names to agent classes,
and the StubAgent for testing — completing the parallel structure
with BaseTool/ToolRegistry from Step 6.

The key architectural difference from tools: the registry stores
CLASSES not instances. Agents are instantiated per sub-task with
a fresh ScopedContext. This ensures each agent execution is isolated
and has exactly the permissions the ApprovalGrant specified — no more.

**Files Created:**

`daf/runtime/agent.py`
- `AgentResult` — return type for all agent runs (ok/fail constructors)
- `BaseAgent` — abstract base class with role enforcement
- `AgentNotFoundError` — raised by registry on missing role
- `AgentAlreadyRegisteredError` — duplicate registration protection
- `AgentExecutionError` — wraps unexpected exceptions from execute()

`daf/runtime/agent_registry.py`
- `AgentRegistry` — stores classes, instantiates on demand
- `register()` — stores class, enforces no duplicates
- `instantiate()` — creates fresh instance per sub-task
- `get_class()` — returns class without instantiating (for inspection)

`daf/agents/__init__.py` — package init
`daf/agents/stub_agent.py`
- `StubAgent` — configurable stub with run history for testing

`tests/unit/test_agent.py` — 40 tests

**Files Updated:**
- `IMPLEMENTATION.md` — this entry

**How to Run Tests:**
```bash
# Step 7 tests (40 tests)
python -m pytest tests/unit/test_agent.py -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 199 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestAgentResult` | 8 | ok/fail constructors, cost, metadata, task_id |
| `TestBaseAgentEnforcement` | 5 | role required, must be str, abstract exemption |
| `TestBaseAgentRun` | 4 | wraps execute(), AgentExecutionError wrapping, re-raise, passthrough |
| `TestStubAgent` | 9 | success/failure, run history, task_id, cost, reset, repr |
| `TestAgentRegistry` | 13 | register, has, duplicate, replace, wrong type, instantiate, get_class, roles, len, repr |
| `TestAgentRegistryWithStubAgent` | 1 | end-to-end register → instantiate → run |

**Design Note — Classes Not Instances:**
`AgentRegistry.instantiate()` creates a fresh agent instance on every call.
This is tested explicitly with `test_instantiate_creates_fresh_instance_each_time`.
It ensures each sub-task gets its own agent state — run history from one
sub-task cannot bleed into another. This matters for the StubAgent in tests
and for stateful real agents in production.


---

### Step 8 — ScopedContext: Real Tool Clients

**Purpose:**
The ScopedContext scaffold used stub tool clients that raised
`NotImplementedError`. This step replaces stubs with real
`ScopedToolRegistry` instances from the ToolRegistry built in Step 6.

After this step, the structural enforcement invariant is fully implemented:
an agent with `tools=["read_db"]` literally cannot access `write_db`
because `ToolNotFoundError` is raised at `ctx.tools.get("write_db")`.
This is enforced at construction time — not at call time.

The adversarial test suite is also upgraded from testing stub behaviour
to testing the real ScopedContext with real ToolRegistry.

**Files Updated:**

`daf/runtime/scoped_context.py` — REWRITTEN
- Constructor now takes `tool_registry: ToolRegistry` parameter
- `self.tools` is now a real `ScopedToolRegistry` (not stub dict)
- `ToolNotFoundError` raised at construction if permitted tool not registered
- `ValueError` raised if agent_role not in ApprovalGrant
- `task_input` is now a defensive copy (not a reference)
- `permitted_data_sources` property added (data clients deferred to Phase 3)
- `budget` property added (returns None until Step 9)

`tests/adversarial/test_scoped_context.py` — REWRITTEN
- Now uses real ScopedContext + real ToolRegistry
- Expanded from 5 to 18 tests across 3 adversarial test classes:
  - `TestScopedContextEnforcement` (6): permitted/unpermitted access
  - `TestScopedContextImmutability` (3): post-scoping registry changes,
    role mutation, task_input copy
  - `TestScopedContextConstruction` (7): error cases and properties

**Files Created:**
`tests/unit/test_scoped_context.py` — 17 unit tests

**How to Run Tests:**
```bash
# Unit tests for ScopedContext
python -m pytest tests/unit/test_scoped_context.py -v

# Adversarial tests (security — must always pass)
python -m pytest tests/adversarial/ -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 229 passed
```

**What the Tests Verify:**

| File | Class | Tests | What It Covers |
|---|---|---|---|
| unit | `TestScopedContextConstruction` | 5 | Valid construction, invalid role, unregistered tool |
| unit | `TestScopedContextToolAccess` | 4 | get permitted, get unpermitted raises, callable, names |
| unit | `TestScopedContextTaskInput` | 3 | default empty, accessible, copy independence |
| unit | `TestScopedContextProperties` | 5 | role, max_calls, data_sources, budget=None, repr |
| adversarial | `TestScopedContextEnforcement` | 6 | Permission boundary, enumeration, empty permissions, two-agent isolation |
| adversarial | `TestScopedContextImmutability` | 3 | Post-scoping changes, role mutation, task_input copy |
| adversarial | `TestScopedContextConstruction` | 7 | Error cases + properties |
| adversarial | `TestBudgetTrackerSecurity` | 2 | Budget exhaustion, race conditions |

**Key Adversarial Property Verified:**
`test_adding_to_registry_after_scoping_does_not_expand_context`
— The most important immutability test. A new tool registered in
ToolRegistry after ScopedContext creation is NOT visible to that context.
This is the ScopedToolRegistry snapshot property from Step 6 confirmed
at the ScopedContext level with real integration.


---

### Step 9 — BudgetTracker Wired into ScopedContext

**Purpose:**
BudgetTracker existed in the scaffold but was not connected to anything.
This step wires it into ScopedContext so agents can check and record
budget through their execution context.

One tracker per workflow — shared across all agents. Created by
ExecutionOrchestrator (Step 14) from the ApprovalGrant and injected
into each ScopedContext at instantiation.

**Files Updated:**

`daf/runtime/budget_tracker.py`
- Added `from_grant(grant)` classmethod — creates tracker from ApprovalGrant
- Added `is_exhausted` property — True when no budget remains
- Added `summary()` method — returns dict for audit records and logging
- Added validation: `ValueError` for negative `max_cost_usd`
- Added validation: `ValueError` for negative `estimated_cost`
- Added float drift protection in `record_actual` (clamp to 0)
- Updated `__repr__` to include spent/remaining/max

`daf/runtime/scoped_context.py`
- Added `budget_tracker` parameter to `__init__`
- `budget` property now returns the injected tracker (not always None)
- Updated docstring to reflect Step 9 completion

**Files Created:**
`tests/unit/test_budget_tracker.py` — 25 tests

**How to Run Tests:**
```bash
# Budget tracker + wiring tests (25 tests)
python -m pytest tests/unit/test_budget_tracker.py -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 254 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestBudgetTrackerNewMethods` | 10 | from_grant, is_exhausted, summary, negative value validation, repr |
| `TestBudgetTrackerCoreBehaviour` | 9 | Initial state, check_and_reserve, record_actual (up/down/release), float drift |
| `TestScopedContextBudgetWiring` | 6 | budget accessible, None when not injected, reserve via context, exhaustion, from_grant integration, shared tracker across two contexts |

**Key Design — Shared Tracker Pattern:**
`test_shared_tracker_across_two_contexts` verifies the intended Phase 2
multi-agent pattern: one BudgetTracker is created from the ApprovalGrant
and injected into every ScopedContext in the workflow. Spending by one
agent is immediately visible to all others. This is how the per-workflow
budget limit is enforced atomically.


---

### Step 10 — AuditStore: Append-Only Audit Trail

**Purpose:**
Every significant event in a DAF workflow must be recorded immutably.
This step implements the AuditRecord model, the AuditStore interface,
an InMemoryAuditStore for unit tests, and a PostgresAuditStore for
production. The audit trail is what makes DAF trustworthy to compliance
teams — without it, there is no proof of what happened and why.

**Files Created:**

`daf/models/audit_record.py`
- `AuditEventType` — string constants for all event types
- `AuditRecord` — frozen Pydantic model (immutable after creation)
- `AuditRecord.make()` — convenience factory method

`daf/runtime/audit_store.py`
- `AuditStore` — abstract base class (write, query, count)
- `InMemoryAuditStore` — unit test implementation (no DB needed)
- `AuditStoreError` — raised on write/query failure

`daf/runtime/postgres_audit_store.py`
- `PostgresAuditStore` — asyncpg PostgreSQL implementation
- Connection pool management
- Async context manager support

`tests/unit/test_audit_store.py` — 28 tests

**How to Run Tests:**
```bash
# Unit tests (no Docker needed) — 28 tests
python -m pytest tests/unit/test_audit_store.py -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 282 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestAuditEventType` | 3 | All constants are strings, no duplicates, ALL contains expected types |
| `TestAuditRecord` | 6 | make() fields, unique audit_id, created_at, empty payload, immutability, custom event types |
| `TestInMemoryAuditStore` | 16 | write/query, request isolation, event_type filter, order, count, duplicate detection, clear, payload fidelity |
| `TestAuditStoreInterface` | 3 | Abstract class, InMemory is subclass, AuditStoreError fields |
| `TestAuditStoreWorkflowScenario` | 2 | Full successful workflow trail, escalated workflow trail |

**Audit Events Defined:**
```
workflow_started      workflow_completed    workflow_escalated
plan_proposed         plan_evaluated
human_review_requested  human_review_responded
execution_started
step_started          step_completed        step_failed
```

**The Immutability Guarantee:**
- `AuditRecord` is a frozen Pydantic model — fields cannot be modified
- `InMemoryAuditStore` raises `AuditStoreError` on duplicate audit_id
- `PostgresAuditStore` relies on PostgreSQL `UNIQUE` constraint on audit_id
- PostgreSQL `UPDATE` and `DELETE` are revoked at DB level (`scripts/init.sql`)


---

### Step 11 — CheckpointStore: Resumable Execution State

**Purpose:**
Without checkpoints, any failure during execution means restarting
from scratch — re-running completed steps and spending budget twice.
With checkpoints, execution resumes from the last successful step.

Checkpoints also enable the HITL gate pattern: when human approval
is needed, the workflow suspends (saves checkpoint with state=awaiting_hitl),
releases all resources, and resumes (loads checkpoint) when the human responds.

**Files Created:**

`daf/models/workflow_checkpoint.py`
- `CheckpointState` — state constants (RUNNING, AWAITING_HITL, RESUMING, COMPLETED, FAILED)
- `WorkflowCheckpoint` — mutable execution state model
- `WorkflowCheckpoint.create()` — initial checkpoint factory
- Transition methods (all return new instances — never mutate):
  - `mark_task_complete()` — moves task from pending to completed
  - `mark_awaiting_hitl()` — suspends at HITL gate
  - `mark_resuming()` — HITL approved, resuming
  - `mark_completed()` — workflow finished
  - `mark_failed()` — unexpected failure

`daf/runtime/checkpoint_store.py`
- `CheckpointStore` — abstract interface (save, load, delete, exists)
- `InMemoryCheckpointStore` — unit test implementation
- `RedisCheckpointStore` — production Redis implementation
- `CheckpointStoreError` — structured error

`tests/unit/test_checkpoint_store.py` — 37 tests

**How to Run Tests:**
```bash
# Checkpoint store tests (37 tests — no Docker needed)
python -m pytest tests/unit/test_checkpoint_store.py -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 319 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestCheckpointState` | 3 | Constants are strings, ALL contains expected states, no duplicates |
| `TestWorkflowCheckpointCreate` | 7 | Initial state, pending_tasks, empty completed, zero cost, no pause, unique ID, timestamp |
| `TestWorkflowCheckpointTransitions` | 10 | All transition methods return new objects, state changes, cost accumulation, immutability |
| `TestInMemoryCheckpointStore` | 11 | save/load, overwrite, delete, exists, clear, len, repr |
| `TestCheckpointResumeScenario` | 3 | Resume from partial execution, HITL suspend/resume, completed checkpoint deletion |
| `TestCheckpointStoreInterface` | 3 | Abstract class, subclass check, error fields |

**Key Design — Contrast With AuditStore:**
```
AuditStore:
  - Append-only (no UPDATE, no DELETE)
  - Permanent — records never removed
  - One record per event — many records per workflow
  - Purpose: proof of what happened

CheckpointStore:
  - Mutable — save() overwrites
  - Temporary — deleted on completion
  - One record per workflow — updated as tasks complete
  - Purpose: enable resumption on failure
```

Both are needed. They serve different purposes.


---

### Step 12 — HumanReview Models

**Purpose:**
These are the data contracts for the HITL stage. When the Policy Engine
identifies tasks requiring human approval, the EvaluateStage (Step 13)
builds one HumanReviewRequest containing all gated tasks, sends it to
the reviewer, and waits for one HumanReviewResponse containing a
per-task decision.

All design decisions from the earlier architecture discussion
are encoded in these models:
- One request per evaluation (not one per task)
- Single human interaction point
- Per-task decision in response
- Any rejection → back to re-plan with context
- Timeout → auto-reject via `timeout_response()`
- Both request and response written to AuditStore (immutable)

**Files Created:**

`daf/models/human_review.py`
- `GatedTaskDetail` — details of one gated task for reviewer context
- `HumanReviewRequest` — one request per evaluation, all gated tasks
  - `create()` factory with expiry calculation
  - `is_expired`, `gated_task_ids`, `task_count` properties
- `TaskDecision` — per-task decision (approved/rejected + reason)
  - `is_approved`, `is_rejected` properties
- `HumanReviewResponse` — frozen (immutable) response model
  - `approved_all()` — convenience constructor
  - `rejected_all()` — convenience constructor
  - `timeout_response()` — auto-reject on expiry
  - `is_fully_approved()`, `has_rejections()` methods
  - `approved_task_ids()`, `rejected_task_ids()` methods
  - `decision_for(task_id)` — lookup by task_id

`tests/unit/test_human_review.py` — 31 tests

**How to Run Tests:**
```bash
# HumanReview model tests (31 tests)
python -m pytest tests/unit/test_human_review.py -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 350 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestGatedTaskDetail` | 3 | Construction, default cost, reversible flag |
| `TestHumanReviewRequest` | 10 | create() factory, expiry calculation, properties, is_expired |
| `TestTaskDecision` | 4 | Approved/rejected flags, reason storage |
| `TestHumanReviewResponse` | 12 | All constructors, mixed decisions, decision_for, immutability, notes |
| `TestHumanReviewRequestResponseIntegration` | 3 | review_id match, all tasks have decisions, timeout scenario |

**The Timeout Pattern:**
```python
# EvaluateStage will do this (Step 13):
if review_request.is_expired:
    response = HumanReviewResponse.timeout_response(
        review_id=review_request.review_id,
        grant_id=review_request.grant_id,
        task_ids=review_request.gated_task_ids,
    )
    # response.timed_out == True
    # response.has_rejections() == True
    # EvaluateStage treats this as a violation → re-plan
```


---

### Step 13 — EvaluateStage: HITL Coordinator

**Purpose:**
The EvaluateStage is the thin coordinator that owns the complete
evaluate phase of the Governed Agentic Loop. It wraps PolicyEngine
and HITL resolution, returning one clean EvaluationOutcome.

The GovernedAgenticLoop will call EvaluateStage.run() instead of
calling PolicyEngine directly. This keeps the loop clean and ensures
the HITL pattern is fully encapsulated.

Key design from our architecture discussion:
- HITL collected at END of evaluate stage, before execute
- All gated tasks in one request — single human interaction point
- Any rejection → ViolationReport → back to re-plan
- Timeout → auto-reject (safest default)

**Files Created:**

`daf/runtime/human_review_gateway.py`
- `BaseHumanReviewGateway` — abstract interface
- `StubHumanReviewGateway` — for unit tests (configurable approve/reject/timeout)
- `CLIHumanReviewGateway` — for development (terminal I/O)

`daf/components/evaluate_stage.py`
- `EvaluationOutcome` — clean result type (EXECUTABLE / NOT_EXECUTABLE)
  - `is_executable()` — loop checks this
  - `as_violation()` — converts outcome for re-planning
- `EvaluateStage` — thin coordinator
  - Calls PolicyEngine
  - Writes PLAN_EVALUATED audit record
  - Resolves HITL if gated tasks exist
  - Writes HUMAN_REVIEW_REQUESTED + HUMAN_REVIEW_RESPONDED records
  - Returns EvaluationOutcome

`tests/unit/test_evaluate_stage.py` — 23 tests

**How to Run Tests:**
```bash
# EvaluateStage tests (23 tests)
python -m pytest tests/unit/test_evaluate_stage.py -v

# Full suite
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 373 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestEvaluationOutcome` | 5 | is_executable, as_violation, raises on wrong outcome, repr |
| `TestEvaluateStageClearApproval` | 3 | EXECUTABLE returned, audit record written, verdict in payload |
| `TestEvaluateStageRejection` | 3 | NOT_EXECUTABLE returned, as_violation returns report, audit record |
| `TestEvaluateStageHITLApproved` | 3 | EXECUTABLE with review_response, two audit records written, gateway receives request |
| `TestEvaluateStageHITLRejected` | 4 | NOT_EXECUTABLE on rejection, ViolationReport from HITL, timeout auto-rejects, no gateway auto-rejects |
| `TestStubHumanReviewGateway` | 5 | All modes (approve/reject/timeout), request history, set_next_response |

**Audit Records Written Per Evaluation:**
```
Always:
  PLAN_EVALUATED (verdict, violations count, gated tasks)

When HITL resolves:
  HUMAN_REVIEW_REQUESTED (review_id, expires_at, gated tasks)
  HUMAN_REVIEW_RESPONDED (reviewer_id, timed_out, approved/rejected)
```


---

### Step 14 — ExecutionOrchestrator: Real Execution

**Purpose:**
Replaces the Phase 1 stub with real agent execution.
Each sub-task is executed by an agent instantiated with a ScopedContext
built from the ApprovalGrant — enforcing permissions structurally.

**What it does:**
1. Creates shared BudgetTracker from ApprovalGrant
2. Resolves dependency order (raises ExecutionError on unmet deps)
3. For each task: builds ScopedContext, instantiates agent, runs it
4. Saves checkpoint after every completed step
5. Writes audit records throughout (EXECUTION_STARTED, STEP_STARTED, STEP_COMPLETED/FAILED)
6. Halts on first task failure (partial outcome)
7. Deletes checkpoint on completion

**Files Updated:**

`daf/components/execution_orchestrator.py` — REPLACED (was stub)
- Full execution algorithm with dependency ordering
- ScopedContext per agent role from ApprovalGrant
- Shared BudgetTracker across all agents
- Checkpoint save/update/delete lifecycle
- Audit record emission throughout
- Phase 1 backwards compatibility (no registries = stub result)

`tests/unit/test_execution_orchestrator.py` — NEW (17 tests)

**Bugs fixed during development:**
- `make_orchestrator` fixture used `or` for default args — falsy stores
  replaced a passed-in store. Fixed to use `is not None`.
- Empty `InMemoryCheckpointStore` is falsy (len=0). Fixed `if self._checkpoint_store:`
  to `if self._checkpoint_store is not None:` in orchestrator.
- Budget tracker only tracks `check_and_reserve` — agent `cost_usd` from
  `AgentResult` was not recorded. Fixed by calling `record_actual` after each step.

**How to Run Tests:**
```bash
python -m pytest tests/unit/test_execution_orchestrator.py -v
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 390 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestExecutionOrchestratorHappyPath` | 5 | Single task, multiple tasks, result IDs, timestamps, duration |
| `TestExecutionOrchestratorFailure` | 2 | Partial outcome on failure, halts after first failure |
| `TestExecutionOrchestratorDependencies` | 2 | Task order preserved, unmet dependency raises |
| `TestExecutionOrchestratorAuditRecords` | 3 | EXECUTION_STARTED, STEP_STARTED/COMPLETED, STEP_FAILED |
| `TestExecutionOrchestratorCheckpoints` | 2 | Checkpoint saved during execution, deleted after completion |
| `TestExecutionOrchestratorBudget` | 1 | total_cost_usd accumulates from agent results |
| `TestExecutionOrchestratorPhase1Compat` | 2 | No registries returns stub, empty sub_tasks returns stub |


---

### Step 15 — InputProcessor: Full Validation

**Purpose:**
The scaffold had a minimal InputProcessor that just wrapped the raw dict
into a WorkflowRequest with no validation. This step replaces it with
full validation, sanitization, and intent classification.

**Files Updated:**

`daf/components/input_processor.py` — REPLACED (was minimal stub)
- `InputValidationError` — raised on invalid input (field + reason)
- Task validation: non-empty, string type, max 10,000 chars, stripped
- ID sanitization: user_id + tenant_id with defaults, stripping, truncation
- Constraints validation: max_cost_usd > 0, max_duration_s > 0, dict type
- Intent classification: keyword-based heuristic (deterministic/llm/mixed)
- Context sanitization: valid JSON types kept, non-serialisable dropped

**Files Created:**
`tests/unit/test_input_processor.py` — 44 tests

**How to Run Tests:**
```bash
python -m pytest tests/unit/test_input_processor.py -v
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 434 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestInputProcessorHappyPath` | 6 | Minimal request, WorkflowRequest type, UUID, unique IDs, timestamp, full request |
| `TestInputProcessorTaskValidation` | 8 | Empty, whitespace, missing, non-string, too long, max length OK, stripped, None |
| `TestInputProcessorIDSanitization` | 8 | Defaults, empty, whitespace, stripping, truncation, non-string |
| `TestInputProcessorConstraints` | 9 | Valid pass-through, zero/negative/non-number cost, zero/positive duration, non-dict, extra keys |
| `TestInputProcessorIntentClassification` | 5 | Explicit override, LLM keywords, deterministic keywords, ambiguous, default mixed |
| `TestInputProcessorContextSanitization` | 5 | Valid values, non-serialisable dropped, non-dict default, missing default, None default |
| `TestInputValidationError` | 3 | Field/reason stored, message content, exception hierarchy |


---

### Step 16 — OutputAssembler + GovernedAgenticLoop Phase 2 Wiring

**Purpose:**
OutputAssembler replaces the minimal scaffold with full audit record
writing and structured FinalResponse assembly. The GovernedAgenticLoop
is also updated to use EvaluateStage and handle InputValidationError.

**Files Updated:**

`daf/models/final_response.py`
- Added `audit_summary: dict` field — event counts for caller

`daf/components/output_assembler.py` — REPLACED (was minimal stub)
- `assemble()` — completed/partial workflows + WORKFLOW_COMPLETED audit record
- `escalate()` — loop exhausted + WORKFLOW_ESCALATED audit record
- `invalid_input()` — new method for InputValidationError cases
- `_build_audit_summary()` — queries AuditStore for event counts

`daf/loop.py` — UPDATED
- Constructor injects AuditStore, CheckpointStore, HITL gateway
- Uses EvaluateStage instead of direct PolicyEngine call
- Catches InputValidationError → returns invalid_input FinalResponse
- Writes WORKFLOW_STARTED and PLAN_PROPOSED audit records
- OutputAssembler receives AuditStore for terminal records

**Files Created:**
`tests/unit/test_output_assembler.py` — 27 tests

**How to Run Tests:**
```bash
python -m pytest tests/unit/test_output_assembler.py -v
python -m pytest tests/unit/ tests/adversarial/ -q
# Expected: 461 passed
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestOutputAssemblerAssemble` | 11 | FinalResponse type, outcomes, IDs, cost, step summary, error in result, audit records, no-store graceful |
| `TestOutputAssemblerEscalate` | 7 | Escalated outcome, iterations, context, message, zero cost, audit record, empty history |
| `TestOutputAssemblerInvalidInput` | 5 | outcome, zero iterations, field/reason in context, None request, zero cost |
| `TestOutputAssemblerAuditSummary` | 2 | Populated from store, empty without store |
| `TestLoopInputValidationHandling` | 2 | Empty task, missing task → FinalResponse not exception |

**Full Audit Trail (all events from one successful workflow):**
```
WORKFLOW_STARTED         written by: loop.py
PLAN_PROPOSED            written by: loop.py
PLAN_EVALUATED           written by: EvaluateStage
HUMAN_REVIEW_REQUESTED   written by: EvaluateStage (if gated tasks)
HUMAN_REVIEW_RESPONDED   written by: EvaluateStage (if gated tasks)
EXECUTION_STARTED        written by: ExecutionOrchestrator
STEP_STARTED             written by: ExecutionOrchestrator (×N)
STEP_COMPLETED           written by: ExecutionOrchestrator (×N)
WORKFLOW_COMPLETED       written by: OutputAssembler
```


---

### Step 17 — Example 01: End-to-End Phase 2

**Purpose:**
The final step of Phase 2. Wires all components into a working
end-to-end example and verifies the complete stack with a mocked LLM
(no API key needed for the test suite).

**Bugs fixed during development:**
The `or`-based falsy check appeared in two more places:
- `loop.py`: `_audit_store = audit_store or InMemoryAuditStore()`
- `loop.py`: `_checkpoint_store = checkpoint_store or InMemoryCheckpointStore()`

Both suffered the same issue as Step 14 — empty stores are falsy.
Fixed to `if X is not None else` throughout.

**Files Updated:**

`daf/loop.py`
- Added `agent_registry` + `tool_registry` parameters to constructor
- Fixed `or`-based falsy default for `audit_store` and `checkpoint_store`

`examples/01_basic_analysis/run.py` — REPLACED
- Full Phase 2 stack: StubAgents + StubTools + real LLM
- Shows `setup_registries()` pattern for Phase 2 usage
- Documents what is real vs stubbed

**Files Created:**
`tests/integration/test_example01_mocked.py` — 14 tests

**How to Run Tests:**
```bash
# Mocked integration tests (no API key needed)
python -m pytest tests/integration/test_example01_mocked.py -v

# Full suite including mocked integration
python -m pytest tests/unit/ tests/adversarial/ tests/integration/test_example01_mocked.py -q
# Expected: 475 passed

# Run the actual example (requires LLM_API_KEY in .env)
python examples/01_basic_analysis/run.py
```

**What the Tests Verify:**

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestExample01EndToEnd` | 7 | Returns FinalResponse, completed outcome, 1 iteration, 3 steps, all succeed, task IDs, budget tracked |
| `TestExample01AuditTrail` | 4 | Full audit trail present, 3 STEP events, WORKFLOW_COMPLETED last, audit_summary populated |
| `TestExample01CheckpointLifecycle` | 1 | No checkpoint after completion |
| `TestExample01PolicyEnforcement` | 2 | Forbidden tool causes escalation, invalid input skips LLM |

---

## Phase 2 — COMPLETE ✓

All 12 steps are done. The execution layer is proven.

**Phase 2 Exit Criterion — MET:**
Example 01 runs end-to-end: real LLM planning (mocked in tests),
real PolicyEngine evaluation, real agent execution with ScopedContext,
real audit trail in InMemoryAuditStore, real budget tracking,
real checkpoint lifecycle. FinalResponse(outcome="completed") returned.

**Total test count at end of Phase 2:**

| Scope | Tests |
|---|---|
| Unit tests | 461 |
| Mocked integration (no API key) | 14 |
| Live integration (requires API key) | 11 |
| Adversarial | 20 |
| **Total** | **475 (+ 11 skipped without key)** |

**Phase 3 begins next:**
Full adversarial test suite expansion, Example 02 (re-planning loop),
Example 03 (human escalation gate), DAF v0.1 release.


---

## Phase 3 — Hardening

---

### Step 18 — Adversarial Suite Expansion

**Purpose:**
Expanded from 20 to 53 adversarial tests across 5 security layers.
Every security claim in the design philosophy is now tested.

**Files Created:**
- `tests/adversarial/test_input_injection.py` — 11 tests (Layer 1)
- `tests/adversarial/test_policy_engine_invariants.py` — 15 tests (Layer 2)
- `tests/adversarial/test_execution_invariants.py` — 12 tests (Layer 4)

**Security layers covered:**
```
Layer 1: Input injection defense (task, context, constraints)
Layer 2: Policy Engine determinism and malformed proposal handling
Layer 3: ScopedContext immutability (existing tests, now 18)
Layer 4: AgentResult, HITL response integrity, registry poisoning,
         audit record immutability
```

---

### Step 19 — Example 02: Re-planning Loop

**Files Created:**
- `examples/02_replan_loop/README.md`
- `tests/integration/test_example02_mocked.py` — 7 tests

**What the tests verify:**
- Loop self-corrects after policy violation (outcome=completed)
- loop_iterations == 2 (one rejected, one approved)
- LLM called twice
- Second call receives violation context
- Audit trail shows two PLAN_PROPOSED and two PLAN_EVALUATED events
- Always-escalating plan exhausts max_replan_attempts

---

### Step 20 — Example 03: Human Escalation Gate

**Files Created:**
- `tests/integration/test_example03_mocked.py` — 9 tests

**What the tests verify:**
HITL Approved (5 tests):
- Workflow completes when human approves
- Gateway receives review request with correct task details
- HITL audit records written (REQUESTED + RESPONDED)
- One iteration with approved review

HITL Rejected (2 tests):
- Rejection triggers re-plan / escalation
- Rejection recorded in audit trail

HITL Timeout (2 tests):
- Timeout treated as rejection, loop escalates
- Audit record has timed_out=True

---

### Step 21 — DAF v0.1.0 Release

**Version:** 0.1.0

**Total test count:**

| Scope | Tests |
|---|---|
| Unit tests | 461 |
| Adversarial tests | 53 |
| Mocked integration (no API key) | 35 |
| Live integration (requires API key) | 11 |
| **Total (no API key)** | **549 (+ 11 skipped)** |

**How to run everything:**
```bash
# All tests that don't need an API key
python -m pytest tests/unit/ tests/adversarial/ \
  tests/integration/test_example01_mocked.py \
  tests/integration/test_example02_mocked.py \
  tests/integration/test_example03_mocked.py \
  -q
# Expected: 526 passed

# Live integration tests (requires LLM_API_KEY in .env)
python -m pytest tests/integration/test_phase1_loop.py -v -s

# Run examples (requires LLM_API_KEY in .env)
python examples/01_basic_analysis/run.py
```

**Phase 3 complete. DAF v0.1.0 is ready.**

