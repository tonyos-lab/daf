# DAF Architecture

> This document explains the PBAS architecture that DAF implements. Read this before contributing code.

---

## The Core Principle

Every existing agent framework positions the LLM as the brain and the surrounding code as plumbing. DAF inverts this deliberately:

```
LLM        = the brain
             generates intent, plans, reasoning
             never holds execution authority

The system = the nervous system
             decides what signals reach the body
             enforces limits
             reports back what happened
```

This is not metaphor. It is a precise architectural constraint with direct implementation consequences.

---

## The Governed Agentic Loop

DAF implements one central mechanism: the Governed Agentic Loop.

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  Request → Planning Orchestrator (LLM)              │
│                    ↓ Plan Proposal                  │
│            Policy Engine (deterministic)            │
│           ↙ APPROVED          ↘ VIOLATED            │
│  Execution Orchestrator    Re-plan with context     │
│          ↓                      ↑                   │
│       Result            (loop continues)            │
│          ↓                                          │
│  Audit Trail                                        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**The loop has three roles:**

| Role | Component | Intelligence |
|---|---|---|
| Propose | Planning Orchestrator | LLM |
| Govern | Policy Engine | Deterministic code |
| Execute | Execution Orchestrator | Deterministic code |

The LLM only proposes. It never governs or executes.

---

## The Three Components

### Planning Orchestrator

**What it does:** Receives a user request and produces a Plan Proposal.

**What a Plan Proposal contains:**
- List of sub-tasks with dependencies
- For each sub-task: required agent role, required tools, required data, estimated cost, rationale
- Overall confidence score
- Human gate recommendation

**Critical constraint:** The Planning Orchestrator is the **only** component that invokes an LLM. Everything else is deterministic code.

**Re-planning:** When the Policy Engine rejects a proposal, the Planning Orchestrator receives the Violation Report and re-plans. The violation context (what failed, why, suggested alternative) is included in the re-planning prompt.

---

### Policy Engine

**What it does:** Receives a Plan Proposal and evaluates it against the PolicyMatrix. Returns either an Approval Grant or a Violation Report.

**What it evaluates:**

| Dimension | Question |
|---|---|
| Tool Permissions | Is each required tool in the agent role's permitted tools? |
| Data Access | Is each required data source in the agent role's permitted data? |
| Agent Authorization | Is this agent role permitted for this task type? |
| Orchestrator Routing | Is the requested orchestrator permitted to spawn this agent? |
| Budget | Does this sub-task fit within per-step and workflow budget limits? |
| Compliance | Does this sub-task violate any active compliance rule? |
| Risk Threshold | If irreversible, is confidence above the required threshold? |
| Loop Control | Has the maximum re-plan count been reached? |

**Critical constraint:** The Policy Engine is a **pure function**. Given the same Plan Proposal and PolicyMatrix, it always returns the same result. No async. No LLM calls. No external state reads during evaluation.

---

### Execution Orchestrator

**What it does:** Receives an Approval Grant and executes the approved plan.

**How it instantiates agents:** Each agent receives a `ScopedContext` derived directly from the Approval Grant. The ScopedContext contains exactly the tool clients and data clients the Policy Engine approved — no more.

**Critical constraint:** An agent **cannot** invoke a tool that is not in its ScopedContext. Not because it is instructed not to. Because the tool client does not exist in its context. This is structural enforcement, not behavioral enforcement.

---

## The PolicyMatrix

The PolicyMatrix is a YAML configuration file. It defines what the system is permitted to do. It is owned by the organization deploying DAF, not by DAF itself.

**Structure:**

```yaml
agent_roles:
  document_reader:
    permitted_tools: [read_db]
    permitted_data_sources: [internal_documents]
    permitted_task_types: [deterministic, llm_extraction]

orchestrator_routing:
  document_orchestrator:
    may_spawn_roles: [document_reader, report_writer]

budget_policy:
  max_cost_per_step_usd: 0.10
  max_cost_per_workflow_usd: 0.50

compliance_rules:
  - rule_ref: "DATA-GDPR-001"
    condition: "task.data_required contains pii AND region != EU_APPROVED"
    action: block

risk_policy:
  irreversible_min_confidence: 0.90
  always_gate_action_classes: [send_email, delete_record]

loop_policy:
  max_replan_attempts: 3
```

See [policy-matrix.md](policy-matrix.md) for the full schema reference.

---

## The Trust Boundary

DAF defines three trust zones:

```
Zone 1 — Trusted (framework internals)
  Policy Engine, PolicyMatrix store, AuditStore, BudgetTracker
  → These components are correct by design
  → PolicyMatrix has integrity verification

Zone 2 — Constrained (LLM-adjacent components)
  Planning Orchestrator, Execution Orchestrator, Agent ScopedContexts
  → These components touch the LLM or external tools
  → Their authority is bounded by ScopedContext and Approval Grant

Zone 3 — Untrusted (everything external)
  Tool outputs, API responses, user data, LLM outputs, retrieved documents
  → Nothing in Zone 3 is trusted
  → Zone 3 data never enters Zone 1 directly
  → Zone 3 data is clearly delimited in LLM prompts
```

This boundary is why DAF is structurally resistant to prompt injection: adversarial content in tool outputs is Zone 3 data. It cannot alter Zone 1 policy. And the ScopedContext enforces permissions regardless of what Zone 3 data instructs.

---

## The Eight Principles

1. **Deterministic Orchestration** — control flow in code, not prompts
2. **Narrow LLM Calls** — one cognitive function per call
3. **Output Contract Enforcement** — every call has a schema; violations trigger retry
4. **Immutable Audit Trail** — every step logged, tamper-evident
5. **Failure Isolation** — failures contained at step boundary
6. **Human Authority Preservation** — human gates are structural, not advisory
7. **Propose-Evaluate-Execute Separation** — the model proposes; the system decides and acts
8. **Policy Engine as System Kernel** — single authority for all execution decisions

---

## Further Reading

- [PBAS Whitepaper](https://arxiv.org/abs/XXXX.XXXXX) — the full academic treatment
- [DAF Technical Specification](https://github.com/daf-framework/daf/blob/main/docs/specification.md) — component interfaces and data schemas
- [Policy Matrix Reference](policy-matrix.md) — full schema documentation
- [Research Backlog](research/README.md) — open research questions
