"""
Example 02: Re-planning Loop — Mock Run
Run: python examples/02_replan_loop/run_mock.py
"""
import asyncio, sys
from pathlib import Path

root = Path(__file__).parent.parent.parent
example_dir = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(example_dir))

from agents_and_tools import build_agent_registry, build_tool_registry
from mock_responses import FORBIDDEN_PLAN, REVISED_PLAN, ALWAYS_FORBIDDEN_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore

MATRIX = str(example_dir / "policy" / "matrix.yaml")


async def run_scenario(name, responses, task):
    print(f"\n{'─'*55}\n  Scenario: {name}\n{'─'*55}")
    audit_store = InMemoryAuditStore()
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX,
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
        audit_store=audit_store,
    )
    result = await loop.run({"task": task, "tenant_id": "example-org", "user_id": "demo"})
    print(f"  Outcome:         {result.outcome}")
    print(f"  Loop iterations: {result.loop_iterations}")
    if result.result:
        steps = ", ".join(
            ("✓" if s["success"] else "✗") + " " + s["task_id"]
            for s in result.result
        )
        print(f"  Steps ({len(result.result)}):    {steps}")
    if result.escalation_context:
        print(f"  Escalation:      {result.escalation_context.get('message','')[:60]}")


async def main():
    print("\n" + "═"*55)
    print("  DAF — Example 02: Re-planning Loop (Mock Mode)")
    print("═"*55)
    await run_scenario(
        "Re-plan: forbidden tool → self-corrects → completed",
        [FORBIDDEN_PLAN, REVISED_PLAN],
        "Read documents and write results to the database.",
    )
    await run_scenario(
        "Escalation: always-forbidden → max attempts → escalated",
        [ALWAYS_FORBIDDEN_PLAN],
        "Must write data to the database.",
    )
    print(f"\n{'═'*55}\n")

if __name__ == "__main__":
    asyncio.run(main())
