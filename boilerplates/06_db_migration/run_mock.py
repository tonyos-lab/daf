"""DB Migration Validator — Mock Run
Run: python boilerplates/06_db_migration/run_mock.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import (
    SAFE_MIGRATION_PLAN, DESTRUCTIVE_MIGRATION_PLAN,
    PROD_MIGRATION_PLAN, FORBIDDEN_PLAN,
)
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway

MATRIX = str(Path(__file__).parent / "policy" / "matrix.yaml")

async def run(name, responses, task, gateway=None):
    print(f"\n  {'─'*56}\n  {name}\n  {'─'*56}")
    r = await GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=MATRIX, agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(), audit_store=InMemoryAuditStore(),
        hitl_gateway=gateway,
    ).run({"task": task, "tenant_id": "your-org", "user_id": "dba-lead"})
    print(f"  outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result: print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")
    if gateway and hasattr(gateway, 'requests') and gateway.requests:
        print(f"  HITL: {gateway.requests[-1].gated_task_ids} reviewed")
    if r.escalation_context:
        print(f"  escalation: {r.escalation_context.get('message','')[:55]}")

async def main():
    print("\n══════════════════════════════════════════════════════")
    print("  Boilerplate 06: DB Migration Validator (Mock Mode)")
    print("══════════════════════════════════════════════════════")
    await run("Safe migration — auto-approved (ADD/CREATE only)",
              [SAFE_MIGRATION_PLAN],
              "Validate migration V42__add_user_preferences.sql")
    await run("Destructive migration — DBA gate triggered (DROP/TRUNCATE)",
              [DESTRUCTIVE_MIGRATION_PLAN],
              "Validate migration V43__drop_legacy_table.sql",
              StubHumanReviewGateway(approve_all=True))
    await run("Production migration — senior engineer gate triggered",
              [PROD_MIGRATION_PLAN],
              "Validate production schema migration V44__alter_orders.sql",
              StubHumanReviewGateway(approve_all=True))
    await run("Re-plan: execute_sql not permitted → self-corrects",
              [FORBIDDEN_PLAN, SAFE_MIGRATION_PLAN],
              "Validate and run the migration directly.")
    print("\n══════════════════════════════════════════════════════\n")

if __name__ == "__main__":
    asyncio.run(main())
