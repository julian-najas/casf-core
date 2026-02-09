CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY,

  request_id UUID NOT NULL,
  event_id   UUID NOT NULL,
  ts         TIMESTAMPTZ NOT NULL DEFAULT now(),

  actor      TEXT NOT NULL,
  action     TEXT NOT NULL,
  decision   TEXT NOT NULL,

  payload    JSONB NOT NULL,

  prev_hash  TEXT NOT NULL DEFAULT '',
  hash       TEXT NOT NULL,

  CONSTRAINT uq_audit_event_id UNIQUE (event_id),
  CONSTRAINT uq_audit_hash UNIQUE (hash)
);

CREATE INDEX IF NOT EXISTS idx_audit_request_ts
  ON audit_events (request_id, ts);

CREATE INDEX IF NOT EXISTS idx_audit_ts
  ON audit_events (ts);
