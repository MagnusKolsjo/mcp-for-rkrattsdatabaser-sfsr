-- =============================================================================
-- Arbetsström 8 — SFSR ändringsregister
-- Databasschema: PostgreSQL
-- Schema (namespace): sfsr
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS sfsr;

-- ---------------------------------------------------------------------------
-- sfsr_laws: metadata för varje grundförfattning (ett SFS-nummer = en rad)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sfsr.sfsr_laws (
    sfs_nr              TEXT        PRIMARY KEY,            -- t.ex. "1993:1617"
    rubrik              TEXT,                               -- lagens officiella namn
    ikraft_grundforfattning     DATE,                               -- ikraftträdandedatum för grundförfattningen
    celex_grundforfattning      TEXT,                               -- radbrytningsseparerade CELEX-nr (kan vara tomt)
    cached_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- tidpunkt för senaste hämtning
    cache_source        TEXT        NOT NULL DEFAULT 'api'  -- 'api' eller 'html'
);

-- ---------------------------------------------------------------------------
-- sfsr_amendments: ändrings-SFS per grundförfattning (ett ändrings-SFS = en rad)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sfsr.sfsr_amendments (
    id                      BIGSERIAL   PRIMARY KEY,
    sfs_nr                  TEXT        NOT NULL REFERENCES sfsr.sfsr_laws (sfs_nr) ON DELETE CASCADE,
    andrings_sfs            TEXT        NOT NULL,           -- t.ex. "2010:622"
    rubrik                  TEXT,                           -- ändringslagens namn (kan saknas)
    ikrafttradande          DATE,                           -- ikraftträdandedatum (kan saknas)
    paragrafer              TEXT,                           -- berörda paragrafer i fritext, t.ex. "1 §, 2 kap. 3-5 §§"
    prop                    TEXT,                           -- bakomliggande proposition, t.ex. "prop. 2010/11:47"
    bet                     TEXT,                           -- bakomliggande betänkande
    rskr                    TEXT,                           -- riksdagsskrivelse
    celex                   TEXT,                           -- kommaseparerade CELEX-nr (kan vara tomt)
    eu_direktiv             BOOLEAN     NOT NULL DEFAULT FALSE,   -- genomför EU-direktiv
    overgangsbestammelse    BOOLEAN     NOT NULL DEFAULT FALSE,   -- har övergångsbestämmelse
    historisk               BOOLEAN     NOT NULL DEFAULT FALSE,   -- historisk (inaktuell) post
    borttagen               BOOLEAN     NOT NULL DEFAULT FALSE    -- borttagen post
);

CREATE INDEX IF NOT EXISTS idx_sfsr_amendments_sfs_nr
    ON sfsr.sfsr_amendments (sfs_nr);

CREATE INDEX IF NOT EXISTS idx_sfsr_amendments_andrings_sfs
    ON sfsr.sfsr_amendments (andrings_sfs);

CREATE INDEX IF NOT EXISTS idx_sfsr_amendments_ikrafttradande
    ON sfsr.sfsr_amendments (ikrafttradande);
