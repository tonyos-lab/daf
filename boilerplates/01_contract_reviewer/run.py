"""
Contract Reviewer — Real Mode
Requires: LLM_API_KEY in environment or .env file
Run: python boilerplates/01_contract_reviewer/run.py
"""
import asyncio, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv; load_dotenv(env_file)
    except ImportError:
        pass

from agents import build_agent_registry
from tools import build_tool_registry
from daf import GovernedAgenticLoop
from daf.runtime.anthropic_client import AnthropicLLMClient

MATRIX = str(Path(__file__).parent / "policy" / "matrix.yaml")


async def main():
    if not os.getenv("LLM_API_KEY"):
        print("ERROR: LLM_API_KEY not set. Run in mock mode:")
        print("  python boilerplates/01_contract_reviewer/run_mock.py")
        return

    loop = GovernedAgenticLoop(
        llm_client=AnthropicLLMClient(api_key=os.getenv("LLM_API_KEY")),
        policy_matrix=MATRIX,
        agent_registry=build_agent_registry(),
        tool_registry=build_tool_registry(),
    )
    result = await loop.run({
        "task": (
            "Review the vendor contract and extract: payment terms, "
            "liability cap, notice period, governing law, and risk level."
        ),
        "tenant_id": "your-org",
        "user_id":   "analyst-1",
        "constraints": {"max_cost_usd": 0.50},
    })
    print(f"Outcome:    {result.outcome}")
    print(f"Iterations: {result.loop_iterations}")
    print(f"Cost:       ${result.total_cost_usd:.4f}")
    if result.result:
        for step in result.result:
            print(f"  {'✓' if step['success'] else '✗'} {step['task_id']}")

if __name__ == "__main__":
    asyncio.run(main())
