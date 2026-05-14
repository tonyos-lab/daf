"""Support Triage — Mock Run
Run: python boilerplates/03_support_triage/run_mock.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import TRIAGE_PLAN, CLASSIFY_ONLY_PLAN, FORBIDDEN_TOOL_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway

MATRIX = str(Path(__file__).parent / "policy" / "matrix.yaml")

async def run(name, responses, task, gateway=None):
    print(f"\n  {'─'*52}\n  {name}\n  {'─'*52}")
    r = await GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX, agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(), audit_store=InMemoryAuditStore(),
        hitl_gateway=gateway,
    ).run({"task": task, "tenant_id": "your-org", "user_id": "support-lead"})
    print(f"  outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result: print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")
    if gateway and hasattr(gateway, 'requests') and gateway.requests:
        req = gateway.requests[-1]
        print(f"  HITL: {req.task_count} task(s) reviewed — {req.gated_task_ids}")

async def main():
    print("\n══════════════════════════════════════════════════════")
    print("  Boilerplate 03: Support Triage (Mock Mode)")
    print("══════════════════════════════════════════════════════")
    await run("Full triage — draft approved by human",
              [TRIAGE_PLAN], "Triage ticket TKT-2847 and draft a response.",
              StubHumanReviewGateway(approve_all=True))
    await run("Classify only — no draft needed",
              [CLASSIFY_ONLY_PLAN], "Classify ticket TKT-2847 urgency and category.")
    await run("Re-plan: forbidden tool → self-corrects",
              [FORBIDDEN_TOOL_PLAN, TRIAGE_PLAN],
              "Read ticket and send auto-reply immediately.",
              StubHumanReviewGateway(approve_all=True))
    print("\n══════════════════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
