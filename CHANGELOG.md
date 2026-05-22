# Ändringslogg

Alla meningsfulla ändringar dokumenteras här.
Formatet följer [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versionshanteringen följer [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [4.0.0] — 2026-05-22

### Brytande ändringar — MCP-verktygsnamn och returstruktur

**Verktyg har döpts om till svenska namn:**
- `sfsr_get_law_history` → `sfsr_hamta_andringshistorik`
- `sfsr_get_paragraph_history` → `sfsr_hamta_paragrafhistorik`
- `sfsr_trace_chain` → `sfsr_folj_andringskedja`

**Server-ID ändrat:** `sfsr` → `sfsr-v2` (för att tvinga cache-bustning i Claude Desktop
vid namnbytet ovan).

**CELEX-fält returneras nu som lista** (`list[str]`) i stället för kommaseparerad sträng.
Gäller `celex_grundforfattning` i `sfsr_hamta_andringshistorik` och `celex` i varje ändring.

**Nytt fält `historisk` exponeras** i varje ändringspost — markerar inaktuella poster
enligt källans API. Fältet filtrerades bort i tidigare versioner.

**Nya metadata-fält** exponeras i `sfsr_hamta_andringshistorik`:
`utfardad_grundforfattning`, `upphavd_datum`, `upphavd_genom`, `departement`, `t_o_m_sfs`,
`prop_grundforfattning`, `bet_grundforfattning`, `rskr_grundforfattning`,
`cache_kalla`, `cachad_vid`.

### Added

- `sfsr_hamta_lagtext` — nytt MCP-verktyg som hämtar konsoliderad lagtext för
  en grundförfattning. Om lagtexten saknas i cachen hämtas posten automatiskt om.

- Nio nya kolumner i `sfsr_lagar`: `utfardad_grundforfattning`, `upphavd_datum`,
  `upphavd_genom`, `departement`, `t_o_m_sfs`, `lagtext`,
  `prop_grundforfattning`, `bet_grundforfattning`, `rskr_grundforfattning`.

- **Grundförfattningens förarbeten exponeras:** Fälten `prop_grundforfattning`,
  `bet_grundforfattning`, `rskr_grundforfattning` parsades i `_till_datamodell_api`
  men returnerades inte. Nu lagras de i databasen och returneras via
  `sfsr_hamta_andringshistorik`. HTML-backenden saknar dessa uppgifter och returnerar `null`.

- `db/migration_v4_0_0.sql` — migrationsskript som lägger till de nya kolumnerna,
  rensar HTML-cachade rader och döper om index till svenska namn.

### Fixed

- **HTTP-transport (Bugg 1):** `mcp.get_asgi_app()` ersatt med
  `mcp.streamable_http_app()` i `_starta_http()` — HTTP-läget fungerar nu korrekt
  med FastMCP Streamable HTTP-protokollet.

- **HTML-scraper SFS-extraktion (Bugg 2):** Regex ändrat till
  `re.search(r"SFS\s+(\d{4}:\d+)", header_text)` för korrekt extraktion av SFS-nummer
  ur rubriktext. Gamla HTML-cachade rader rensas av `migration_v4_0_0.sql`.

- **eu_direktiv-semantik (Bg4):** API-backenden sätter `eu_direktiv` enbart från
  API:ets `eUdirektiv`-flagga, inte från CELEX-närvaro. HTML-backenden saknar
  denna flagga och sätter `eu_direktiv=False` — CELEX-närvaron är fortfarande
  synlig via `celex`-fältet.

- **`initiera_schema()` robust mot nere PG-container:** `try/except Exception`
  omsluter hela DB-init-blocket så att servern fortsätter stå även om
  PostgreSQL-containern är nere vid uppstart. Felet loggas som varning.

- **Deterministisk sortering cache vs. API:** Sekundärnyckeln i `_las_fran_cache`
  ORDER BY ändrad från `andrings_sfs` (lexikografisk) till `SUBSTR(andrings_sfs, 1, 4)`
  (SFS-år) — matchar API-pathens sortering och fungerar i både PostgreSQL och SQLite.

- **Deduplering i HTML-scraper (K13):** `sedda_sfs: set[str]` förhindrar dubbletter
  när HTML-sidan returnerar samma SFS-nummer på flera rader.

- **Normalisering av SFS-nummer (K12):** `_normalisera_sfs` hanterar nu "SFS "-prefix
  och blanksteg runt kolon i SFS-nummer.

### Changed

- **DB-hjälpare standardiserade (K5/K6):** Gamla `_get_pg_conn`, `_get_sqlite_conn`,
  `_is_postgres`, `_tabell_prefix` ersatta av det enhetliga mönstret
  `_ar_postgres()`, `_hamta_db()`, `_ph()`, `_prefix()` — samma mönster som
  övriga MCP-servrar i projektet.

- **DB-init vid serverstart (K7):** `mcp_server.py` anropar `initiera_schema()`
  från `db.py` vid uppstart. Initieringen är robust mot att databasen är otillgänglig
  (try/except, loggas som varning men stoppar inte servern).

- **Schema-SQL samlat i `db/`-katalogen (K7):** Ny `db.py` läser
  `db/schema_postgres.sql` respektive `db/schema_sqlite.sql` vid uppstart.

- **Index döpta om till svenska namn (K8):**
  `idx_sfsr_amendments_*` → `idx_sfsr_andringar_*` i schemafiler och migration.

- **`db/init_db.py` funktionsnamn (K11):**
  `init_postgres` → `initiera_postgres`, `init_sqlite` → `initiera_sqlite`.

- **User-Agent uppdaterad:**
  `Mozilla/5.0 (compatible; sfsr-mcp-bot/1.0)` → projektets korrekta UA-sträng
  `mcp-for-rkrattsdatabaser-sfsr/1.0 (+https://github.com/…)`.

- **Dubbelserialiserat JSON (K10):** Kommentar i `_las_fran_cache` förtydligad —
  beskriver varför defensiv hantering av dubbel-JSON behövs.

- **Licens (K14/K15):** README uppdaterat till `AGPL-3.0` (från `AGPLv3`) och
  kompletterat med en not om att AGPL-3.0 kräver källkodstillgänglighet även vid
  nätverksdrift.

- **ValueError separeras från tekniska fel i `hamta_lag`:** Generisk `except Exception`
  fångade tidigare även `ValueError` ("SFS ej hittat") och aktiverade HTML-fallback,
  vilket ledde till att tomma poster cachades. Nu re-raisas `ValueError` direkt.

- **`cachad_vid` och `cache_kalla` exponeras:** `_las_fran_cache` hämtar nu
  `cachad_vid` ur databasen. Båda fälten returneras via `sfsr_hamta_andringshistorik`.

- **Docsträngar korrigerade:** `sfsr_folj_andringskedja` saknade `rubrik` och
  `overgangsbestammelse`. `sfsr_hamta_andringshistorik` uppdaterad med alla nya fält.

- **Lösenord maskeras i `db/init_db.py`:** `DATABASE_URL` skrivs ut med
  lösenordsdelen ersatt av `***` via `re.sub`. Felgrenen ("okänt URL-format")
  använde `_maskera_url` och lösenordet maskeras nu konsekvent i alla utskriftsgrenar.

- **`cachad_vid` symmetri vid färsk hämtning:** `hamta_lag` sätter
  `data["cachad_vid"]` efter `_spara_i_cache`-anropet — värdet är nu konsistent
  oavsett om data kommer från cache eller färsk API/HTML-hämtning.


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
  automatisk övergång till HTML-skrapning av rkrattsbaser.gov.se
- Lokal cache i PostgreSQL (schema `sfsr`) eller SQLite med konfigurerbar TTL
- Stöd för `MCP_TRANSPORT=stdio` (standard) och `MCP_TRANSPORT=http` med
  Bearer-token-autentisering
- `db/schema_postgres.sql` och `db/schema_sqlite.sql` — databasscheman för
  tabellerna `sfsr_laws` och `sfsr_amendments`
- `db/init_db.py` — initierar databasen, väljer automatiskt PostgreSQL eller SQLite
- `01_explore_sfsr.py` — utforskningsskript för HTML-strukturen
- `02_explore_sfsr_api.py` — utforskningsskript och verifiering av Elasticsearch-API:et
