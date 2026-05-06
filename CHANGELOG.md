# Ändringslogg

Alla meningsfulla ändringar dokumenteras här.
Formatet följer [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versionshanteringen följer [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.0.0] — 2026-05-06

### Brytande ändringar — databas och Python-API

**Databas-rename i schemat `sfsr`** — kräver migration via
`db/migration_v3_0_0.sql`. Skriptet är idempotent och säkert att köra om.

Tabeller:
- `sfsr_laws` → `sfsr_lagar`
- `sfsr_amendments` → `sfsr_andringar`

Kolumner i `sfsr.sfsr_lagar`:
- `cached_at` → `cachad_vid`
- `cache_source` → `cache_kalla`

**Python-identifierare** — 13 unika identifierare med å/ä/ö flyttade till
ASCII-svenska. Berörda filer: `01_explore_sfsr.py` och `02_explore_sfsr_api.py`
(utforskningsskript). Bland byten:
- `hämta_sfsr` → `hamta_sfsr`
- `hämta_via_api` → `hamta_via_api`
- `_parse_celex_ändring` → `_parse_celex_andring`
- `_parse_förarbeten` → `_parse_forarbeten`
- `råa_ändringar` → `raa_andringar`
- `källdata` → `kalldata`
- `värde` → `varde`
- `med_överg` → `med_overg`

Kärnkoden (`mcp_server.py`, `sfsr_tools.py`, `sfsr_scraper.py`, `db/init_db.py`)
hade inga identifierare med å/ä/ö — bara SQL-strängarna behövde uppdateras med
nya tabell- och kolumnnamn.

### Tekniskt

- Ny `db/migration_v3_0_0.sql` med PL/pgSQL-helperfunktioner
  `pg_temp.byt_tabell` och `pg_temp.byt_kolumn` som är idempotenta.
- `db/schema_postgres.sql` och `db/schema_sqlite.sql` uppdaterade — nya
  installationer skapas direkt med svenska namn.



## [2.0.0] — 2026-05-03

### Changed (brytande)

- Kolumnen `ikraft_grundlag` i `sfsr_laws` döpt om till `ikraft_grundforfattning`
- Kolumnen `celex_grundlag` i `sfsr_laws` döpt om till `celex_grundforfattning`
- JSON-fälten `ikraft_grundlag` och `celex_grundlag` i MCP-verktygssvar döpta
  om till `ikraft_grundforfattning` respektive `celex_grundforfattning`

### Fixed

- Terminologifel genomgående i kod och dokumentation: "grundlag" (konstitution)
  användes felaktigt som synonym för "grundförfattning" (den ursprungliga lag som
  ändringsposterna avser). Grundlag avser enbart de fyra konstitutionella lagarna
  (RF, SO, TF, YGL) och får inte användas i vidare betydelse.

### Added

- `db/migration_v2_0_0.sql` — migrationsskript som döper om kolumnerna i
  befintliga PostgreSQL-databaser (SQLite-instruktioner inkluderade som kommentar)

## [1.0.0] — 2026-05-03

### Added

- `sfsr_get_law_history` — hämtar hela ändringshistoriken för en lag med
  ikraftträdandedatum, berörda paragrafer och förarbeten
- `sfsr_get_paragraph_history` — filtrerar ändringar som berör en specifik paragraf
- `sfsr_trace_chain` — returnerar ändringskedjan i omvänd kronologisk ordning
  med propositionsreferenser för vidare uppslag
- Dual-backend: Elasticsearch-API på beta.rkrattsbaser.gov.se (primär) med
  automatisk fallback till HTML-skrapning av rkrattsbaser.gov.se
- Lokal cache i PostgreSQL (schema `sfsr`) eller SQLite med konfigurerbar TTL
- Stöd för `MCP_TRANSPORT=stdio` (standard) och `MCP_TRANSPORT=http` med
  Bearer-token-autentisering
- `db/schema_postgres.sql` och `db/schema_sqlite.sql` — databasscheman för
  tabellerna `sfsr_laws` och `sfsr_amendments`
- `db/init_db.py` — initierar databasen, väljer automatiskt PostgreSQL eller SQLite
- `01_explore_sfsr.py` — utforskningsskript för HTML-strukturen
- `02_explore_sfsr_api.py` — utforskningsskript och verifiering av Elasticsearch-API:et
