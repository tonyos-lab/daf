#!/usr/bin/env python3
"""
Generate all 38 DAF research experiment scaffolds.
Run from repo root: python scripts/scaffold_experiments.py
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXP_ROOT  = REPO_ROOT / "experiments"

# ---------------------------------------------------------------------------
# Master registry — all 38 experiments
# ---------------------------------------------------------------------------

EXPERIMENTS = [
    # ── RELIABILITY (REL) ──────────────────────────────────────────────────
    dict(
        id="REL-001", dir="REL_001", domain="reliability", tier=1,
        title="Per-Call Reliability Characterisation",
        question="Can per-call reliability be formally characterised as a function of call type and model tier?",
        hypothesis="A MockLLMClient with fail_after=N produces a success rate of N/(N+1) deterministically across all runs.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=5,
    ),
    dict(
        id="REL-002", dir="REL_002", domain="reliability", tier=1,
        title="Reliability Composability Under Sequential Tasks",
        question="Does reliability compose predictably when multiple tasks are chained in a single plan?",
        hypothesis="The overall success rate of a multi-task plan equals the product of individual task success rates.",
        depends_on=["REL-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="REL-003", dir="REL_003", domain="reliability", tier=1,
        title="Loop Termination Guarantee",
        question="Under what PolicyMatrix configurations is Governed Agentic Loop termination formally guaranteed?",
        hypothesis="The loop always terminates within max_replan_attempts+1 iterations regardless of LLM output.",
        depends_on=["REL-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="REL-004", dir="REL_004", domain="reliability", tier=1,
        title="Concurrent Loop Reliability",
        question="Does reliability degrade when multiple GovernedAgenticLoop instances run concurrently?",
        hypothesis="Concurrent loops do not share state and each maintains its individual reliability guarantee.",
        depends_on=["REL-001"], estimated_cost=0.0, estimated_minutes=15,
    ),
    dict(
        id="REL-005", dir="REL_005", domain="reliability", tier=2,
        title="Live API Reliability Baseline",
        question="What is the empirical per-call success rate against the live Anthropic API under normal conditions?",
        hypothesis="Live API calls succeed at ≥99% over 100 consecutive planning calls under normal load.",
        depends_on=["REL-001"], estimated_cost=2.50, estimated_minutes=30,
    ),
    dict(
        id="REL-006", dir="REL_006", domain="reliability", tier=1,
        title="Replan Loop Convergence Rate",
        question="At what rate does the replan loop converge to a compliant plan after a violation?",
        hypothesis="A correctly configured PolicyMatrix with a well-structured violation message produces a compliant replan within 2 iterations ≥90% of the time.",
        depends_on=["REL-003"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="REL-007", dir="REL_007", domain="reliability", tier=1,
        title="Error Propagation Isolation",
        question="Does a failure in one task prevent correct results from earlier tasks being lost?",
        hypothesis="When a task fails mid-plan, all previously completed task outputs are preserved in the ExecutionResult.",
        depends_on=["REL-002"], estimated_cost=0.0, estimated_minutes=10,
    ),

    # ── OBSERVABILITY (OBS) ────────────────────────────────────────────────
    dict(
        id="OBS-001", dir="OBS_001", domain="observability", tier=1,
        title="Minimal Audit Schema for Compliance",
        question="What is the minimal audit schema satisfying SOC2, HIPAA, and GDPR simultaneously?",
        hypothesis="The InMemoryAuditStore record structure contains all fields required by SOC2, HIPAA, and GDPR with no additions needed.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=15,
    ),
    dict(
        id="OBS-002", dir="OBS_002", domain="observability", tier=1,
        title="Audit Trail Completeness",
        question="Does the audit trail capture every state transition in the Governed Agentic Loop?",
        hypothesis="Every loop execution produces exactly one audit record per defined event type, with no gaps.",
        depends_on=["OBS-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="OBS-003", dir="OBS_003", domain="observability", tier=1,
        title="Audit Record Immutability",
        question="Can audit records be modified after they are written to the store?",
        hypothesis="AuditRecord is frozen at creation — no field can be mutated after write.",
        depends_on=["OBS-001"], estimated_cost=0.0, estimated_minutes=5,
    ),
    dict(
        id="OBS-004", dir="OBS_004", domain="observability", tier=2,
        title="OTEL Trace Export Fidelity",
        question="Are all internal DAF spans exported correctly via the OpenTelemetry collector?",
        hypothesis="All loop stage spans (plan, evaluate, execute) appear in the OTEL collector with correct parent-child relationships.",
        depends_on=["OBS-002"], estimated_cost=0.0, estimated_minutes=20,
    ),
    dict(
        id="OBS-005", dir="OBS_005", domain="observability", tier=2,
        title="Grafana Dashboard Coverage",
        question="Do the Grafana dashboards expose all metrics required for operational monitoring?",
        hypothesis="The default Grafana dashboard covers loop duration, cost per workflow, violation rate, and escalation rate.",
        depends_on=["OBS-004"], estimated_cost=0.0, estimated_minutes=30,
    ),

    # ── ORCHESTRATION (ORC) ────────────────────────────────────────────────
    dict(
        id="ORC-001", dir="ORC_001", domain="orchestration", tier=1,
        title="Task Dependency Resolution Correctness",
        question="Does the ExecutionOrchestrator correctly resolve and enforce task dependency ordering?",
        hypothesis="Tasks with declared dependencies always execute after their dependencies, regardless of plan ordering.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="ORC-002", dir="ORC_002", domain="orchestration", tier=1,
        title="ScopedContext Tool Isolation",
        question="Are tools outside an agent's permitted set completely inaccessible within a ScopedContext?",
        hypothesis="Calling an unpermitted tool via ScopedContext raises ToolNotFoundError in 100% of cases.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="ORC-003", dir="ORC_003", domain="orchestration", tier=1,
        title="Multi-Agent Plan Execution Isolation",
        question="Do multiple agents in a single plan share any mutable state?",
        hypothesis="Two agents executing in the same plan cannot read or write each other's ScopedContext.",
        depends_on=["ORC-002"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="ORC-004", dir="ORC_004", domain="orchestration", tier=1,
        title="Budget Tracking Accuracy",
        question="Does the BudgetTracker accurately reflect cumulative cost across all tasks in a workflow?",
        hypothesis="Total cost reported in FinalResponse equals the sum of all individual task costs to within floating-point precision.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="ORC-005", dir="ORC_005", domain="orchestration", tier=1,
        title="Checkpoint Resume Correctness",
        question="After a mid-workflow interruption, does resuming from checkpoint produce the same result as an uninterrupted run?",
        hypothesis="A workflow resumed from a saved checkpoint produces an identical FinalResponse to one that ran uninterrupted.",
        depends_on=["ORC-001"], estimated_cost=0.0, estimated_minutes=15,
    ),
    dict(
        id="ORC-006", dir="ORC_006", domain="orchestration", tier=1,
        title="Empty Plan Handling",
        question="How does the loop behave when the LLM returns a plan with zero sub-tasks?",
        hypothesis="An empty plan is evaluated and either approved (returning a completed outcome with no steps) or rejected based on PolicyMatrix configuration.",
        depends_on=["ORC-001"], estimated_cost=0.0, estimated_minutes=5,
    ),

    # ── SECURITY (SEC) ─────────────────────────────────────────────────────
    dict(
        id="SEC-001", dir="SEC_001", domain="security", tier=1,
        title="Prompt Injection Resistance Baseline",
        question="What is the prompt injection resistance rate of PBAS-compliant implementations versus autonomous agent baselines?",
        hypothesis="Injected instructions in the task field cannot cause the PolicyEngine to approve a policy-violating plan.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=15,
    ),
    dict(
        id="SEC-002", dir="SEC_002", domain="security", tier=1,
        title="Tool Permission Escalation Resistance",
        question="Can an LLM-generated plan grant itself access to tools not in the PolicyMatrix?",
        hypothesis="Any plan referencing tools not in the agent's permitted_tools list is rejected in 100% of cases regardless of how the request is framed.",
        depends_on=["SEC-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="SEC-003", dir="SEC_003", domain="security", tier=1,
        title="Budget Bypass Resistance",
        question="Can a malformed plan bypass the budget enforcement in the PolicyEngine?",
        hypothesis="No plan with estimated_cost_usd exceeding the PolicyMatrix budget limit can be approved, regardless of field manipulation.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="SEC-004", dir="SEC_004", domain="security", tier=1,
        title="Compliance Rule Bypass Resistance",
        question="Can adversarial task inputs cause compliance block rules to be skipped?",
        hypothesis="A compliance rule with action=block fires in 100% of matching cases regardless of how the triggering field is encoded.",
        depends_on=["SEC-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="SEC-005", dir="SEC_005", domain="security", tier=1,
        title="Audit Record Forgery Resistance",
        question="Can a malicious agent inject false records into the AuditStore?",
        hypothesis="The AuditStore rejects duplicate audit IDs and frozen record mutation in 100% of attempts.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="SEC-006", dir="SEC_006", domain="security", tier=1,
        title="HITL Response Forgery Resistance",
        question="Can a forged HumanReviewResponse cause the loop to execute a rejected plan?",
        hypothesis="HumanReviewResponse is frozen at creation — a forged approval cannot override a legitimate rejection.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="SEC-007", dir="SEC_007", domain="security", tier=1,
        title="Input Sanitisation Coverage",
        question="What categories of malicious input does the InputProcessor reject before reaching the LLM?",
        hypothesis="All 8 adversarial input categories (null bytes, YAML injection, oversized fields, non-string types, negative costs, zero costs, non-dict constraints, non-serialisable context) are rejected at the InputProcessor.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=15,
    ),

    # ── COST (CST) ─────────────────────────────────────────────────────────
    dict(
        id="CST-001", dir="CST_001", domain="cost", tier=2,
        title="Quality-Cost Tradeoff by Model Tier",
        question="For each call type, what is the quality-cost tradeoff across model tiers?",
        hypothesis="Haiku produces acceptable plan quality for simple single-agent tasks at <20% of the cost of Sonnet.",
        depends_on=[], estimated_cost=5.00, estimated_minutes=45,
    ),
    dict(
        id="CST-002", dir="CST_002", domain="cost", tier=2,
        title="Optimal Planning Orchestrator Tier",
        question="Which model tier produces the best cost-per-compliant-plan ratio for the PlanningOrchestrator?",
        hypothesis="Sonnet produces the optimal cost-per-compliant-plan ratio for multi-agent plans with compliance constraints.",
        depends_on=["CST-001"], estimated_cost=3.00, estimated_minutes=30,
    ),
    dict(
        id="CST-003", dir="CST_003", domain="cost", tier=2,
        title="Full Loop Cost Model",
        question="What is the total cost distribution of a GovernedAgenticLoop run across plan types?",
        hypothesis="90% of workflow costs are incurred in the planning stage; execution stage cost is negligible for mock tools.",
        depends_on=["CST-001", "CST-002"], estimated_cost=4.00, estimated_minutes=45,
    ),
    dict(
        id="CST-004", dir="CST_004", domain="cost", tier=1,
        title="Budget Enforcement Precision",
        question="At what cost granularity does the BudgetTracker enforce limits?",
        hypothesis="BudgetTracker enforces limits to 6 decimal places with no floating-point bypass possible.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="CST-005", dir="CST_005", domain="cost", tier=2,
        title="Replan Cost Overhead",
        question="What is the average additional cost incurred per replan iteration?",
        hypothesis="Each replan iteration adds approximately the same cost as the initial plan call.",
        depends_on=["CST-003"], estimated_cost=2.00, estimated_minutes=30,
    ),
    dict(
        id="CST-006", dir="CST_006", domain="cost", tier=2,
        title="Cost Estimation Accuracy",
        question="How accurately does the PlanningOrchestrator estimate cost before execution?",
        hypothesis="Pre-execution cost estimates are within ±15% of actual incurred costs for standard plan types.",
        depends_on=["CST-003"], estimated_cost=2.00, estimated_minutes=30,
    ),
    dict(
        id="CST-007", dir="CST_007", domain="cost", tier=1,
        title="Mock vs Live Cost Divergence",
        question="How does cost tracking behaviour differ between MockLLMClient and live API runs?",
        hypothesis="MockLLMClient cost tracking is structurally identical to live API cost tracking — the only difference is the source of the cost value.",
        depends_on=["CST-004"], estimated_cost=0.0, estimated_minutes=10,
    ),

    # ── HUMAN-IN-THE-LOOP (HIL) ────────────────────────────────────────────
    dict(
        id="HIL-001", dir="HIL_001", domain="human_in_loop", tier=1,
        title="HITL Gate Trigger Accuracy",
        question="Does the EvaluateStage gate exactly the tasks that match always_gate_action_classes?",
        hypothesis="Every task whose action_class appears in always_gate_action_classes is gated in 100% of cases, and no other task is gated.",
        depends_on=[], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="HIL-002", dir="HIL_002", domain="human_in_loop", tier=1,
        title="HITL Approval Flow Correctness",
        question="Does an approved HumanReviewResponse correctly unblock plan execution?",
        hypothesis="A StubHumanReviewGateway returning approved causes the gated task to execute and the workflow to complete.",
        depends_on=["HIL-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="HIL-003", dir="HIL_003", domain="human_in_loop", tier=1,
        title="HITL Rejection Triggers Replan",
        question="Does a rejected HumanReviewResponse correctly trigger the replan loop?",
        hypothesis="A StubHumanReviewGateway returning rejected causes the loop to replan with the rejection as violation context.",
        depends_on=["HIL-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="HIL-004", dir="HIL_004", domain="human_in_loop", tier=1,
        title="HITL Timeout Behaviour",
        question="How does the loop handle a HITL gateway that times out?",
        hypothesis="A timed-out HumanReviewResponse is treated identically to a rejection and triggers replan.",
        depends_on=["HIL-003"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="HIL-005", dir="HIL_005", domain="human_in_loop", tier=1,
        title="No Gateway Auto-Rejection",
        question="What happens when a plan requires HITL but no gateway is configured?",
        hypothesis="When no HITL gateway is configured, all gated tasks are auto-rejected and the loop escalates after max_replan_attempts.",
        depends_on=["HIL-001"], estimated_cost=0.0, estimated_minutes=10,
    ),
    dict(
        id="HIL-006", dir="HIL_006", domain="human_in_loop", tier=1,
        title="Partial HITL Approval",
        question="Can a reviewer approve some gated tasks and reject others in a single review response?",
        hypothesis="Mixed decisions in HumanReviewResponse correctly allow approved tasks to execute and trigger replan for rejected tasks.",
        depends_on=["HIL-002", "HIL-003"], estimated_cost=0.0, estimated_minutes=15,
    ),
]

# ---------------------------------------------------------------------------
# Template generators
# ---------------------------------------------------------------------------

def make_init(exp_id: str) -> str:
    return f"# experiments.{exp_id.lower().replace('-', '_')}\n"


def make_experiment_md(e: dict) -> str:
    deps = ", ".join(e["depends_on"]) if e["depends_on"] else "none"
    cost_str = f"${e['estimated_cost']:.2f}" + (" (live API)" if e["tier"] == 2 else " (offline)")
    tier_label = "1 (offline — no API key, no Docker)" if e["tier"] == 1 else "2 (requires Docker stack and/or LLM_API_KEY)"
    class_name = e["dir"]

    return f"""# {e["id"]} — {e["title"]}

---

## Identity

| Field              | Value |
|--------------------|-------|
| **Experiment ID**  | {e["id"]} |
| **Domain**         | {e["domain"]} |
| **Tier**           | {tier_label} |
| **Status**         | defined |
| **Claimed by**     | unclaimed |
| **Depends on**     | {deps} |
| **Estimated cost** | {cost_str} |
| **Estimated time** | {e["estimated_minutes"]} minutes |

---

## Research Question

{e["question"]}

---

## Hypothesis

{e["hypothesis"]}

---

## What This Experiment Measures

> TODO: Fill in a 3–5 sentence plain-language description of what
> this experiment actually does. See EXPERIMENT_TEMPLATE.md for guidance.

---

## Metrics

| Metric Key | Type | Unit | Description |
|------------|------|------|-------------|
| `total_runs` | int | — | Total iterations executed |
| `pass_count` | int | — | Iterations matching expected behaviour |
| `fail_count` | int | — | Iterations deviating from expected behaviour |
| `pass_rate`  | float | ratio 0–1 | pass_count / total_runs |

> TODO: Add experiment-specific metrics above.

---

## Prerequisites

**Tier {e["tier"]} — satisfied by RESEARCH_SETUP.md:**
- [ ] Python virtual environment active
- [ ] `pip install -r requirements.txt` complete
- [ ] `pip install -r requirements-dev.txt` complete
- [ ] DAF importable (`python -c "import daf"` succeeds)
- [ ] Research infrastructure importable

{"**Additional for Tier 2:**" + chr(10) + "- [ ] `docker-compose up -d` running" + chr(10) + "- [ ] `LLM_API_KEY` set in `.env`" if e["tier"] == 2 else "**Additional prerequisites:** None — base setup is sufficient."}

---

## Preparation Steps

1. Navigate to the DAF project root and activate venv:
   ```bash
   cd /path/to/daf
   source .venv/bin/activate   # Linux/macOS
   source .venv/Scripts/activate  # Windows Git Bash
   ```

2. Verify readiness:
   ```bash
   python -c "from experiments.{e["domain"]}.{e["dir"]}.experiment import {class_name}; print('ready')"
   ```
   Expected output: `ready`

> TODO: Add any experiment-specific preparation steps.

---

## Execution

```bash
python -m daf.research.runner experiments/{e["domain"]}/{e["dir"]}/experiment.py
```

**Expected duration:** {e["estimated_minutes"]} minutes
**Expected cost:** {cost_str}

---

## Result Recording

```
findings/{e["id"]}/{e["id"]}_run_NNN.log
findings/{e["id"]}/{e["id"]}_run_NNN.json
```

### Checklist:
- [ ] `.log` file ends with `END OF LOG`
- [ ] `.json` is valid JSON
- [ ] `verdict` is `pass`, `fail`, `inconclusive`, or `error`
- [ ] All metrics present
- [ ] `hypothesis_supported` is `true` or `false`

---

## Related Experiments

| Experiment ID | Relationship |
|---------------|-------------|
{"| " + " |\\n| ".join([f"{d} | depends on" for d in e["depends_on"]]) + " |" if e["depends_on"] else "| — | — |"}

---

_Experiment Spec — {e["id"]} — v1.0 — TonyOS Lab_
"""


def make_experiment_py(e: dict) -> str:
    class_name = e["dir"]
    deps_list  = repr(e["depends_on"])
    domain_val = f'Domain.{e["domain"].upper()}'
    tier_val   = "Tier.OFFLINE" if e["tier"] == 1 else "Tier.SERVICES"
    tier_note  = "# Tier 1 — fully offline" if e["tier"] == 1 else "# Tier 2 — requires Docker / LLM_API_KEY"

    return f'''"""
experiments/{e["domain"]}/{e["dir"]}/experiment.py
{'=' * (len(e["domain"]) + len(e["dir"]) + 25)}
{e["id"]} — {e["title"]}

Research Question:
    {e["question"]}

Hypothesis:
    {e["hypothesis"]}

Tier: {e["tier"]} {tier_note}
Depends on: {", ".join(e["depends_on"]) if e["depends_on"] else "none"}
Estimated cost: ${e["estimated_cost"]:.2f}
Estimated time: {e["estimated_minutes"]} minutes

Status: SCAFFOLD — implement prepare(), run(), teardown()
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allows running directly: python experiment.py
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from daf.research.base import (
    BaseExperiment,
    ExperimentResult,
    Verdict,
    {domain_val.split(".")[0]},
    Tier,
)


class {class_name}(BaseExperiment):

    experiment_id       = "{e["id"]}"
    domain              = {domain_val}
    tier                = {tier_val}
    title               = "{e["title"]}"
    research_question   = (
        "{e["question"]}"
    )
    hypothesis          = (
        "{e["hypothesis"]}"
    )
    depends_on          = {deps_list}
    estimated_cost_usd  = {e["estimated_cost"]}
    estimated_minutes   = {e["estimated_minutes"]}

    # ------------------------------------------------------------------
    # Lifecycle — implement these three methods
    # ------------------------------------------------------------------

    async def prepare(self) -> None:
        """
        Set up fixtures, registries, and policy matrix.
        TODO: implement for {e["id"]}.
        """
        raise NotImplementedError(
            f"{{self.experiment_id}}.prepare() is not yet implemented. "
            f"See experiments/{e["domain"]}/{e["dir"]}/EXPERIMENT.md for guidance."
        )

    async def run(self) -> ExperimentResult:
        """
        Execute the experiment and return a structured result.
        TODO: implement for {e["id"]}.
        """
        raise NotImplementedError(
            f"{{self.experiment_id}}.run() is not yet implemented."
        )

    async def teardown(self) -> None:
        """Clean up after run(). May be a no-op."""
        pass  # TODO: add teardown if needed


# ---------------------------------------------------------------------------
# Direct execution entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run {e["id"]}")
    parser.add_argument("--findings-dir", default="findings")
    args = parser.parse_args()

    exp    = {class_name}()
    result = exp.execute(findings_dir=args.findings_dir)

    print(f"\\nVerdict : {{result.verdict.value.upper()}}")
    print(f"Summary : {{result.summary}}")
'''


# ---------------------------------------------------------------------------
# Main scaffold loop
# ---------------------------------------------------------------------------

def scaffold_all():
    created = 0
    for e in EXPERIMENTS:
        domain_dir = EXP_ROOT / e["domain"] / e["dir"]
        domain_dir.mkdir(parents=True, exist_ok=True)

        # __init__.py
        init_path = domain_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text(make_init(e["id"]))

        # EXPERIMENT.md
        md_path = domain_dir / "EXPERIMENT.md"
        if not md_path.exists():
            md_path.write_text(make_experiment_md(e))

        # experiment.py — skip REL-001 (already fully implemented)
        py_path = domain_dir / "experiment.py"
        if not py_path.exists():
            if e["id"] == "REL-001":
                # Copy the full working implementation
                src = Path(__file__).resolve().parents[1] / "experiments" / "reliability" / "REL_001" / "experiment.py"
                if src.exists():
                    py_path.write_text(src.read_text())
                else:
                    py_path.write_text(make_experiment_py(e))
            else:
                py_path.write_text(make_experiment_py(e))

        created += 1
        print(f"  ✓  {e['id']}  {e['title']}")

    print(f"\nScaffolded {created} experiments.")


if __name__ == "__main__":
    print("Scaffolding all 38 DAF research experiments...\n")
    scaffold_all()
