"""Report Generator — Mock Run
Run: python boilerplates/05_report_generator/run_mock.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import FULL_REPORT_PLAN, ANALYSE_ONLY_PLAN, FORBIDDEN_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway

MATRIX = str(Path(__file__).parent / "policy" / "matrix.yaml")

async def run(name, responses, task, gateway=None):
    print(f"\n  {'─'*55}\n  {name}\n  {'─'*55}")
    r = await GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX, agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(), audit_store=InMemoryAuditStore(),
        hitl_gateway=gateway,
    ).run({"task": task, "tenant_id": "your-org", "user_id": "finance-director"})
    print(f"  outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result: print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")
    if gateway and hasattr(gateway, 'requests') and gateway.requests:
        print(f"  HITL: {gateway.requests[-1].gated_task_ids} reviewed")

async def main():
    print("\n══════════════════════════════════════════════════════")
    print("  Boilerplate 05: Report Generator (Mock Mode)")
    print("══════════════════════════════════════════════════════")
    await run("Full report — approved and sent",
              [FULL_REPORT_PLAN],
              "Analyse Q1 sales data and generate a report for the board.",
              StubHumanReviewGateway(approve_all=True))
    await run("Full report — human rejects → re-plans without generation",
              [FULL_REPORT_PLAN, ANALYSE_ONLY_PLAN],
              "Analyse Q1 sales data and generate a report.",
              StubHumanReviewGateway(approve_all=False))
    await run("Analyse only — no generation gate",
              [ANALYSE_ONLY_PLAN],
              "Analyse the Q1 data and return the key metrics.")
    await run("Re-plan: wrong role for send_email → self-corrects",
              [FORBIDDEN_PLAN, FULL_REPORT_PLAN],
              "Read data and email report directly.",
              StubHumanReviewGateway(approve_all=True))
    print("\n══════════════════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
