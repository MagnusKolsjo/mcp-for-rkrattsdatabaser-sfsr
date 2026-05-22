-- =============================================================================
-- SFSR MCP-server — migration till v4.0.0
-- Kör mot PostgreSQL med: psql <DATABASE_URL> -f db/migration_v4_0_0.sql
-- Skriptet är idempotent och säkert att köra om.
-- =============================================================================
--
-- Vad migrationen gör:
--   1. Lägger till nio nya kolumner i sfsr.sfsr_lagar
--   2. Tar bort HTML-cachade rader (gamla scraper-buggar — dessa hämtas om)
--   3. Döper om index till svenska namn (idx_sfsr_amendments_* → idx_sfsr_andringar_*)
--
-- SQLite-instruktioner finns som kommentarer längst ner i filen.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Steg 1: Lägg till nya kolumner i sfsr.sfsr_lagar
-- Kolumnerna är nullable — befintliga rader får NULL och fylls på vid nästa
-- cache-hämtning via API:et.
-- -----------------------------------------------------------------------------

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS utfardad_grundforfattning  DATE;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS upphavd_datum              DATE;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS upphavd_genom              TEXT;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS departement                TEXT;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS t_o_m_sfs                  TEXT;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS lagtext                    TEXT;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS prop_grundforfattning      TEXT;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS bet_grundforfattning       TEXT;

ALTER TABLE sfsr.sfsr_lagar
    ADD COLUMN IF NOT EXISTS rskr_grundforfattning      TEXT;

-- -----------------------------------------------------------------------------
-- Steg 2: Rensa HTML-cachade rader
-- Gamla HTML-hämtningar kan ha felaktiga SFS-nummer (bugg i scraper v1–v3).
-- Raderna hämtas om automatiskt vid nästa anrop tack vare den fixade scrapern.
-- ON DELETE CASCADE i sfsr_andringar hanterar borttagningen av ändringsrader.
-- -----------------------------------------------------------------------------

DELETE FROM sfsr.sfsr_lagar
WHERE cache_kalla = 'html';

-- -----------------------------------------------------------------------------
-- Steg 3: Döp om index till svenska namn
-- Från v1.0.0 heter indexen idx_sfsr_amendments_* (engelska). De skapades på
-- den gamla sfsr_amendments-tabellen och följde med vid rename till sfsr_andringar.
-- Nya installationer (v3+) har redan rätt namn — DROP IF EXISTS är säkert.
-- -----------------------------------------------------------------------------

DROP INDEX IF EXISTS sfsr.idx_sfsr_amendments_sfs_nr;
DROP INDEX IF EXISTS sfsr.idx_sfsr_amendments_andrings_sfs;
DROP INDEX IF EXISTS sfsr.idx_sfsr_amendments_ikrafttradande;

CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_sfs_nr
    ON sfsr.sfsr_andringar (sfs_nr);

CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_andrings_sfs
    ON sfsr.sfsr_andringar (andrings_sfs);

CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_ikrafttradande
    ON sfsr.sfsr_andringar (ikrafttradande);

-- =============================================================================
-- SQLite-instruktioner (kör dessa manuellt mot SQLite-databasen om du använder
-- SQLite som backend; SQLite stödjer inte ALTER TABLE ADD COLUMN IF NOT EXISTS
-- i äldre versioner, men kommandona är i övrigt giltiga SQLite-syntax)
-- =============================================================================
--
-- ALTER TABLE sfsr_lagar ADD COLUMN utfardad_grundforfattning TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN upphavd_datum             TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN upphavd_genom             TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN departement               TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN t_o_m_sfs                 TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN lagtext                   TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN prop_grundforfattning     TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN bet_grundforfattning      TEXT;
-- ALTER TABLE sfsr_lagar ADD COLUMN rskr_grundforfattning     TEXT;
--
-- DELETE FROM sfsr_lagar WHERE cache_kalla = 'html';
--
-- DROP INDEX IF EXISTS idx_sfsr_amendments_sfs_nr;
-- DROP INDEX IF EXISTS idx_sfsr_amendments_andrings_sfs;
-- DROP INDEX IF EXISTS idx_sfsr_amendments_ikrafttradande;
--
-- CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_sfs_nr
--     ON sfsr_andringar (sfs_nr);
-- CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_andrings_sfs
--     ON sfsr_andringar (andrings_sfs);
-- CREATE INDEX IF NOT EXISTS idx_sfsr_andringar_ikrafttradande
--     ON sfsr_andringar (ikrafttradande);
-- =============================================================================
