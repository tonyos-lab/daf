# DAF Boilerplates

Seven ready-to-run starting points for building governed agentic applications with DAF.

Each boilerplate is **self-contained** — copy it out of this repo and it still works.
Only dependency: `pip install daf`.

---

## Quick Start

```bash
# Run any boilerplate immediately — no API key needed
python boilerplates/01_contract_reviewer/run_mock.py
python boilerplates/05_report_generator/run_mock.py

# Run with a real LLM (add LLM_API_KEY to .env first)
python boilerplates/01_contract_reviewer/run.py
```

---

## The Seven Boilerplates

| # | Project | Use Case | Key DAF Concept |
|---|---|---|---|
| 01 | [Contract Reviewer](01_contract_reviewer/) | Extract payment terms, liability clauses from contracts | Basic happy path — one role, read-only, no gates |
| 02 | [Research Summariser](02_research_summariser/) | Fetch pages, extract claims, produce a research brief | Multi-step with dependencies — two roles |
| 03 | [Support Triage](03_support_triage/) | Classify tickets, draft responses, flag high-value refunds | Compliance rules + conditional HITL gate |
| 04 | [Code Review Assistant](04_code_review/) | Review PR diffs for security, quality, test coverage | Re-planning loop + multiple roles + HITL on security |
| 05 | [Report Generator](05_report_generator/) | Analyse data, generate report, email after approval | Irreversible action gate — mandatory HITL before send |
| 06 | [DB Migration Validator](06_db_migration/) | Analyse SQL scripts, flag DROP/TRUNCATE, require sign-off | Risk policy + compliance rules + destructive action gates |
| 07 | [Multi-Tenant Processor](07_multi_tenant/) | Same DAF instance, different policy per tenant | Per-tenant PolicyMatrix — GDPR, SOX, standard |

---

## Choosing Your Starting Point

**New to DAF?** Start with `01_contract_reviewer` — simplest possible loop, one role, no gates.

**Building something with email/notifications?** Use `05_report_generator` — the irreversible action pattern transfers directly.

**Need compliance rules?** Use `03_support_triage` or `06_db_migration`.

**Multi-tenant SaaS?** Use `07_multi_tenant` — shows per-tenant PolicyMatrix loading.

**Need re-planning?** Use `04_code_review` — shows the self-correction loop with multiple agent roles.

---

## File Structure (every boilerplate)

```
NN_project_name/
  README.md            what it does, how to run, how to test, how to adapt
  policy/
    matrix.yaml        PolicyMatrix — edit this to change governance rules
  mock_responses.py    sample LLM responses for testing without an API key
  agents.py            agent implementations (stubs → replace with real)
  tools.py             tool implementations (stubs → replace with real)
  run_mock.py          runs immediately — no API key, no infrastructure
  run.py               real mode — requires LLM_API_KEY + real tools
```

---

## The Mock ↔ Real Switch

Every boilerplate works in both modes. The switch is one line:

```python
# Mock mode (testing/development)
from daf.testing import MockLLMClient
llm = MockLLMClient(responses=[MY_PLAN])

# Real mode (production)
from daf.runtime.anthropic_client import AnthropicLLMClient
llm = AnthropicLLMClient(api_key=os.getenv("LLM_API_KEY"))

# Everything else is identical
loop = GovernedAgenticLoop(llm_client=llm, ...)
```

---

## Copying a Boilerplate Out of the Repo

```bash
cp -r boilerplates/01_contract_reviewer/ ~/projects/my-contract-reviewer/
cd ~/projects/my-contract-reviewer/
pip install daf
python run_mock.py    # works immediately
```

Each boilerplate only imports from `daf` — no relative imports into the framework.
