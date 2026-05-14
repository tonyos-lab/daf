"""
Example 01: Basic Analysis — Happy Path

Demonstrates the complete Phase 2 Governed Agentic Loop:

  Real LLM planning (Anthropic claude-haiku)
  → Real PolicyEngine evaluation
  → StubAgent execution (no real DB needed)
  → Real audit trail (InMemory)
  → Real budget tracking
  → FinalResponse returned

WHAT IS REAL vs STUBBED:
  Real:    LLM planning, PolicyEngine, audit trail, budget tracker
  Stubbed: Agents (StubAgent), Tools (StubTool), DB (no real DB)

WHY STUBS FOR AGENTS/TOOLS:
  Real agents and tools require infrastructure (databases, APIs).
  This example focuses on the governance loop — not the tools.
  Replace StubAgents with real implementations when you have
  real infrastructure connected.

Run:
  python examples/01_basic_analysis/run.py

Requirements:
  LLM_API_KEY set in .env or environment
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load .env if present
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass


def setup_registries():
    """
    Configure the AgentRegistry and ToolRegistry for this example.

    Uses StubAgents and StubTools — replace with real implementations
    once you have infrastructure connected.
    """
    from daf.agents.stub_agent import StubAgent
    from daf.runtime.agent_registry import AgentRegistry
    from daf.runtime.tool_registry import ToolRegistry
    from daf.tools.stub_tool import StubTool

    # ── Tool Registry ────────────────────────────────────────
    tool_registry = ToolRegistry()
    tool_registry.register(StubTool(
        name="read_db",
        idempotent=True,
        output={
            "documents": [
                {"id": 1, "title": "Product Overview",
                 "content": "Our product provides..."},
                {"id": 2, "title": "Technical Specs",
                 "content": "The system supports..."},
                {"id": 3, "title": "Release Notes",
                 "content": "Version 2.0 includes..."},
            ]
        },
    ))
    tool_registry.register(StubTool(
        name="read_file",
        idempotent=True,
        output={"content": "File content here", "size_bytes": 4096},
    ))
    tool_registry.register(StubTool(
        name="llm_extraction",
        idempotent=True,
        output={
            "features": [
                "Multi-tenant support",
                "Real-time processing",
                "Enterprise compliance",
            ]
        },
    ))
    tool_registry.register(StubTool(
        name="llm_summarization",
        idempotent=True,
        output={"summary": "Product delivers real-time processing with compliance."},
    ))
    tool_registry.register(StubTool(
        name="llm_generation",
        idempotent=True,
        output={"report": "Generated report content"},
    ))
    tool_registry.register(StubTool(
        name="llm_evaluation",
        idempotent=True,
        output={"score": 0.85, "confidence": 0.90},
    ))
    tool_registry.register(StubTool(
        name="write_file",
        idempotent=False,
        output={"written": True, "path": "/tmp/output.json"},
    ))

    # ── Agent Registry ───────────────────────────────────────
    agent_registry = AgentRegistry()

    class AnalystAgent(StubAgent):
        """Analyst agent — reads documents and extracts information."""
        role = "analyst"
        def __init__(self):
            super().__init__(
                role="analyst",
                output={
                    "extracted_features": [
                        "Multi-tenant support",
                        "Real-time processing",
                        "Enterprise compliance",
                        "99.9% uptime SLA",
                        "API-first architecture",
                    ],
                    "document_count": 3,
                    "confidence": 0.92,
                },
                cost_usd=0.02,
            )

    agent_registry.register(AnalystAgent)

    return agent_registry, tool_registry


async def main():
    """Run Example 01: Basic Analysis."""
    from daf import GovernedAgenticLoop
    from daf.runtime.anthropic_client import AnthropicLLMClient

    print("\n" + "═" * 60)
    print("  DAF — Example 01: Basic Analysis")
    print("  Phase 2 End-to-End Demonstration")
    print("═" * 60)

    # Check API key
    if not os.getenv("LLM_API_KEY"):
        print("\n  ERROR: LLM_API_KEY not set.")
        print("  Copy .env.example to .env and add your Anthropic API key.")
        print("  Or run the unit test version: make test-unit")
        return

    # Set up registries
    agent_registry, tool_registry = setup_registries()
    print(f"\n  Registered tools:  {tool_registry.names()}")
    print(f"  Registered agents: {agent_registry.roles()}")

    # Build the loop
    client = AnthropicLLMClient(
        api_key=os.getenv("LLM_API_KEY"),
        model=os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001"),
    )

    loop = GovernedAgenticLoop(
        llm_client=client,
        policy_matrix="policy/matrix/example.yaml",
        agent_registry=agent_registry,
        tool_registry=tool_registry,
    )

    print("\n  Running workflow...")
    print("  Task: Read the product documents and extract a summary of key features")
    print()

    result = await loop.run({
        "task": (
            "Read the product documents and extract a summary of key features. "
            "Focus on capabilities that enterprise customers would care about."
        ),
        "tenant_id": "example-org",
        "user_id":   "demo-user",
        "constraints": {
            "max_cost_usd": 0.50,
        },
    })

    # Display results
    print("═" * 60)
    print(f"  Outcome:         {result.outcome}")
    print(f"  Loop iterations: {result.loop_iterations}")
    print(f"  Total cost:      ${result.total_cost_usd:.4f}")

    if result.result:
        print(f"\n  Step results ({len(result.result)} steps):")
        for step in result.result:
            status = "✓" if step["success"] else "✗"
            print(f"    {status} {step['task_id']} (${step['cost_usd']:.4f})")

    if result.audit_summary:
        print(f"\n  Audit summary:")
        print(f"    Total events: {result.audit_summary.get('total_events', 0)}")
        for event, count in result.audit_summary.get("event_counts", {}).items():
            print(f"    {event}: {count}")

    if result.escalation_context:
        print(f"\n  Escalation: {result.escalation_context.get('message', '')}")

    print("═" * 60)
    print()


if __name__ == "__main__":
    asyncio.run(main())
