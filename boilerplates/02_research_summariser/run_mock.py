"""Research Summariser — Mock Run
Run: python boilerplates/02_research_summariser/run_mock.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import MULTI_SOURCE_PLAN, SINGLE_SOURCE_PLAN, FORBIDDEN_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore

MATRIX = str(Path(__file__).parent / "policy" / "matrix.yaml")

async def run(name, responses, task):
    print(f"\n  {'─'*50}\n  {name}\n  {'─'*50}")
    r = await GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX, agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(), audit_store=InMemoryAuditStore(),
    ).run({"task": task, "tenant_id": "your-org", "user_id": "researcher-1"})
    print(f"  outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result: print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")

async def main():
    print("\n══════════════════════════════════════════════")
    print("  Boilerplate 02: Research Summariser (Mock)")
    print("══════════════════════════════════════════════")
    await run("Multi-source research brief (4 steps)", [MULTI_SOURCE_PLAN],
              "Research the state of the AI market. Fetch 3 sources and produce a brief.")
    await run("Single source summary (2 steps)", [SINGLE_SOURCE_PLAN],
              "Summarise this article: https://example.com/article-1")
    await run("Re-plan: role/tool mismatch → self-corrects", [FORBIDDEN_PLAN, MULTI_SOURCE_PLAN],
              "Fetch and analyse sources in one combined step.")
    print("\n══════════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
