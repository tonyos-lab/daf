"""
Contract Reviewer — Mock Run
Run: python boilerplates/01_contract_reviewer/run_mock.py
"""
import asyncio, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import STANDARD_CONTRACT_PLAN, MINIMAL_PLAN, FORBIDDEN_TOOL_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore

MATRIX = str(Path(__file__).parent / "policy" / "matrix.yaml")


async def run_scenario(name, responses, task):
    print(f"\n  {'─'*50}\n  {name}\n  {'─'*50}")
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX,
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
        audit_store=InMemoryAuditStore(),
    )
    r = await loop.run({"task": task, "tenant_id": "your-org", "user_id": "analyst-1"})
    print(f"  outcome:    {r.outcome}")
    print(f"  iterations: {r.loop_iterations}")
    print(f"  cost:       ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result:
            print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")
    if r.escalation_context:
        print(f"  escalation: {r.escalation_context.get('message','')[:55]}")


async def main():
    print("\n══════════════════════════════════════════════════════")
    print("  DAF Boilerplate 01: Contract Reviewer (Mock Mode)")
    print("══════════════════════════════════════════════════════")
    await run_scenario(
        "Standard contract review (3 steps)",
        [STANDARD_CONTRACT_PLAN],
        "Review the vendor contract and extract payment terms, liability clauses, and risk level.",
    )
    await run_scenario(
        "Minimal review (1 step)",
        [MINIMAL_PLAN],
        "Quick extraction of all key terms from the contract.",
    )
    await run_scenario(
        "Re-plan: forbidden tool → self-corrects",
        [FORBIDDEN_TOOL_PLAN, STANDARD_CONTRACT_PLAN],
        "Extract contract terms and store in database.",
    )
    print("\n══════════════════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
