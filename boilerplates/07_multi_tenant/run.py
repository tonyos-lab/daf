"""Multi-Tenant Document Processor — Real Mode. Requires LLM_API_KEY."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
try:
    from dotenv import load_dotenv; load_dotenv(Path(__file__).parent.parent.parent / ".env")
except: pass
from agents import build_agent_registry
from tools import build_tool_registry
from daf import GovernedAgenticLoop
from daf.runtime.llm_client import LLMClient

# Implement LLMClient for your preferred provider.
# See daf/runtime/llm_client.py for the interface.
#
# Example (Ollama):
#   class MyOllamaClient(LLMClient):
#       async def complete(self, system, user, schema) -> LLMResponse: ...
#       def estimate_cost(self, input_tokens, output_tokens) -> float: ...
#       @property
#       def model_id(self) -> str: ...
from daf.runtime.human_review_gateway import CLIHumanReviewGateway

POLICY_DIR = Path(__file__).parent / "policy"
TENANT_MATRICES = {
    "standard-tenant": str(POLICY_DIR / "standard_tenant.yaml"),
    "gdpr-tenant":     str(POLICY_DIR / "gdpr_tenant.yaml"),
    "sox-tenant":      str(POLICY_DIR / "sox_tenant.yaml"),
}

async def main():
    if not os.getenv("LLM_API_KEY"):
        print("ERROR: LLM_API_KEY not set."); return

    tenant_id = os.getenv("TENANT_ID", "standard-tenant")
    print(f"Running as tenant: {tenant_id}")

    r = await GovernedAgenticLoop(
        llm_client=YOUR_LLM_CLIENT,  # TODO: replace with your LLMClient instance
        policy_matrix=TENANT_MATRICES[tenant_id],
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
        hitl_gateway=CLIHumanReviewGateway(),
    ).run({"task": "Process the vendor document and extract key entities.",
           "tenant_id": tenant_id, "user_id": "processor-1"})
    print(f"outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")



if __name__ == "__main__":
    asyncio.run(main())
