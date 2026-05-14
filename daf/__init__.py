"""
DAF — Deterministic Agentic Framework
Reference implementation of Policy-Based Agentic Systems (PBAS).

The model proposes. The system governs.

Quick start:
    from daf import GovernedAgenticLoop
    from daf.runtime.anthropic_client import AnthropicLLMClient

    client = AnthropicLLMClient(api_key="sk-ant-...")
    loop = GovernedAgenticLoop(
        llm_client=client,
        policy_matrix="policy/matrix/example.yaml",
    )
    result = await loop.run({"task": "Analyse the contracts"})

https://github.com/tonyos-lab/daf
https://arxiv.org/abs/XXXX.XXXXX
"""

__version__ = "0.1.0"
__author__  = "[YOUR NAME]"
__license__ = "Apache-2.0"

from daf.loop import GovernedAgenticLoop

__all__ = ["GovernedAgenticLoop"]
