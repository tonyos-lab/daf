# PBAS Research

DAF is developed alongside empirical research validating the PBAS architecture. This directory contains the research backlog, findings, and experiment infrastructure.

---

## Research Domains

| Domain | Experiments | Status |
|---|---|---|
| [Reliability](domains/reliability.md) | REL-001 to REL-007 | Defined |
| [Observability](domains/observability.md) | OBS-001 to OBS-005 | Defined |
| [Orchestration](domains/orchestration.md) | ORC-001 to ORC-006 | Defined |
| [Security](domains/security.md) | SEC-001 to SEC-007 | Defined |
| [Cost](domains/cost.md) | CST-001 to CST-007 | Defined |
| [Human-in-Loop](domains/human-in-loop.md) | HIL-001 to HIL-006 | Defined |

Total: 38 experiments across 6 domains.

---

## Contributing Research

Anyone can run experiments and contribute findings. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the research contribution process.

**To claim an experiment:**
1. Find an unclaimed experiment in the relevant domain file
2. Open an Issue using the Research Finding template
3. Comment "claiming" on the experiment's issue

**To submit findings:**
1. Run the experiment following the BaseExperiment pattern
2. Create `findings/{experiment_id}/` with `metrics.json` and `notes.md`
3. Submit a PR

---

## Findings

Published findings are in [findings/](findings/). Each finding links to its experiment ID, git SHA, and run ID for full reproducibility.

---

## Research Infrastructure

The R&D environment setup (local services, experiment runner, Grafana dashboards) is documented in the [DAF R&D Local Environment Setup guide](https://github.com/daf-framework/daf/releases).

---

## Priority Research Questions

The most important open questions, in order:

1. **(REL-001)** Can per-call reliability be formally characterized as a function of call type and model tier?
2. **(SEC-001)** What is the prompt injection resistance rate of PBAS-compliant implementations versus autonomous agent baselines?
3. **(REL-003)** Under what PolicyMatrix configurations is Governed Agentic Loop termination formally guaranteed?
4. **(CST-001)** For each call type, what is the quality-cost tradeoff across model tiers?
5. **(OBS-001)** What is the minimal audit schema satisfying SOC2, HIPAA, and GDPR simultaneously?

These five establish the empirical foundation that all other experiments depend on.
