-- =============================================================================
-- Migration v2.0.0 — Döper om kolumner: grundlag → grundförfattning
-- =============================================================================
--
-- Bakgrund: Begreppet "grundlag" (RF, SO, TF, YGL) användes felaktigt som
-- synonym för "grundförfattning" (den ursprungliga lag som ändringar avser).
-- Denna migration döper om de berörda kolumnerna i sfsr_laws.
--
-- Körs mot PostgreSQL (schema sfsr) och SQLite — välj rätt block nedan.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- PostgreSQL
-- ---------------------------------------------------------------------------
-- Kör detta block om du använder PostgreSQL:

ALTER TABLE sfsr.sfsr_laws
    RENAME COLUMN ikraft_grundlag TO ikraft_grundforfattning;

ALTER TABLE sfsr.sfsr_laws
    RENAME COLUMN celex_grundlag TO celex_grundforfattning;

-- ---------------------------------------------------------------------------
-- SQLite
-- ---------------------------------------------------------------------------
-- SQLite < 3.25 saknar stöd för RENAME COLUMN. Kör istället:
--   1. Ta bort den befintliga .db-filen.
--   2. Kör: python db/init_db.py
--   Cachen byggs upp på nytt automatiskt vid nästa anrop till MCP-servern.
--
-- SQLite >= 3.25 (Python 3.8+ inkluderar 3.31+):
--
--   ALTER TABLE sfsr_laws RENAME COLUMN ikraft_grundlag TO ikraft_grundforfattning;
--   ALTER TABLE sfsr_laws RENAME COLUMN celex_grundlag TO celex_grundforfattning;
