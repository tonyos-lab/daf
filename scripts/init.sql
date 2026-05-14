-- DAF Audit Records — append-only
CREATE TABLE IF NOT EXISTS audit_records (
  id              BIGSERIAL PRIMARY KEY,
  audit_id        UUID NOT NULL UNIQUE,
  request_id      UUID NOT NULL,
  tenant_id       TEXT NOT NULL,
  user_id         TEXT NOT NULL,
  event_type      TEXT NOT NULL,
  payload         JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

REVOKE UPDATE, DELETE ON audit_records FROM PUBLIC;

CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_records(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_records(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_records(tenant_id, created_at);

-- Experiment results (R&D use)
CREATE TABLE IF NOT EXISTS experiment_runs (
  id              BIGSERIAL PRIMARY KEY,
  experiment_id   TEXT NOT NULL,
  run_id          UUID NOT NULL UNIQUE,
  research_domain TEXT NOT NULL,
  hypothesis      TEXT NOT NULL,
  parameters      JSONB NOT NULL,
  metrics         JSONB,
  outcome         TEXT,
  notes           TEXT,
  git_commit      TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exp_domain ON experiment_runs(research_domain);
CREATE INDEX IF NOT EXISTS idx_exp_id ON experiment_runs(experiment_id);
