# DAF Roadmap

DAF is developed in parallel with empirical research validating the PBAS architecture. The roadmap reflects both implementation milestones and research milestones.

---

## Phase 1 — Foundation (Current)

**Goal:** Funder-ready, developer-readable project. Architecture specified, community infrastructure in place.

- [x] PBAS architecture specification (whitepaper)
- [x] DAF Technical Specification (component interfaces and schemas)
- [x] Reference Implementation Guide (code patterns)
- [x] GitHub repository with full community infrastructure
- [x] PBAS Research Backlog (38 experiments defined)
- [ ] Submit PBAS whitepaper to arXiv
- [ ] Policy Engine — core implementation
- [ ] PolicyMatrix schema and YAML loader
- [ ] PlanProposal and ApprovalGrant Pydantic models
- [ ] Basic GovernedAgenticLoop skeleton
- [ ] Example 01: basic analysis (happy path)

**Target:** Q2 2026

---

## Phase 2 — Core Loop

**Goal:** Complete Governed Agentic Loop running end-to-end with all three worked examples functional.

- [ ] Planning Orchestrator with Anthropic API integration
- [ ] Full Policy Engine evaluation (all 8 dimensions)
- [ ] Execution Orchestrator with scoped agent instantiation
- [ ] ScopedContext enforcement (runtime API-level)
- [ ] BudgetTracker with atomic compare-and-swap
- [ ] CheckpointStore with Redis backend
- [ ] AuditStore with PostgreSQL append-only backend
- [ ] Example 02: re-planning loop (violation scenario)
- [ ] Example 03: governed action (human escalation gate)
- [ ] Unit test suite (>90% coverage on Policy Engine)
- [ ] Adversarial test suite (injection resistance)

**Research milestones (parallel):**
- REL-001: per-call reliability benchmark
- SEC-001: prompt injection resistance baseline
- CST-001: per-call cost by model tier

**Target:** Q3 2026

---

## Phase 3 — Research Validation

**Goal:** Key PBAS claims empirically validated. First research findings published.

- [ ] Wave 1 experiments complete (REL-001, CST-001, OBS-001, SEC-002)
- [ ] Wave 2 experiments complete
- [ ] First findings document published
- [ ] Go/No-Go checkpoint 1 passed
- [ ] Docker Compose local environment published
- [ ] Grafana dashboards for experiment metrics
- [ ] OpenTelemetry observability integration

**Target:** Q4 2026

---

## Phase 4 — Community and Adoption

**Goal:** Active community, real-world deployments, NLnet/Anthropic funding secured.

- [ ] Wave 3–5 experiments complete
- [ ] Full PBAS Research Backlog completed
- [ ] DAF v1.0 stable release
- [ ] Plugin architecture for custom agent roles and tools
- [ ] Policy Engine visual configuration tool
- [ ] NLnet / Anthropic funding secured
- [ ] AISG Singapore collaboration established
- [ ] Community contributor programme launched
- [ ] First external organization deploying DAF in production

**Target:** Q1–Q2 2027

---

## Phase 5 — Ecosystem

**Goal:** DAF as the standard reference implementation for governed AI systems.

- [ ] DAF v2.0 with multi-agent coordination
- [ ] TypeScript / JavaScript port
- [ ] Policy Matrix marketplace (community-contributed policies)
- [ ] Cloud-native deployment templates (AWS, GCP, Azure)
- [ ] Linux Foundation or Apache Foundation hosting consideration
- [ ] Academic course materials using DAF
- [ ] Enterprise reference deployments documented

**Target:** 2027+

---

## Research Roadmap

The full experiment schedule is defined in [docs/research/README.md](docs/research/README.md). Research and implementation proceed in parallel — research findings feed directly into implementation decisions.

| Domain | Experiments | Timeline |
|---|---|---|
| Reliability | REL-001 to REL-007 | Weeks 1-8 |
| Observability | OBS-001 to OBS-005 | Weeks 1-8 |
| Orchestration | ORC-001 to ORC-006 | Weeks 1-12 |
| Security | SEC-001 to SEC-007 | Weeks 1-12 |
| Cost | CST-001 to CST-007 | Weeks 1-12 |
| Human-in-Loop | HIL-001 to HIL-006 | Weeks 4-16 |

---

## What Is Not on the Roadmap

- **Commercial products built on DAF** — DAF is and will remain open source
- **Proprietary model integrations** — DAF supports any LLM provider with structured output; no vendor lock-in
- **Autonomous agent mode** — DAF explicitly rejects this paradigm; it is not a roadmap item

---

## Suggesting Roadmap Items

Open a [Discussion](https://github.com/daf-framework/daf/discussions) in the Ideas category. Roadmap decisions are made transparently per the [Governance](GOVERNANCE.md) process.
