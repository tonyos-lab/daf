"""Support Triage — Real Mode. Requires LLM_API_KEY."""
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
from daf.runtime.anthropic_client import AnthropicLLMClient
from daf.runtime.human_review_gateway import CLIHumanReviewGateway

async def main():
    if not os.getenv("LLM_API_KEY"):
        print("ERROR: LLM_API_KEY not set."); return
    r = await GovernedAgenticLoop(
        llm_client=AnthropicLLMClient(api_key=os.getenv("LLM_API_KEY")),
        policy_matrix=str(Path(__file__).parent / "policy" / "matrix.yaml"),
        agent_registry=build_agent_registry(), tool_registry=build_tool_registry(),
        hitl_gateway=CLIHumanReviewGateway(),
    ).run({"task": "Triage the latest support ticket and draft a response.",
           "tenant_id": "your-org", "user_id": "support-lead"})
    print(f"outcome: {r.outcome}  iterations: {r.loop_iterations}  cost: ${r.total_cost_usd:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
