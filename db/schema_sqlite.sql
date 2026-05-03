-- =============================================================================
-- Arbetsström 8 — SFSR ändringsregister
-- Databasschema: SQLite
-- (SQLite-filer ger naturlig isolation — inget schema-prefix behövs)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- sfsr_laws: metadata för varje grundlag (ett SFS-nummer = en rad)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sfsr_laws (
    sfs_nr              TEXT        PRIMARY KEY,
    rubrik              TEXT,
    ikraft_grundlag     TEXT,                   -- datum som TEXT (SQLite har ingen DATE-typ)
    celex_grundlag      TEXT,
    cached_at           TEXT        NOT NULL DEFAULT (datetime('now')),
    cache_source        TEXT        NOT NULL DEFAULT 'api'
);

-- ---------------------------------------------------------------------------
-- sfsr_amendments: ändrings-SFS per grundlag
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sfsr_amendments (
    id                      INTEGER     PRIMARY KEY AUTOINCREMENT,
    sfs_nr                  TEXT        NOT NULL REFERENCES sfsr_laws (sfs_nr) ON DELETE CASCADE,
    andrings_sfs            TEXT        NOT NULL,
    rubrik                  TEXT,
    ikrafttradande          TEXT,               -- datum som TEXT
    paragrafer              TEXT,
    prop                    TEXT,
    bet                     TEXT,
    rskr                    TEXT,
    celex                   TEXT,
    eu_direktiv             INTEGER     NOT NULL DEFAULT 0,   -- 0/1 (SQLite har ingen BOOLEAN)
    overgangsbestammelse    INTEGER     NOT NULL DEFAULT 0,
    historisk               INTEGER     NOT NULL DEFAULT 0,
    borttagen               INTEGER     NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sfsr_amendments_sfs_nr
    ON sfsr_amendments (sfs_nr);

CREATE INDEX IF NOT EXISTS idx_sfsr_amendments_andrings_sfs
    ON sfsr_amendments (andrings_sfs);

CREATE INDEX IF NOT EXISTS idx_sfsr_amendments_ikrafttradande
    ON sfsr_amendments (ikrafttradande);
