CREATE TABLE IF NOT EXISTS batches (
    batch_id text PRIMARY KEY,
    title text NOT NULL,
    is_test boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS revisions (
    entity_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    batch_id text NOT NULL REFERENCES batches(batch_id),
    kind text NOT NULL CHECK (kind IN ('source','claim','evidence','assessment','note','review')),
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL,
    PRIMARY KEY (entity_id, revision)
);
CREATE TABLE IF NOT EXISTS requests (
    request_id text PRIMARY KEY,
    batch_id text NOT NULL REFERENCES batches(batch_id),
    payload_hash text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE VIEW current_records AS
SELECT DISTINCT ON (entity_id) * FROM revisions ORDER BY entity_id, revision DESC;
CREATE INDEX IF NOT EXISTS revisions_batch_kind ON revisions(batch_id, kind);
CREATE INDEX IF NOT EXISTS revisions_search ON revisions USING gin
    (to_tsvector('simple', payload::text));

CREATE OR REPLACE FUNCTION deny_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Revisions are append-only';
END;
$$;
DROP TRIGGER IF EXISTS revisions_immutable ON revisions;
CREATE TRIGGER revisions_immutable BEFORE UPDATE OR DELETE ON revisions
FOR EACH ROW EXECUTE FUNCTION deny_revision_mutation();

CREATE TABLE IF NOT EXISTS document_snapshots (
    source_id uuid NOT NULL,
    source_revision integer NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    request_hash text NOT NULL UNIQUE,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, source_revision, revision),
    FOREIGN KEY (source_id, source_revision) REFERENCES revisions(entity_id, revision)
);
DROP TRIGGER IF EXISTS document_snapshots_immutable ON document_snapshots;
CREATE TRIGGER document_snapshots_immutable BEFORE UPDATE OR DELETE ON document_snapshots
FOR EACH ROW EXECUTE FUNCTION deny_revision_mutation();

CREATE TABLE IF NOT EXISTS extraction_jobs (
    request_hash text PRIMARY KEY,
    source_id uuid NOT NULL,
    source_revision integer NOT NULL,
    configuration text NOT NULL,
    state text NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued', 'running', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    error text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (source_id, source_revision) REFERENCES revisions(entity_id, revision)
);
