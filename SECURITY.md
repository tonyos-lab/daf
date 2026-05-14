# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| main branch | ✅ |
| Tagged releases | ✅ Current release only |

---

## Reporting a Vulnerability

**Do not report security vulnerabilities via GitHub Issues.** Issues are public. A public vulnerability report gives attackers information before a fix is available.

### How to report

Email: **security@daf-framework.org**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix if you have one

### What to expect

- **Acknowledgement**: within 48 hours
- **Assessment**: within 7 days
- **Fix timeline**: depends on severity (critical: 7 days, high: 30 days, medium: 90 days)
- **Credit**: reporters are credited in the release notes unless they prefer anonymity

---

## Security Model

DAF's security architecture is built on three independent enforcement layers:

**Layer 1 — Prompt structure**
Instructions and untrusted data are separated in all LLM calls. Tool outputs, user data, and retrieved content are classified as Zone 3 (untrusted) and never enter system prompt context.

**Layer 2 — Policy Engine evaluation**
Every Plan Proposal is evaluated by the deterministic Policy Engine before any execution authority is granted. A manipulated proposal is still subject to full policy evaluation regardless of how it was generated.

**Layer 3 — ScopedContext enforcement**
Agents are instantiated with exactly the tool and data clients granted by the Approval Grant. An agent cannot invoke an unpermitted tool regardless of model instruction or adversarial content — the client does not exist in its context.

An attacker must defeat all three layers simultaneously. Each layer is independent.

---

## Known Limitations

- Policy Engine correctness depends on the completeness of the PolicyMatrix configuration. Incomplete policies produce gaps in coverage.
- Planning Orchestrator prompt injection resistance at Layer 1 is defense-in-depth, not a hard guarantee. Layers 2 and 3 provide the hard guarantees.
- DAF does not currently provide cryptographic integrity verification of LLM outputs. This is on the roadmap.

---

## Responsible Disclosure

We follow coordinated disclosure. We will work with reporters to ensure fixes are available before public disclosure. We will not take legal action against researchers who follow this policy in good faith.
