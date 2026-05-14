# DAF Developer Guide

This guide is for people building DAF itself — implementing components, writing tests, and contributing to the framework. If you are building *with* DAF (using it in your own project), see [quickstart.md](quickstart.md) instead.

Read [design-philosophy.md](design-philosophy.md) before this document. The philosophy explains *why*. This guide explains *how*.

---

## 1. Development Environment

### Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Language runtime |
| pyenv | latest | Python version management |
| Docker Desktop | 24+ | Local services |
| Git | 2.40+ | Version control |
| make | any | Command runner |

### Setup

```bash
# Clone
git clone https://github.com/tonyos-lab/daf
cd daf

# Python environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux / WSL2
# .venv\Scripts\activate         # Windows CMD (not recommended — use WSL2)

# Dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Environment
cp .env.example .env
# Open .env and add your ANTHROPIC_API_KEY

# Local services (PostgreSQL, Redis, Grafana)
make services-up

# Verify setup
make test-unit        # should pass immediately
make test-adversarial # should pass immediately
```

### Verify your environment is correct

```bash
python -c "import daf; print(daf.__version__)"
# Expected: 0.1.0

python -c "from daf.components.policy_engine import PolicyEngine; print('OK')"
# Expected: OK

make test-unit
# Expected: all tests pass, no errors
```

If anything fails at this stage, check the [quickstart troubleshooting section](quickstart.md) before raising an issue.

---

## 2. Project Structure

```
daf/                          # Python package — the framework
  __init__.py                 # Public API: GovernedAgenticLoop
  loop.py                     # GovernedAgenticLoop — entry point
  components/                 # The five components
    policy_engine.py          # Deterministic governance — the kernel
    planning_orchestrator.py  # LLM cognitive layer
    execution_orchestrator.py # Deterministic runtime
    input_processor.py        # Entry point validation
    output_assembler.py       # Result assembly + audit
  models/                     # Pydantic schemas — shared contracts
    workflow_request.py
    plan_proposal.py
    approval_grant.py
    violation_report.py
    policy_matrix.py
    execution_result.py
    final_response.py
  runtime/                    # Infrastructure components
    scoped_context.py         # Agent runtime interface
    budget_tracker.py         # Atomic cost enforcement
    audit_store.py            # Append-only audit writer
    checkpoint_store.py       # Resumable state store
tests/
  unit/                       # Isolated, no external deps
  integration/                # Full loop, real LLM calls
  adversarial/                # Security properties — hard gate
docs/
  design-philosophy.md        # Why it is built this way
  developer-guide.md          # This document
  architecture.md             # Architecture overview
  quickstart.md               # For users of DAF
  policy-matrix.md            # PolicyMatrix reference
  research/                   # Research backlog and findings
policy/
  matrix/                     # PolicyMatrix YAML files
    example.yaml
examples/
  01_basic_analysis/          # Happy path
  02_replan_loop/             # Violation and re-plan
  03_governed_action/         # Human escalation gate
```

---

## 3. The Build Order

DAF is built in phases. Each phase produces something testable before the next begins. We never have a half-built component sitting in the codebase.

### Phase 1 — Core Loop

Build the governance mechanism. Prove that Propose → Evaluate → Execute works with stub agents.

```
Step 1:  PolicyEngine — complete compliance rule evaluation
Step 2:  PlanningOrchestrator — real Anthropic API call
Step 3:  GovernedAgenticLoop — wire components together
Step 4:  Integration test — loop runs end-to-end
```

**Exit criterion for Phase 1:**
The loop runs with a real LLM planning call, the Policy Engine evaluates the proposal, and either approves (triggering stub execution) or rejects (triggering re-planning). All unit and adversarial tests pass.

### Phase 2 — Execution

Build real agent execution within scoped permissions.

```
Step 5:  BaseAgent + AgentRegistry
Step 6:  BaseTool + ToolRegistry
Step 7:  ExecutionOrchestrator — real execution
Step 8:  ScopedContext — real tool clients
Step 9:  AuditStore — PostgreSQL writer
Step 10: CheckpointStore — Redis writer
Step 11: Example 01 working end-to-end
```

**Exit criterion for Phase 2:**
Example 01 runs end-to-end: real planning, real policy evaluation, real agent execution with scoped tools, real audit record written to PostgreSQL.

### Phase 3 — Hardening

```
Step 12: Full InputProcessor validation
Step 13: Full OutputAssembler with audit records
Step 14: Complete adversarial test suite
Step 15: Example 02 (re-planning loop)
Step 16: Example 03 (human escalation gate)
```

**Exit criterion for Phase 3:** DAF v0.1 — all three examples run, all tests pass, adversarial suite complete.

---

## 4. How to Implement a Component

Every component in DAF follows the same development pattern:

```
Design → Review → Code → Test → Review → Merge
```

**Never skip the design step.** Before writing a line of code, document what you plan to build. This catches design problems before they become code problems.

### The design document (required before coding)

For any non-trivial change, write a brief design note in the PR or Discussion:

```
Component: PolicyEngine._rule_applies()

What it does:
  Evaluates whether a compliance rule applies to a sub-task.
  Returns True if the rule applies, False if not.

Inputs:
  rule: ComplianceRule
  task: SubTask

Output:
  bool

Approach:
  Structured condition evaluation using three operators:
  - contains: field value contains the condition value
  - equals: field value equals the condition value
  - in_list: field value is in the condition list

What it does NOT do:
  - Does not evaluate arbitrary expressions
  - Does not call external services
  - Does not modify any state

Tests I will write:
  - rule with contains operator matches correctly
  - rule with equals operator matches correctly
  - unknown operator returns False (conservative)
  - rule with no matching field returns False
```

### The implementation pattern

```python
class SomeComponent:
    """
    One-line description of what this component does.

    CRITICAL (if applicable):
    - State any invariants that must never be violated
    - Example: "This method must never invoke an LLM"
    """

    def primary_method(
        self,
        input_a: TypeA,
        input_b: TypeB,
    ) -> ReturnType:
        """
        Brief description of what this method does.

        Args:
            input_a: What this is and what values are valid
            input_b: What this is and what values are valid

        Returns:
            Description of the return value

        Raises:
            ComponentError: When and why this is raised
        """
        # Implementation here
```

### Rules for all component implementations

**Type annotations are mandatory.** Every function parameter and return value must be typed. No `Any` unless explicitly justified in a comment.

**Docstrings are mandatory on public methods.** Private methods (`_name`) may have shorter docstrings. Magic methods (`__name__`) may omit docstrings.

**No `TODO` comments in production code.** If something is unfinished, it is either not merged yet or tracked as a GitHub Issue. `TODO` in merged code means the code is incomplete.

**No bare `except` clauses.** Always catch specific exceptions. If you genuinely need to catch everything, use `except Exception as e` and log `e`.

**No mutable default arguments.** Never `def fn(items=[])`. Always `def fn(items=None): if items is None: items = []`.

---

## 5. Coding Conventions

### Naming

```python
# Classes: PascalCase
class PolicyEngine:
class PlanProposal:

# Methods and functions: snake_case
def evaluate_proposal():
def _build_approval_grant():  # private: leading underscore

# Constants: SCREAMING_SNAKE_CASE
MAX_REPLAN_ATTEMPTS = 3
DEFAULT_CONFIDENCE_THRESHOLD = 0.90

# Variables: snake_case, descriptive
approval_grant = ...        # good
ag = ...                    # bad — not descriptive
temp = ...                  # bad — what is temp?

# Boolean variables: is_ or has_ prefix
is_approved = True
has_violations = False
```

### Imports

```python
# Standard library first
from __future__ import annotations
import uuid
import logging
from typing import Any
from datetime import datetime, timezone

# Third-party second
from pydantic import BaseModel, Field
import yaml

# DAF models third (never other components)
from daf.models.plan_proposal import PlanProposal
from daf.models.approval_grant import ApprovalGrant

# Never import another component from within a component
# WRONG:
from daf.components.planning_orchestrator import PlanningOrchestrator
```

### Logging

```python
# Module-level logger — always
logger = logging.getLogger(__name__)

# Log levels:
logger.debug(...)    # internal state useful during development
logger.info(...)     # significant events (workflow started, plan approved)
logger.warning(...)  # something unexpected but handled (re-plan triggered)
logger.error(...)    # something failed (step failed, escalation triggered)

# Always include structured context
logger.info(
    "Plan approved",
    extra={"proposal_id": str(proposal.proposal_id), "iteration": iteration}
)

# Never log sensitive data (API keys, PII, credentials)
```

### Error handling

```python
# Define component-specific exceptions in the component file
class PolicyEngineError(Exception):
    """Raised when the Policy Engine encounters an unrecoverable error."""
    pass

class PolicyMatrixError(PolicyEngineError):
    """Raised when the PolicyMatrix is invalid or cannot be loaded."""
    pass

# Raise with context
raise PolicyMatrixError(
    f"PolicyMatrix for tenant '{tenant_id}' not found at {path}"
)

# Catch specific exceptions
try:
    matrix = yaml.safe_load(path.read_text())
except yaml.YAMLError as e:
    raise PolicyMatrixError(f"Invalid YAML in PolicyMatrix: {e}") from e
except FileNotFoundError:
    raise PolicyMatrixError(f"PolicyMatrix file not found: {path}") from None
```

---

## 6. Testing Requirements

### Unit tests

Every component must have unit tests before it is considered complete. Unit tests:

- Run without any external dependencies (no LLM, no Docker, no filesystem)
- Use the `make_*` helper functions to build test fixtures
- Test both the success path and every failure path
- Are fast — the entire unit suite runs in under 30 seconds

**Coverage target:**
- `PolicyEngine`: 100% — it is deterministic, there is no excuse for less
- All other components: 90%+ with justification for any gaps

**The test helper pattern:**

```python
# Define fixture builders at the top of each test file
# These make tests readable and reduce boilerplate

def make_matrix(**overrides) -> PolicyMatrix:
    """Build a PolicyMatrix with safe test defaults."""
    defaults = {
        "version": "1.0.0",
        "tenant_id": "test",
        "effective": "2026-01-01T00:00:00Z",
        "agent_roles": {
            "test_agent": AgentRoleConfig(
                permitted_tools=["read_db"],
                permitted_data_sources=["test_data"],
                permitted_task_types=["llm_extraction"],
                max_llm_calls_per_step=3,
            )
        },
    }
    defaults.update(overrides)
    return PolicyMatrix(**defaults)


def make_proposal(**overrides) -> PlanProposal:
    """Build a PlanProposal with safe test defaults."""
    defaults = {
        "request_id": uuid.uuid4(),
        "iteration": 1,
        "orchestrator": "test_orchestrator",
        "planning_rationale": "test plan",
        "sub_tasks": [make_subtask()],
        "total_estimated_cost": 0.05,
        "confidence": 0.95,
    }
    defaults.update(overrides)
    return PlanProposal(**defaults)
```

**The test structure:**

```python
class TestPolicyEngineToolPermissions:
    """
    Group related tests in classes.
    Class name describes what is being tested.
    """

    def test_permitted_tool_passes(self):
        """
        Method name: test_{condition}_{expected_result}
        Docstring: one sentence describing the scenario.
        """
        # Arrange
        matrix = make_matrix()
        proposal = make_proposal()  # uses read_db which is permitted

        # Act
        result = engine.evaluate(proposal, matrix)

        # Assert — specific, not generic
        assert result.verdict == "APPROVED"

    def test_unpermitted_tool_returns_blocking_violation(self):
        # Arrange
        matrix = make_matrix()
        proposal = make_proposal()
        proposal.sub_tasks[0].tools_required = ["write_db"]  # not permitted

        # Act
        result = engine.evaluate(proposal, matrix)

        # Assert
        assert result.verdict == "REJECTED"
        assert len(result.violation_report.violations) == 1
        v = result.violation_report.violations[0]
        assert v.dimension == "tool_permission"
        assert v.severity == "blocking"
        assert "write_db" in v.detail
        assert v.suggestion != ""  # must always provide a suggestion
```

### Adversarial tests

Adversarial tests verify security properties. They live in `tests/adversarial/` and are a hard gate — any failure blocks all deployments.

The adversarial test contract:

```python
class TestScopedContextEnforcement:
    """
    SECURITY TESTS.
    These verify that runtime constraints cannot be bypassed.
    ALL TESTS MUST PASS. Any failure is a security regression.
    Do not skip. Do not mock security properties.
    """
```

**What adversarial tests cover:**

- ScopedContext: unpermitted tools do not exist in context
- ScopedContext: unpermitted data sources do not exist in context
- BudgetTracker: concurrent reservations never produce over-budget approvals
- PolicyEngine: malformed proposals do not produce incorrect approvals
- PolicyEngine: adversarial proposal content does not bypass evaluation

**Adding a new adversarial test:**

When you implement a new security property, add a corresponding adversarial test. The test must:
1. Simulate a realistic attack scenario
2. Verify the property holds regardless of model behavior
3. Include a comment explaining the attack it defends against

### Integration tests

Integration tests test the full loop. They cost money (real LLM calls) and require Docker. Run them deliberately — before every commit, not on every save.

```bash
# Requires: .env with LLM_API_KEY, make services-up
make test-integration
```

---

## 7. The Review Workflow

### Between the maintainer and contributors

DAF uses a design-first review workflow:

```
1. Contributor opens an Issue describing what they want to build
2. Maintainer reviews the design — approves, adjusts, or rejects
3. Contributor implements based on approved design
4. Contributor opens PR with implementation + tests
5. Maintainer reviews code and tests
6. Approved → merged. Needs changes → back to step 3.
```

**Never open a PR without a prior design discussion for non-trivial changes.** A PR that changes component interfaces, adds new models, or modifies security properties requires a prior Issue or Discussion thread.

### What makes a PR ready for review

- [ ] All tests pass: `make test-all`
- [ ] Adversarial tests pass: `make test-adversarial`
- [ ] Linter passes: `make lint`
- [ ] Formatter applied: `make format`
- [ ] New public methods have docstrings
- [ ] CHANGELOG.md has an entry
- [ ] Design philosophy is not violated (self-check against Section 3 of design-philosophy.md)
- [ ] No `TODO` comments in the implementation

### What the reviewer checks

**First pass — philosophy compliance:**
- Does this change violate any principle in design-philosophy.md?
- Does the PolicyEngine remain a pure function?
- Are all new security properties covered by adversarial tests?

**Second pass — correctness:**
- Do the tests cover both the happy path and failure paths?
- Are error messages specific and actionable?
- Are exceptions raised for unexpected failures (not swallowed)?

**Third pass — code quality:**
- Are type annotations complete?
- Are docstrings present on public methods?
- Is the naming clear and consistent?

---

## 8. Adding a New Component

If you are adding a completely new component to DAF, follow this checklist:

```
Before writing code:
  [ ] Read design-philosophy.md
  [ ] Confirm the component fits the dependency rule
      (it imports models, not other components)
  [ ] Confirm its primary method signature
  [ ] Open a GitHub Discussion for design review
  [ ] Get approval from the lead maintainer

Implementation:
  [ ] Create the file in the correct directory
  [ ] Add module-level logger
  [ ] Define component-specific exceptions
  [ ] Implement with full type annotations
  [ ] Add docstrings to all public methods
  [ ] Determine: sync or async? (see philosophy Section 5)

Tests:
  [ ] Create test file in tests/unit/
  [ ] Implement make_*() fixture helpers
  [ ] Test every public method
  [ ] Test every failure path
  [ ] If security-relevant: add adversarial tests

Integration:
  [ ] Add to components/__init__.py
  [ ] Wire into loop.py if applicable
  [ ] Update docs/architecture.md if architecture changes
  [ ] Add CHANGELOG.md entry
```

---

## 9. Common Patterns

### The make_*() fixture pattern

Every test file that tests a component with complex inputs defines fixture builders at the module level. This keeps tests readable and reduces duplication.

```python
# At the top of every test file:
def make_matrix(**overrides) -> PolicyMatrix:
    ...

def make_proposal(**overrides) -> PlanProposal:
    ...

def make_subtask(**overrides) -> SubTask:
    ...
```

The `**overrides` pattern lets each test customize only the fields it cares about:

```python
# Test only cares about tools_required
proposal = make_proposal()
proposal.sub_tasks[0].tools_required = ["forbidden_tool"]

# Test only cares about budget
matrix = make_matrix(
    budget_policy=BudgetPolicyConfig(max_cost_per_step_usd=0.001)
)
```

### The stub → real implementation pattern

Stubs in the codebase are explicitly marked. They compile and run but produce predictable minimal output. They are never left in production code past their phase.

```python
async def execute(self, approval_grant: ApprovalGrant) -> ExecutionResult:
    """Execute an approved plan."""
    # STUB — Phase 2 implementation
    # Tracked in: github.com/tonyos-lab/daf/issues/NNN
    logger.warning("ExecutionOrchestrator.execute() is a stub")
    return ExecutionResult(
        grant_id=approval_grant.grant_id,
        outcome="stub_completed",
        ...
    )
```

When implementing a stub:
1. Remove the stub comment
2. Write the real implementation
3. Write or update the tests
4. Close the tracking issue

### The schema-first design pattern

Models are defined before the components that use them. When designing a new component, start with the input and output schemas:

```python
# Step 1: Define what goes in and what comes out
class NewComponentInput(BaseModel):
    field_a: str
    field_b: int

class NewComponentOutput(BaseModel):
    result: str
    success: bool

# Step 2: Write the test using these schemas
def test_new_component_success():
    input = NewComponentInput(field_a="test", field_b=1)
    result = component.process(input)
    assert isinstance(result, NewComponentOutput)
    assert result.success is True

# Step 3: Implement the component to make the test pass
```

---

## 10. Makefile Reference

```bash
make test-unit          # Unit tests — fast, no external deps
make test-integration   # Full loop — requires LLM API + Docker
make test-adversarial   # Security tests — hard gate
make test-all           # All three suites
make test-coverage      # Coverage report in htmlcov/

make lint               # ruff check .
make format             # ruff format .

make services-up        # Start Docker services
make services-down      # Stop Docker services (keep data)
make services-reset     # Stop and delete all data
make services-status    # Check service health

make cost-today         # API spend today
make cost-month         # API spend this month

make jupyter            # Start Jupyter Lab for experiments
```

---

## 11. Getting Help

**For questions about the architecture or design:**
Open a Discussion in the Architecture category.

**For questions about how to implement something:**
Open a Discussion in the Q&A category.

**For bugs:**
Open an Issue using the Bug Report template.

**For security issues:**
Email security@tonyos-lab.org — do not open a public issue.

**Response time:**
Every question receives a response within 48 hours. This is a commitment, not a target.

---

*This document is maintained by the DAF community.*
*Last updated: 2026 — DAF is a TonyOS Lab open-source project — tonyos-lab.org*
