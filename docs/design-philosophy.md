# DAF Design Philosophy

> The model proposes. The system governs.

This document explains the thinking behind every architectural decision in DAF. It is not a tutorial. It is not a reference. It is the answer to the question: *why is it built this way?*

Read this before contributing code. The code enforces these principles. Understanding the philosophy tells you why the code is shaped the way it is — and why certain things that might seem like improvements would actually be regressions.

---

## 1. The Central Claim

Every existing agent framework makes the same architectural assumption: the LLM is the brain, and the surrounding code is plumbing. The model plans, decides, and governs itself. The framework just wires things together.

This assumption is the root cause of every structural failure in production AI systems:

- Non-determinism that makes systematic testing impossible
- Silent corruption where agents report success while systems are broken
- Unbounded cost with no external termination mechanism
- Prompt injection vulnerabilities that cannot be fixed with better prompts
- Auditability gaps that create compliance exposure

These are not bugs. They are consequences of giving the model execution authority it was not designed to hold.

DAF makes a different claim:

> **The LLM is the brain. The system is the nervous system. The brain generates intent, plans, and reasoning. The nervous system decides what signals reach the body, enforces physical limits, and reports back what happened. Neither is complete without the other. The brain never bypasses the nervous system to act directly on the world.**

This is not metaphor. It is a precise architectural constraint with direct implementation consequences. In DAF, the model proposes. The system governs. The system acts. These are not the same role given to different components. They are fundamentally different responsibilities that must be held by fundamentally different types of systems.

---

## 2. What We Reject

Understanding what DAF rejects is as important as understanding what it does.

### We reject the autonomous agent pattern

```python
# This is the pattern DAF rejects
agent.run("research competitors and send the report to stakeholders")
# → LLM decides what tools to call
# → LLM decides what data to access
# → LLM decides when to send emails
# → No cost control
# → No audit trail
# → Prompt injection can redirect any of the above
```

The autonomous agent pattern is excellent for demonstrations. It produces impressive results in controlled environments. It fails structurally in production because the properties that production systems require — determinism, auditability, cost control, security boundaries — are incompatible with unconstrained model agency.

### We reject prompt-based constraints

Prompt-based constraints are the prevailing defense in existing frameworks:

```
"You are a finance agent. Only access finance data.
 Do not read other databases. Stay within budget."
```

These constraints are language. Language can be:
- Reasoned around by a sufficiently confused model
- Overridden by adversarial content in tool outputs
- Lost across context window boundaries
- Silently ignored by a model that has received conflicting instructions

DAF's position is unambiguous: **prompt-based constraints are not enforcement mechanisms**. They are suggestions. They may improve model behavior on average. They cannot provide guarantees.

Every security-relevant constraint in DAF is enforced at the runtime layer. A ScopedContext instantiated with permission to call `read_db` literally cannot call `write_db` because that client does not exist in its context. This is not a prompt. It is physics.

### We reject multi-purpose LLM calls

Asking the model to simultaneously classify, reason, decide, format, and act in a single prompt produces outputs that are harder to validate, harder to retry safely, and harder to reason about when something goes wrong.

DAF defines a strict taxonomy of LLM call types. Each call does exactly one thing. A call that classifies does not also summarize. A call that extracts does not also decide. This narrowness is not a limitation — it is the primary driver of per-call reliability.

### We reject silent failures

A system that reports success while leaving the world in a broken state is worse than a system that fails loudly. Silent failures erode trust in ways that are invisible until they become catastrophic.

In DAF, the only valid non-success outcome from the Policy Engine is a `REJECTED` verdict with a structured `ViolationReport`. This is not a failure — it is the system working correctly. Everything else that goes wrong is an exception that surfaces immediately. We never swallow errors. We never continue from an unknown state.

---

## 3. The Eight Principles

### Principle 1 — Deterministic Orchestration

All control flow, routing decisions, state transitions, and error handling live in code, not in model prompts. Task sequencing, retry policies, and escalation paths are engineering artifacts with deterministic, testable behavior.

**In practice:** If you find yourself writing a prompt that tells the model to decide what step to take next, you are violating this principle. That decision belongs in the orchestrator as an `if/else` statement.

**Prohibits:** Using the LLM to route between workflow paths, decide on retry behavior, or determine escalation conditions.

**Correct vs wrong:**

```python
# WRONG — LLM decides routing
response = llm.call("Should we retry or escalate? Answer: retry or escalate")
if "retry" in response:
    retry()

# CORRECT — orchestrator decides routing
result = policy_engine.evaluate(proposal, matrix)
if result.verdict == "REJECTED" and proposal.iteration < matrix.loop_policy.max_replan_attempts:
    return await self.planning_orchestrator.plan(request, [result.violation_report], iteration + 1)
else:
    return self.output_assembler.escalate(request, violation_history)
```

---

### Principle 2 — Narrow LLM Calls

Each model invocation performs exactly one cognitive function from the defined taxonomy: classify, extract, summarize, transform, evaluate, translate, or plan. The Planning call type is unique to DAF — it produces a structured `PlanProposal` and nothing else.

**In practice:** Before writing a prompt, state in one sentence what cognitive function this call performs. If you cannot state it in one sentence, the call is doing too much.

**Prohibits:** Prompts that ask the model to "analyze, summarize, and recommend" in one call. Prompts that mix planning with formatting. Prompts that conflate evaluation with generation.

**Correct vs wrong:**

```python
# WRONG — multi-purpose call
prompt = """
Analyze these contracts, identify risks,
summarize findings, and format as a report.
"""

# CORRECT — separate calls, each with one purpose
risks = await extraction_call(contracts)      # extracts structured risks
summary = await summarization_call(risks)     # summarizes extracted risks
report = await generation_call(summary)       # formats summary as report
```

---

### Principle 3 — Output Contract Enforcement

Every model call is accompanied by a strict output schema. Responses not conforming to the contract trigger a defined retry or escalation path. Silent consumption of malformed responses is prohibited.

**In practice:** Every LLM call in DAF uses Anthropic's structured output mode or function calling to enforce the schema at the API layer. Schema validation happens before the response enters any downstream component.

**Prohibits:** Parsing model output with regex. Assuming the model will "usually" return the right format. Continuing with a partially valid response.

**Correct vs wrong:**

```python
# WRONG — parse and hope
response = llm.call(prompt)
data = json.loads(response.text)  # might fail, might produce garbage

# CORRECT — enforce schema at the API layer
response = llm.call(prompt, response_format=PlanProposal.model_json_schema())
proposal = PlanProposal.model_validate(response.parsed)  # raises if invalid
```

---

### Principle 4 — Immutable Audit Trail

Every workflow step produces a tamper-evident log entry. This is a first-class architectural requirement, not instrumentation added after the fact. The audit trail is what makes the system trustworthy to compliance teams, enterprise evaluators, and the researchers validating our claims.

**In practice:** The `AuditStore` writes append-only records. `UPDATE` and `DELETE` are revoked at the database level. Every record includes the Policy Engine decision that authorized execution.

**Prohibits:** Mutable audit records. Audit logging as an afterthought. Selectively logging only successful outcomes.

---

### Principle 5 — Failure Isolation

Failures are contained at the step boundary and cannot corrupt workflow state. Side-effectful actions are classified as idempotent or non-idempotent before execution. Checkpointing enables safe resumption from any failure point.

**In practice:** A failed sub-task raises an exception that the `ExecutionOrchestrator` catches at the step boundary. The exception does not propagate to other sub-tasks unless they depend on the failed one. State is checkpointed after each successful step.

**Prohibits:** Exceptions that propagate across step boundaries. Retrying non-idempotent actions without verification. Proceeding from an unknown state after a failure.

---

### Principle 6 — Human Authority Preservation

Human review gates for high-risk or irreversible actions are structural components enforced by the framework, not advisory prompts asking the model to exercise judgment about when human involvement is appropriate.

**In practice:** The Policy Engine checks `risk_policy.always_gate_action_classes` against each sub-task. When a gate is required, the `ExecutionOrchestrator` halts and emits an escalation event. It does not ask the model whether a human is needed. It checks the policy and acts accordingly.

**Prohibits:** Prompts like "escalate to a human if you are unsure." Using the model's confidence score as the sole criterion for human involvement. Allowing the model to bypass human gates based on its own assessment of urgency.

---

### Principle 7 — Propose-Evaluate-Execute Separation

The model proposes actions with rationale, confidence, and cost estimates. The system evaluates proposals against organizational policy. Execution authority is granted exclusively by the system after policy evaluation passes.

**In practice:** The `PlanningOrchestrator` never directly invokes the `ExecutionOrchestrator`. It produces a `PlanProposal` and returns it. The `GovernedAgenticLoop` passes it to the `PolicyEngine`. The `PolicyEngine` produces an `ApprovalGrant`. Only then does the `ExecutionOrchestrator` run.

**Prohibits:** Any path where execution follows directly from planning without policy evaluation. Any component other than the `PolicyEngine` issuing `ApprovalGrant` objects.

---

### Principle 8 — Policy Engine as System Kernel

The Policy Engine is the single authority for all execution decisions. It is a pure function: given the same `PlanProposal` and `PolicyMatrix`, it always returns the same result. It never invokes an LLM. It never makes async calls. It never reads mutable external state during evaluation.

**In practice:** The `PolicyEngine.evaluate()` method is synchronous. It takes two arguments: `proposal` and `matrix`. It returns a `PolicyEvaluation`. Nothing else enters or leaves during evaluation.

**Prohibits:** Adding an LLM call to the Policy Engine to "improve" its decisions. Making the Policy Engine async. Reading from a database during evaluation. Caching evaluation results based on external state.

---

## 4. The Dependency Rule

Components in DAF have a strict dependency hierarchy:

```
loop.py
  ↓ may import
components/
  ↓ may import
models/    runtime/
  ↓ may import
(nothing — pure data and pure utilities)
```

**No component imports another component.** Components communicate exclusively through models (Pydantic schemas). The `PolicyEngine` does not import `PlanningOrchestrator`. The `ExecutionOrchestrator` does not import `PolicyEngine`. They each import the models that define their inputs and outputs.

This is not a code style preference. It is a philosophical constraint. If `ComponentA` imports `ComponentB`, then `ComponentA`'s behavior depends on `ComponentB`'s implementation. This creates hidden coupling that makes the system harder to test, harder to reason about, and harder to evolve independently.

**The test for a clean dependency:** Can you instantiate and test this component without instantiating any other component? If yes, the dependency rule is satisfied. If no, there is a hidden import that needs to be broken.

---

## 5. The Sync/Async Boundary

The sync/async boundary in DAF is not a performance decision. It is an architectural signal.

```
Synchronous = deterministic, no external dependencies
Async       = touches the LLM, a database, an API, or a file
```

**Synchronous components:**
- `PolicyEngine.evaluate()` — pure function
- `BudgetTracker.check_and_reserve()` — atomic in-memory operation
- `PolicyMatrix` loading — file read at initialization, not during evaluation
- All Pydantic model validation

**Async components:**
- `PlanningOrchestrator.plan()` — calls the Anthropic API
- `ExecutionOrchestrator.execute()` — runs agents that may call tools
- `AuditStore.write()` — writes to PostgreSQL
- `CheckpointStore.save()` — writes to Redis

When you read a method signature and see `async def`, you know immediately: this component touches the outside world. When you see `def`, you know: this is deterministic and testable without any external dependencies.

This convention must be maintained consistently. Do not make a synchronous method async for "future flexibility." Do not make an async method synchronous to simplify a test — mock the async call instead.

---

## 6. How We Handle Failure

### The two categories of non-success

**Category 1 — Expected non-success (not an exception):**

```python
result = policy_engine.evaluate(proposal, matrix)
if result.verdict == "REJECTED":
    # This is normal. The system is working correctly.
    # Handle the violation report and re-plan.
```

A `REJECTED` verdict is not a failure. It is the Policy Engine doing its job. Handle it with normal control flow.

**Category 2 — Unexpected failure (always an exception):**

```python
# If the LLM API is unreachable, raise — do not return a fake response
# If the PolicyMatrix file is corrupt, raise — do not silently use defaults
# If the AuditStore write fails, raise — do not continue without a record
```

Unexpected failures are always exceptions. They surface immediately. They are never swallowed. The system halts rather than continues from an unknown state.

### Why we fail loud

A system that continues from an unknown state produces outputs that cannot be trusted. In a governed AI system, trust is the product. A single silent failure undermines the audit trail, compromises the Policy Engine's guarantees, and — in a production deployment — may cause real-world harm.

The cost of a loud failure is a stopped workflow. The cost of a silent failure is an untrusted system. We always choose the stopped workflow.

---

## 7. What We Will Never Compromise

These are invariants. They are not guidelines. They are not "best practices that we follow when convenient." They are hard constraints that define what DAF is. Violating any of them is not a performance optimization or a pragmatic tradeoff. It is a change to the fundamental nature of the system.

**The Policy Engine stays deterministic.**
No LLM calls. No async. No mutable external state during evaluation. Ever.

**The ScopedContext is structural, not advisory.**
Agent permissions are enforced at instantiation through client availability. A tool that is not in the ScopedContext does not exist. This enforcement never moves to a prompt.

**Adversarial tests are a hard gate.**
If any test in `tests/adversarial/` fails, nothing ships. No exceptions. No "we'll fix it in the next release." Fix it now.

**The audit trail is immutable.**
No `UPDATE`. No `DELETE`. No post-hoc modification of records for any reason.

**Execution authority flows only from the Policy Engine.**
The only valid source of an `ApprovalGrant` is `PolicyEngine.evaluate()`. Nothing else in the system creates or modifies `ApprovalGrant` objects.

---

## 8. How This Philosophy Evolves

This document is not frozen. The philosophy can and should evolve as we learn from building DAF, running experiments, and receiving community feedback.

**How to propose a philosophy change:**

1. Open a GitHub Discussion in the Architecture category
2. State clearly: which principle you are proposing to change, why, and what the new formulation should be
3. Include concrete examples showing the current principle leading to a worse outcome than the proposed change
4. Allow 14 days for community discussion
5. The lead maintainer makes the final decision and updates this document

**What requires a philosophy change vs what does not:**

A philosophy change is required when:
- A principle is being violated in the implementation
- New evidence from research suggests a principle is incorrect
- A new use case is incompatible with a principle

A philosophy change is NOT required when:
- You want to add a new component that follows existing principles
- You want to change how a principle is implemented (not whether it applies)
- You disagree with the style but not the substance

**The bar for changing an invariant (Section 7) is higher.**
Changing an invariant requires not just a community discussion but a formal Architectural Decision Record documenting the problem, the options considered, the decision, and the consequences. Invariants protect the properties that make DAF trustworthy. They change rarely and deliberately.

---

## Summary

DAF is built on one insight: intelligence and execution authority are different things. The model provides intelligence. The system holds authority. Separating these cleanly — in the architecture, in the code, in the tests — is what makes governed AI possible.

Everything in this document follows from that insight. The eight principles are its expression. The dependency rule enforces it structurally. The sync/async boundary makes it visible in type signatures. The invariants protect it permanently.

When you contribute to DAF, you are not just writing code. You are implementing a claim about how AI systems should be built. The philosophy is the claim. The code is the proof.

---

*This document is maintained by the DAF community. Changes follow the process in Section 8.*
*Last updated: 2026 — DAF is a TonyOS Lab open-source project — tonyos-lab.org*
