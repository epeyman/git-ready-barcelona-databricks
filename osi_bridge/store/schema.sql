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

-- Access-request log — the Phase 4 portal records each Request-access click
-- here, and the provisioning service appends one osi_access_grants row per
-- engine it tried. Together they are the audit trail Schwarz's portal needs.

CREATE TABLE IF NOT EXISTS osi_access_requests (
    id            TEXT PRIMARY KEY,
    model         TEXT          NOT NULL,
    requester     TEXT          NOT NULL,
    justification TEXT,
    status        TEXT          NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS osi_access_grants (
    id          BIGSERIAL PRIMARY KEY,
    request_id  TEXT         NOT NULL REFERENCES osi_access_requests(id) ON DELETE CASCADE,
    engine      TEXT         NOT NULL,
    status      TEXT         NOT NULL,  -- granted | skipped | failed
    detail      TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS osi_access_requests_model_idx
    ON osi_access_requests (model);
CREATE INDEX IF NOT EXISTS osi_access_grants_request_idx
    ON osi_access_grants (request_id);
