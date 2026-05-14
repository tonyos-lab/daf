"""Multi-Tenant Document Processor — Mock Run
Run: python boilerplates/07_multi_tenant/run_mock.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from agents import build_agent_registry
from tools import build_tool_registry
from mock_responses import TENANT_AWARE_PLAN, COMPLIANT_PLAN
from daf import GovernedAgenticLoop
from daf.testing import MockLLMClient
from daf.runtime.audit_store import InMemoryAuditStore
from daf.runtime.human_review_gateway import StubHumanReviewGateway

POLICY_DIR = Path(__file__).parent / "policy"
TENANT_MATRICES = {
    "standard-tenant": str(POLICY_DIR / "standard_tenant.yaml"),
    "gdpr-tenant":     str(POLICY_DIR / "gdpr_tenant.yaml"),
    "sox-tenant":      str(POLICY_DIR / "sox_tenant.yaml"),
}

async def run(tenant_id, responses, task, gateway=None):
    matrix_path = TENANT_MATRICES[tenant_id]
    print(f"\n  {'─'*56}\n  Tenant: {tenant_id}\n  {'─'*56}")
    r = await GovernedAgenticLoop(
        llm_client=MockLLMClient(responses=responses),
        policy_matrix=matrix_path,
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
        audit_store=InMemoryAuditStore(),
        hitl_gateway=gateway,
    ).run({"task": task, "tenant_id": tenant_id, "user_id": "processor-1"})
    print(f"  outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")
    if r.result:
        for s in r.result: print(f"  {'✓' if s['success'] else '✗'} {s['task_id']}")
    if gateway and hasattr(gateway, 'requests') and gateway.requests:
        print(f"  HITL: {gateway.requests[-1].gated_task_ids}")
    if r.escalation_context:
        print(f"  escalated: {r.escalation_context.get('message','')[:50]}")


async def main():
    print("\n══════════════════════════════════════════════════════════")
    print("  Boilerplate 07: Multi-Tenant Processor (Mock Mode)")
    print("  Same task — three different governance outcomes")
    print("══════════════════════════════════════════════════════════")

    task = "Process the vendor document and extract key entities."

    # Standard tenant: permissive — no compliance rules
    await run("standard-tenant", [TENANT_AWARE_PLAN], task)

    # GDPR tenant: pii_data triggers BLOCK → re-plans with compliant plan
    await run("gdpr-tenant", [TENANT_AWARE_PLAN, COMPLIANT_PLAN], task)

    # SOX tenant: financial_records triggers GATE → human approval
    await run("sox-tenant", [TENANT_AWARE_PLAN], task,
              StubHumanReviewGateway(approve_all=True))

    print("\n══════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    asyncio.run(main())
