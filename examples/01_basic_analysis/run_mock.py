"""
Example 01: Basic Analysis — Mock Run
Run: python examples/01_basic_analysis/run_mock.py
"""
import asyncio, sys
from pathlib import Path

# Add project root and this example dir to path
root = Path(__file__).parent.parent.parent
example_dir = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(example_dir))

from agents import build_agent_registry          # noqa: E402
from tools import build_tool_registry             # noqa: E402
from mock_responses import (                      # noqa: E402
    HAPPY_PATH_PLAN, OVER_BUDGET_PLAN, FORBIDDEN_TOOL_PLAN,
)
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
    result = await loop.run({
        "task": task, "tenant_id": "example-org", "user_id": "demo",
        "constraints": {"max_cost_usd": 0.50},
    })
    print(f"  Outcome:         {result.outcome}")
    print(f"  Loop iterations: {result.loop_iterations}")
    print(f"  Total cost:      ${result.total_cost_usd:.4f}")
    if result.result:
        print(f"  Steps ({len(result.result)}):")
        for s in result.result:
            icon = "✓" if s["success"] else "✗"
            print(f"    {icon} {s['task_id']}  ${s['cost_usd']:.4f}")
    if result.audit_summary:
        print(f"  Audit events:    {result.audit_summary.get('total_events', 0)}")
    if result.escalation_context:
        msg = result.escalation_context.get("message", "")
        print(f"  Escalation:      {msg[:60]}")


async def main():
    print("\n" + "═"*55)
    print("  DAF — Example 01: Basic Analysis (Mock Mode)")
    print("  No API key required")
    print("═"*55)

    await run_scenario(
        "Happy Path (3 steps, all succeed)",
        [HAPPY_PATH_PLAN],
        "Read the product documents and extract a summary of key features.",
    )
    await run_scenario(
        "Over-Budget Plan (always rejected → escalated)",
        [OVER_BUDGET_PLAN],
        "Perform a comprehensive deep analysis of all documents.",
    )
    await run_scenario(
        "Re-plan (forbidden tool → self-corrects → completed)",
        [FORBIDDEN_TOOL_PLAN, HAPPY_PATH_PLAN],
        "Read documents and write results to the database.",
    )
    print(f"\n{'═'*55}")
    print("  Run with a real API key:")
    print("    python examples/01_basic_analysis/run.py")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    asyncio.run(main())
