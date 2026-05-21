# Changelog

## [0.2.0] — 2026-05-20

### Added — DAF Stage 2: Multi-Stage Governed Orchestration

**Four cognitive stages** (`daf/stages/`):
- `PlannerStage` — decomposes user task into governed sub-tasks
- `HybridValidator` — two-layer validation: structural check (no LLM) + annotator LLM + rule engine
- `ExecutorStage` — coordinates per-task execution via MCP tool calls
- `CollectorStage` — assembles final response from task outputs

**Rule engine** (`daf/stages/validator.py`):
- `RuleEngine.structural_check()` — synchronous, no LLM, enforces agent/tool/budget permissions
- `RuleEngine.semantic_check()` — evaluates LLM annotations against compliance rules
- Ground truth override — tool governance config overrides LLM annotation (action_class, reversible, may_access_pii)
- Missing annotation gates by default — fails closed

**MCP client** (`daf/mcp/`):
- `MCPClient` — connects MCP servers, discovers tools, applies tool governance at registration
- `DEFAULT_TOOL_GOVERNANCE` — unknown tools receive maximum restriction (write, irreversible, PII, high risk)
- `expose_tools` — only listed tools are registered; unlisted tools cannot be called

**Stage runner** (`daf/engine/runner.py`):
- `StageRunner` — orchestrates all four stages with replan loop
- `StageRunner.from_config()` — accepts `audit_store`, `checkpoint_store`, `hitl_gateway`
- `FinalResponse.cycle_trace` — per-task plan/validation/execution/collection data for UI
- Max iterations hard limit enforced; perpetual rejection escalates

**Audit persistence** (`daf/runtime/`):
- `NullAuditStore` — default, no persistence
- `LogAuditStore` — structured server log output
- `SQLiteAuditStore` — append-only SQLite persistence
- `CompositeAuditStore` — fan-out to multiple stores simultaneously
- Six event types written automatically: WORKFLOW_STARTED, PLAN_PROPOSED, PLAN_EVALUATED,
  STEP_COMPLETED, STEP_FAILED, WORKFLOW_COMPLETED

**Checkpointing** (`daf/runtime/`):
- `NullCheckpointStore` — default, no persistence
- `SQLiteCheckpointStore` — upsert-based SQLite persistence
- Checkpoints written at: execution start, after each task, at HITL gate, after HITL resume
- Failed checkpoints preserved for manual replay
- Completed checkpoints deleted automatically

**Config system** (`daf/config/`):
- `ConfigLoader` — loads `RuntimeConfig` from YAML
- Full config model hierarchy: `RuntimeConfig`, `PolicyConfig`, `OrchestratorConfig`,
  `AgentRoleConfig`, `MCPServerConfig`, `ToolGovernance`, budget/risk/loop policies

**FastAPI app** (`daf/api/`):
- REST API for DAF workflows
- `/workflow/run` — run a workflow
- `/workflow/{id}` — get workflow status
- `/workflow/{id}/approve` — HITL approval endpoint

**Stage 2 tests** (`tests/stage2/`):
- 414 tests across all Stage 2 components
- 24 adversarial tests (LLM injection, rule engine bypass, MCP governance, pipeline integrity)
- 24 audit store tests
- 16 checkpoint store tests

**PBAS v2 whitepaper** (`docs/pbas-v2-whitepaper.md`)

### Fixed
- Inherited v0.1.1 fix: `_apply_ground_truth()` governance path corrected


## [0.1.1] — 2026-05-20

### Fixed
- `daf/stages/validator.py` — `_apply_ground_truth()` now correctly resolves
  tool governance via both flat attributes (Stage 2 `MCPClient` `ToolInfo`) and
  nested `governance` sub-object (v0.1.0 `ToolInfo`). Previously, tools with
  a nested governance object would silently skip ground truth override, allowing
  LLM annotations to stand unchallenged against tool config.
- Extended ground truth override to include `may_access_pii`: a tool flagged
  `may_access_pii=True` in governance config now overrides LLM annotation even
  when the LLM claims `touches_pii=False`.
- Updated `tests/stage2/test_rule_engine.py::test_no_override_when_annotation_matches`
  to include `touches_pii=True` in the annotation, correctly matching the tool's
  `may_access_pii=True` governance config.

### Security
- This fix closes a governance bypass path: without it, a Stage 2 adversarial
  test demonstrated that a tool classified as `delete` in governance config could
  have its annotation left as `read_only` if the `ToolInfo` used nested governance.
  Found and fixed by the Stage 2 adversarial test suite.


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

- 558 tests passing (no API key needed)
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
