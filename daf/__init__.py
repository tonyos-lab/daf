"""
DAF — Deterministic Agentic Framework
Reference implementation of Policy-Based Agentic Systems (PBAS).

The model proposes. The system governs.

Quick start:
    from daf import GovernedAgenticLoop
    from daf.runtime.llm_client import LLMClient, LLMResponse, LLMUsage

    class MyClient(LLMClient):
        async def complete(self, system, user, schema) -> LLMResponse: ...
        def estimate_cost(self, input_tokens, output_tokens) -> float: ...
        @property
        def model_id(self) -> str: ...

    loop = GovernedAgenticLoop(
        llm_client=MyClient(),
        policy_matrix="policies/default.yaml",
    )
    result = await loop.run({"task": "Analyse the contracts"})

DAF is provider-agnostic. Implement LLMClient for any model:
Anthropic, Ollama, OpenAI, Gemini, local models, or any custom backend.

https://github.com/tonyos-lab/daf
"""

__version__ = "0.1.0"
__author__  = "Tony Ochinang"
__license__ = "Apache-2.0"

from daf.loop import GovernedAgenticLoop

__all__ = ["GovernedAgenticLoop"]
