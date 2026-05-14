"""
Example 03: Governed Action — Mock Run
Run: python examples/03_governed_action/run_mock.py
"""
import asyncio, sys
from pathlib import Path

root = Path(__file__).parent.parent.parent
example_dir = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(example_dir))

from agents_and_tools import build_agent_registry, build_tool_registry
from mock_responses import GATED_PLAN, UNGATED_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway

MATRIX = str(example_dir / "policy" / "matrix.yaml")


async def run_scenario(name, responses, gateway, task):
    print(f"\n{'─'*55}\n  Scenario: {name}\n{'─'*55}")
    audit_store = InMemoryAuditStore()
    loop = GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX,
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
        hitl_gateway=gateway,
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
    if gateway and hasattr(gateway, "requests") and gateway.requests:
        req = gateway.requests[-1]
        print(f"  HITL request:    {req.task_count} task(s) — {req.gated_task_ids}")
    if result.escalation_context:
        print(f"  Escalation:      {result.escalation_context.get('message','')[:60]}")


async def main():
    print("\n" + "═"*55)
    print("  DAF — Example 03: Governed Action (Mock Mode)")
    print("═"*55)
    await run_scenario(
        "HITL approved → workflow completes",
        [GATED_PLAN], StubHumanReviewGateway(approve_all=True),
        "Generate a report from the documents.",
    )
    await run_scenario(
        "HITL rejected → re-plans with ungated approach → completes",
        [GATED_PLAN, UNGATED_PLAN], StubHumanReviewGateway(approve_all=False),
        "Generate a report from the documents.",
    )
    await run_scenario(
        "HITL timeout → auto-rejected → escalates",
        [GATED_PLAN], StubHumanReviewGateway(simulate_timeout=True),
        "Generate a report from the documents.",
    )
    print(f"\n{'═'*55}\n")

if __name__ == "__main__":
    asyncio.run(main())
