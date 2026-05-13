-- OSI Bridge model store schema.
--
-- Two tables: a current-state row per model name, plus an append-only
-- version log keyed by (name, version). This lets the registry serve the
-- latest model fast while preserving an audit trail of every published
-- contract revision — Schwarz's hackathon brief explicitly wants a Git-like
-- history of OSI/ODCS contracts maintained in the DB.

CREATE TABLE IF NOT EXISTS osi_models (
    name           TEXT PRIMARY KEY,
    description    TEXT,
    source         TEXT,                  -- the dataset source FQN, copied out for filtering
    osi_payload    JSONB        NOT NULL,
    odcs_payload   JSONB,
    confluence_url TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS osi_model_versions (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT         NOT NULL REFERENCES osi_models(name) ON DELETE CASCADE,
    version      INT          NOT NULL,
    osi_payload  JSONB        NOT NULL,
    odcs_payload JSONB,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS osi_models_source_idx
    ON osi_models (source);
