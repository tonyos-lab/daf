# Changelog

All notable changes to DAF are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-05-14

### DAF v0.1.0 — First Stable Release

The complete Governed Agentic Loop is implemented and verified.

### Architecture

- **GovernedAgenticLoop** — PLAN → EVALUATE → EXECUTE with self-correction
- **PolicyEngine** — deterministic governance, 8 evaluation dimensions, 98% test coverage
- **PlanningOrchestrator** — provider-agnostic LLM interface (Anthropic first)
- **EvaluateStage** — thin coordinator: PolicyEngine + HITL resolution
- **ExecutionOrchestrator** — real agent execution with ScopedContext
- **InputProcessor** — full validation, sanitization, intent classification
- **OutputAssembler** — terminal audit records, structured FinalResponse

### Runtime Infrastructure

- **BaseTool + ToolRegistry + ScopedToolRegistry** — structural tool permission enforcement
- **BaseAgent + AgentRegistry** — per-sub-task agent instantiation
- **ScopedContext** — immutable agent runtime interface built from ApprovalGrant
- **BudgetTracker** — atomic pre-execution cost enforcement with from_grant()
- **AuditStore** — append-only audit trail (InMemory + PostgreSQL)
- **CheckpointStore** — resumable execution state (InMemory + Redis)
- **HumanReviewGateway** — pluggable HITL delivery (Stub + CLI)

### Models

- AuditRecord (frozen, immutable), AuditEventType
- WorkflowCheckpoint with transition methods
- HumanReviewRequest, HumanReviewResponse, GatedTaskDetail, TaskDecision
- EvaluationOutcome

### Examples

- Example 01: Basic analysis — happy path, full audit trail
- Example 02: Re-planning loop — violation and self-correction
- Example 03: Human escalation gate — HITL approval and rejection flows

### Tests

- 526 tests passing (no API key needed)
- 53 adversarial tests covering 5 security layers
- 35 mocked integration tests covering all three examples
- 11 live integration tests (require LLM_API_KEY)

### Known Limitations

- ExecutionOrchestrator uses sequential task execution (no parallelism)
- Data source clients not yet implemented (data_sources noted but not resolved)
- WebhookHumanReviewGateway is Phase 3 (CLI and Stub available)
- PostgresAuditStore and RedisCheckpointStore require Docker for testing

---

## [Unreleased → 0.1.0]

### Added
- Project scaffold: full repository structure, community files, documentation
- PBAS architecture specification (whitepaper submitted to arXiv)
- DAF Technical Specification v1.0 (component interfaces and data schemas)
- DAF Reference Implementation Guide v1.0 (code patterns and examples)
- PBAS Research Backlog v1.0 (38 experiments across 6 domains)
- PolicyMatrix YAML schema (example configuration)
- Pydantic models: WorkflowRequest, PlanProposal, ApprovalGrant, ViolationReport, AuditRecord
- GovernedAgenticLoop skeleton
- Policy Engine skeleton with evaluation algorithm
- ScopedContext and BudgetTracker skeletons
- Example 01: basic analysis (happy path) — scaffold only

### Research
- REL-001 experiment defined: per-call reliability by type
- CST-001 experiment defined: per-call cost by model tier
- SEC-001 experiment defined: prompt injection resistance
- OBS-001 experiment defined: minimal compliant audit schema

---

## Notes

This project follows a research-driven development model. Changelog entries include both implementation changes and research milestones. Research findings that affect the implementation are noted here.
