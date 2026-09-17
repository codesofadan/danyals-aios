-- SEO-AUDIT-OS SQLite schema
-- One DB file: data/seo_audit.db
-- Per-audit raw artifacts live as files under data/audits/<domain>/<run_id>/raw/

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ----- Audit runs (one row per /audit invocation) -----
CREATE TABLE IF NOT EXISTS audit_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid        TEXT NOT NULL UNIQUE,
    domain          TEXT NOT NULL,
    profile         TEXT NOT NULL DEFAULT 'general',   -- local | ecommerce | saas | content | general
    command         TEXT NOT NULL,                      -- /audit, /audit-quick, /audit-local, ...
    args_json       TEXT NOT NULL,                      -- raw flags
    status          TEXT NOT NULL DEFAULT 'pending',    -- pending | running | succeeded | failed | cancelled
    started_at      TEXT NOT NULL,                      -- ISO-8601 PKT
    finished_at     TEXT,
    duration_sec    REAL,
    pages_crawled   INTEGER DEFAULT 0,
    overall_score   REAL,
    on_page_score   REAL,
    technical_score REAL,
    off_page_score  REAL,
    local_score     REAL,
    api_cost_usd    REAL DEFAULT 0,
    artifact_dir    TEXT NOT NULL,                      -- data/audits/<domain>/<run_uuid>/
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_runs_domain ON audit_runs(domain);
CREATE INDEX IF NOT EXISTS idx_audit_runs_status ON audit_runs(status);
CREATE INDEX IF NOT EXISTS idx_audit_runs_started ON audit_runs(started_at DESC);

-- ----- Pages discovered during a run -----
CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    canonical_url   TEXT,
    page_type       TEXT,                               -- homepage | service | location | blog | contact | ...
    http_status     INTEGER,
    response_ms     INTEGER,
    title           TEXT,
    meta_description TEXT,
    h1              TEXT,
    word_count      INTEGER,
    indexable       INTEGER,                            -- 0/1
    crawl_depth     INTEGER,
    is_orphan       INTEGER DEFAULT 0,
    last_modified   TEXT,
    discovered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, url)
);
CREATE INDEX IF NOT EXISTS idx_pages_run ON pages(run_id);
CREATE INDEX IF NOT EXISTS idx_pages_url ON pages(url);

-- ----- Findings (one row per check evaluation per audit) -----
CREATE TABLE IF NOT EXISTS findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    page_id         INTEGER REFERENCES pages(id) ON DELETE SET NULL,  -- NULL for site-level findings
    check_id        TEXT NOT NULL,                      -- e.g. ON-001, TECH-042, OFF-007, LOC-013
    check_name      TEXT NOT NULL,
    category        TEXT NOT NULL,                      -- on-page | technical | off-page | local-seo
    subcategory     TEXT,
    owner_agent     TEXT NOT NULL,                      -- M1..M4, A1..A5, B1..B5, C1..C4, D1..D4
    status          TEXT NOT NULL,                      -- pass | warn | fail | n_a
    severity        TEXT NOT NULL,                      -- critical | major | minor | info
    score           REAL,                               -- 0-10
    confidence      REAL,                               -- 0.0-1.0
    evidence_json   TEXT,                               -- raw value(s), elements, line ranges
    remediation     TEXT,                               -- one-paragraph fix
    references_json TEXT,                               -- URLs cited
    impact_usd      REAL,                               -- projected monthly $-impact (optional)
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_check ON findings(check_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity, status);
CREATE INDEX IF NOT EXISTS idx_findings_owner ON findings(owner_agent);

-- ----- API call log (for cost tracking + rate limit awareness) -----
CREATE TABLE IF NOT EXISTS api_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,                      -- moz | serper | citations_serper | psi | crux | google_places | google_nl
    endpoint        TEXT NOT NULL,
    method          TEXT NOT NULL DEFAULT 'GET',
    request_hash    TEXT,                               -- for dedup / cache
    status_code     INTEGER,
    latency_ms      INTEGER,
    cost_usd        REAL DEFAULT 0,
    cached          INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    called_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_api_calls_run ON api_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_api_calls_provider ON api_calls(provider);

-- ----- Agent runs (telemetry for each Claude subagent invocation) -----
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    agent_id        TEXT NOT NULL,                      -- M1..M4, A1..A5, B1..B5, C1..C4, D1..D4
    agent_name      TEXT NOT NULL,
    team            TEXT NOT NULL,                      -- meta | onpage | technical | offpage | local
    status          TEXT NOT NULL,                      -- queued | running | succeeded | failed
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_sec    REAL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL DEFAULT 0,
    findings_count  INTEGER DEFAULT 0,
    quality_score   REAL,                               -- 0.0-1.0, from L1/L2/L3 gates
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_run ON agent_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_id);

-- ----- Backlinks snapshot (per audit, optional, big table) -----
CREATE TABLE IF NOT EXISTS backlinks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    source_url          TEXT NOT NULL,
    target_url          TEXT NOT NULL,
    source_domain       TEXT NOT NULL,
    anchor_text         TEXT,
    is_dofollow         INTEGER,
    is_sponsored        INTEGER,
    is_ugc              INTEGER,
    source_da           REAL,
    source_spam_score   REAL,
    discovered_at       TEXT,
    lost_at             TEXT,
    snapshot_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_backlinks_run ON backlinks(run_id);
CREATE INDEX IF NOT EXISTS idx_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX IF NOT EXISTS idx_backlinks_target_url ON backlinks(target_url);

-- ----- Schema blocks discovered per page -----
CREATE TABLE IF NOT EXISTS schema_blocks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    page_id             INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    schema_type         TEXT NOT NULL,                  -- LocalBusiness | Article | FAQPage | Service | Product | BreadcrumbList | ...
    raw_json_ld         TEXT NOT NULL,
    is_valid            INTEGER,
    validation_errors   TEXT,
    rich_result_eligible INTEGER,
    extracted_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_schema_blocks_run ON schema_blocks(run_id);
CREATE INDEX IF NOT EXISTS idx_schema_blocks_page ON schema_blocks(page_id);
CREATE INDEX IF NOT EXISTS idx_schema_blocks_type ON schema_blocks(schema_type);

-- ----- Citations (GBP and local directory presence) -----
CREATE TABLE IF NOT EXISTS citations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    source_name         TEXT NOT NULL,                  -- Yelp, Foursquare, Apple, Bing, Localeze, Acxiom, ...
    source_url          TEXT,
    name                TEXT,                           -- as listed on the source
    address             TEXT,
    phone               TEXT,
    is_nap_consistent   INTEGER,
    nap_match_score     REAL,                           -- 0.0-1.0
    last_checked        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_citations_run ON citations(run_id);

-- ----- Reviews snapshot -----
CREATE TABLE IF NOT EXISTS reviews_snapshot (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    platform            TEXT NOT NULL,                  -- google | yelp | facebook | bbb | ...
    total_count         INTEGER,
    average_rating      REAL,
    velocity_per_month  REAL,
    response_rate       REAL,
    last_review_at      TEXT,
    sentiment_positive  REAL,
    sentiment_negative  REAL,
    snapshot_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews_snapshot(run_id);

-- ----- Rankings snapshot -----
CREATE TABLE IF NOT EXISTS rankings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    keyword             TEXT NOT NULL,
    location            TEXT,                           -- "Lahore, Pakistan" or geo-grid id like "31.520,74.358:1mi"
    position            INTEGER,
    url                 TEXT,
    serp_features_json  TEXT,                           -- featured_snippet, local_pack, ai_overview, ...
    checked_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rankings_run ON rankings(run_id);
CREATE INDEX IF NOT EXISTS idx_rankings_keyword ON rankings(keyword);
