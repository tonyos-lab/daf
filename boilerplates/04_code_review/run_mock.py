"""Code Review Assistant — Mock Run
Run: python boilerplates/04_code_review/run_mock.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import FULL_REVIEW_PLAN, SECURITY_ONLY_PLAN, REPLAN_TRIGGER_PLAN
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
    ).run({"task": task, "tenant_id": "your-org", "user_id": "senior-dev"})
    print(f"  outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result: print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")
    if gateway and hasattr(gateway, 'requests') and gateway.requests:
        print(f"  HITL: reviewed {gateway.requests[-1].gated_task_ids}")

async def main():
    print("\n══════════════════════════════════════════════════════")
    print("  Boilerplate 04: Code Review Assistant (Mock Mode)")
    print("══════════════════════════════════════════════════════")
    await run("Full review + comment approved",
              [FULL_REVIEW_PLAN], "Review PR #142 for security and quality.",
              StubHumanReviewGateway(approve_all=True))
    await run("Security scan only (no comment gate)",
              [SECURITY_ONLY_PLAN], "Quick security scan of PR #142.")
    await run("Re-plan: wrong role/tool → self-corrects",
              [REPLAN_TRIGGER_PLAN, FULL_REVIEW_PLAN],
              "Security reviewer generates the comment directly.",
              StubHumanReviewGateway(approve_all=True))
    print("\n══════════════════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
