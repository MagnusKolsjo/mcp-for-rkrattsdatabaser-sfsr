-- =============================================================================
-- SFSR MCP-server — databasschema: SQLite
-- (SQLite-filer ger naturlig isolation — inget schema-prefix behövs)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- sfsr_lagar: metadata för varje grundförfattning (ett SFS-nummer = en rad)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sfsr_lagar (
    sfs_nr                      TEXT        PRIMARY KEY,
    rubrik                      TEXT,
    ikraft_grundforfattning      TEXT,                   -- datum som TEXT (SQLite har ingen DATE-typ)
    utfardad_grundforfattning    TEXT,                   -- utfärdandedatum
    upphavd_datum                TEXT,                   -- datum då lagen upphävdes (NULL = gäller fortfarande)
    upphavd_genom                TEXT,                   -- ersättande SFS-nummer (kan saknas)
    departement                  TEXT,                   -- ansvarigt departement
    celex_grundforfattning       TEXT,                   -- kommaseparerade CELEX-nr
    t_o_m_sfs                    TEXT,                   -- "t.o.m. SFS ÅÅÅÅ:NNN" — vilken version som visas
    lagtext                      TEXT,                   -- konsoliderad lagtext
    prop_grundforfattning        TEXT,                   -- bakomliggande proposition för grundförfattningen
    bet_grundforfattning         TEXT,                   -- bakomliggande betänkande för grundförfattningen
    rskr_grundforfattning        TEXT,                   -- riksdagsskrivelse för grundförfattningen
    cachad_vid                   TEXT        NOT NULL DEFAULT (datetime('now')),
    cache_kalla                  TEXT        NOT NULL DEFAULT 'api'
);

-- ---------------------------------------------------------------------------
-- sfsr_andringar: ändrings-SFS per grundförfattning
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sfsr_andringar (
    id                      INTEGER     PRIMARY KEY AUTOINCREMENT,
    sfs_nr                  TEXT        NOT NULL REFERENCES sfsr_lagar (sfs_nr) ON DELETE CASCADE,
    andrings_sfs            TEXT        NOT NULL,
    rubrik                  TEXT,
    ikrafttradande          TEXT,               -- datum som TEXT
    paragrafer              TEXT,
    prop                    TEXT,
    bet                     TEXT,
    rskr                    TEXT,
    celex                   TEXT,               -- kommaseparerade CELEX-nr
    eu_direktiv             INTEGER     NOT NULL DEFAULT 0,   -- 0/1 (SQLite har ingen BOOLEAN)
    overgangsbestammelse    INTEGER     NOT NULL DEFAULT 0,
    historisk               INTEGER     NOT NULL DEFAULT 0,
    borttagen               INTEGER     NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_sfs_nr
    ON sfsr_andringar (sfs_nr);

CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_andrings_sfs
    ON sfsr_andringar (andrings_sfs);

CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_ikrafttradande
    ON sfsr_andringar (ikrafttradande);
