# Quickstart

Get DAF running locally in 15 minutes.

---

## Prerequisites

- Python 3.11+
- Docker Desktop (for local services)
- Anthropic API key ([get one here](https://console.anthropic.com))

---

## Install

```bash
git clone https://github.com/daf-framework/daf
cd daf
python -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows WSL2
pip install -r requirements.txt
```

---

## Configure

```bash
cp .env.example .env
```

Edit `.env`:

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...          # Your Anthropic API key
LLM_MODEL=claude-sonnet-4-20250514
```

---

## Start local services

```bash
make services-up
```

This starts PostgreSQL (audit store) and Redis (checkpoints) in Docker. Takes about 30 seconds.

---

## Run your first example

```bash
python examples/01_basic_analysis/run.py
```

You will see:

```
[DAF] Planning Orchestrator generating plan...
[DAF] Policy Engine evaluating proposal...
[DAF] All checks passed. Approval granted.
[DAF] Execution Orchestrator running 3 sub-tasks...
[DAF] Step ST-01 complete: document_reader ✓
[DAF] Step ST-02 complete: risk_analyzer ✓
[DAF] Step ST-03 complete: report_writer ✓
[DAF] Workflow complete. Cost: $0.07. Iterations: 1.

Result:
---
[Structured analysis output]
---

Audit record written to: audit_records table
```

---

## Try the re-planning example

```bash
python examples/02_replan_loop/run.py
```

This example intentionally triggers a policy violation and shows the loop self-correcting.

---

## Define your own PolicyMatrix

Copy the example and edit it:

```bash
cp policy/matrix/example.yaml policy/matrix/my_project.yaml
```

Edit `my_project.yaml` to define your agent roles, permitted tools, budget limits, and compliance rules.

Then use it:

```python
loop = GovernedAgenticLoop(
    policy_matrix="policy/matrix/my_project.yaml"
)
```

---

## Run the tests

```bash
make test-unit           # fast, no API calls
make test-adversarial    # security tests
make test-integration    # requires .env and services-up
```

All three test suites must pass before contributing code.

---

## Next steps

- [Architecture](architecture.md) — understand PBAS before extending DAF
- [Policy Matrix Reference](policy-matrix.md) — configure governance for your use case
- [Contributing](../CONTRIBUTING.md) — how to contribute code or research
- [Research Backlog](research/README.md) — run experiments and contribute findings
