-- Build identity is a per-file manifest, never a scalar date.
-- ARCHITECTURE.md findings 1 and 2: no ETag is served, and one build spans ~96s.

CREATE TABLE IF NOT EXISTS builds (
    build_id      VARCHAR PRIMARY KEY,   -- derived label, max(last_modified)::date
    span_seconds  BIGINT,                -- spread of last_modified across files
    file_count    INTEGER,
    status        VARCHAR,               -- 'manifest_only' | 'partial' | 'complete'
    ingested_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS files (
    build_id       VARCHAR,
    filename       VARCHAR,
    last_modified  TIMESTAMP,            -- the only version marker NCBI offers
    content_length BIGINT,
    bytes_received BIGINT,               -- must equal content_length or ingest fails
    sha256         VARCHAR,              -- ours; the server serves no digest
    etag           VARCHAR,              -- always NULL here, recorded to prove it
    rows_parsed    BIGINT,
    rows_rejected  BIGINT,               -- shown on the dashboard, never hidden
    downloaded_at  TIMESTAMP,
    parsed_at      TIMESTAMP,
    PRIMARY KEY (build_id, filename)
);

-- ECD-scoped entity rows. Full-corpus rows are not retained.
CREATE TABLE IF NOT EXISTS entity (
    build_id     VARCHAR,
    pmid         BIGINT,
    type         VARCHAR,
    concept_id   VARCHAR,
    mentions_raw VARCHAR,                -- pipe-delimited as shipped
    resource     VARCHAR,
    source_file  VARCHAR
);

-- Finding 4: Mentions is multi-value in 31.7% of rows. Exploded here, because
-- surface forms are the mechanism behind Experiment 1's number.
CREATE TABLE IF NOT EXISTS mentions (
    build_id   VARCHAR,
    pmid       BIGINT,
    type       VARCHAR,
    concept_id VARCHAR,
    surface    VARCHAR
);

CREATE TABLE IF NOT EXISTS relation (
    build_id VARCHAR,
    pmid     BIGINT,
    rel_type VARCHAR,
    concept1 VARCHAR,
    concept2 VARCHAR
);

-- APPEND-ONLY. Decision 3 consequence: the month-on-month delta cannot be
-- backfilled. If this is ever overwritten instead of appended, the September
-- delta is lost and the dashboard's selling point does not exist until October.
CREATE TABLE IF NOT EXISTS agg_global (
    build_id    VARCHAR,
    source_file VARCHAR,
    metric      VARCHAR,
    value       BIGINT,
    computed_at TIMESTAMP
);

-- Unparseable rows are counted and kept. Never ignore_errors=true and move on.
CREATE TABLE IF NOT EXISTS rejects (
    build_id    VARCHAR,
    source_file VARCHAR,
    line_no     BIGINT,
    reason      VARCHAR,
    raw         VARCHAR
);

-- Audit log of every weekly HEAD check, whether or not it triggered an ingest.
-- More trustworthy than the README, which is three years stale.
CREATE TABLE IF NOT EXISTS head_checks (
    checked_at   TIMESTAMP,
    filename     VARCHAR,
    last_modified TIMESTAMP,
    content_length BIGINT,
    changed      BOOLEAN
);

-- The ECD PMID set from Stage A. Stage B semi-joins against this.
CREATE TABLE IF NOT EXISTS ecd_pmids (
    build_id VARCHAR,
    pmid     BIGINT
);

-- Distinct values of the relation Type column, per build. Settles the README
-- (8 types) against the 2024 NAR paper (12 types) with the file itself.
CREATE TABLE IF NOT EXISTS relation_types (
    build_id VARCHAR,
    rel_type VARCHAR,
    n_rows   BIGINT
);

-- Publication year and journal per ECD paper, from E-utilities. Not in the
-- bulk files at all - they carry PMIDs only - but a literature map without a
-- time axis is not much use to anyone reading about the disease.
CREATE TABLE IF NOT EXISTS pmid_meta (
    build_id VARCHAR,
    pmid     BIGINT,
    year     INTEGER,
    journal  VARCHAR,
    PRIMARY KEY (build_id, pmid)
);
