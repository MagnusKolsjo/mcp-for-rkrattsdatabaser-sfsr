-- ============================================================
-- stream-08-andringsregister-sfsr: Migration v3.0.0 — ASCII-svenska
-- ============================================================
-- Brytande migration. Renamar tabeller och kolumner i sfsr-schemat
-- så att Python-koden i stream-08 v3.0.0 kan köra mot databasen.
--
-- Idempotent: hjälpfunktionerna kontrollerar mot information_schema och
-- hoppar tysta över rename som redan är applicerade. Säker att köra om.
--
-- Förutsättning: Claude Desktop ska vara stängt så att MCP-servern inte
-- läser/skriver mot tabellerna under transaktionen.
--
-- Backup ska tas FÖRE körning (se STREAM-08-paus-v3_0_0.md).
-- ============================================================

\set ON_ERROR_STOP on

BEGIN;

-- ----------------------------------------------------------
-- Hjälpfunktioner
-- ----------------------------------------------------------

CREATE OR REPLACE FUNCTION pg_temp.byt_tabell(
    p_schema TEXT, p_gammal TEXT, p_ny TEXT
) RETURNS VOID AS $func$
DECLARE
    finns_gammal BOOLEAN;
    finns_ny     BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM information_schema.tables
        WHERE table_schema = p_schema AND table_name = p_gammal) INTO finns_gammal;
    SELECT EXISTS(SELECT 1 FROM information_schema.tables
        WHERE table_schema = p_schema AND table_name = p_ny) INTO finns_ny;
    IF finns_gammal AND NOT finns_ny THEN
        EXECUTE format('ALTER TABLE %I.%I RENAME TO %I', p_schema, p_gammal, p_ny);
        RAISE NOTICE 'Bytte tabell %.% -> %', p_schema, p_gammal, p_ny;
    ELSIF finns_ny AND NOT finns_gammal THEN
        RAISE NOTICE 'Tabell %.% -> % redan applicerad — hoppar', p_schema, p_gammal, p_ny;
    ELSIF NOT finns_ny AND NOT finns_gammal THEN
        RAISE EXCEPTION 'Varken tabell % eller % finns i schema %', p_gammal, p_ny, p_schema;
    ELSE
        RAISE EXCEPTION 'BÅDA tabellerna % och % finns i %, manuell utredning kravs', p_gammal, p_ny, p_schema;
    END IF;
END;
$func$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION pg_temp.byt_kolumn(
    p_schema TEXT, p_tabell TEXT, p_gammal TEXT, p_ny TEXT
) RETURNS VOID AS $func$
DECLARE
    finns_gammal BOOLEAN;
    finns_ny     BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM information_schema.columns
        WHERE table_schema = p_schema AND table_name = p_tabell AND column_name = p_gammal)
        INTO finns_gammal;
    SELECT EXISTS(SELECT 1 FROM information_schema.columns
        WHERE table_schema = p_schema AND table_name = p_tabell AND column_name = p_ny)
        INTO finns_ny;
    IF finns_gammal AND NOT finns_ny THEN
        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN %I TO %I',
                       p_schema, p_tabell, p_gammal, p_ny);
        RAISE NOTICE 'Bytte kolumn %.%.% -> %', p_schema, p_tabell, p_gammal, p_ny;
    ELSIF finns_ny AND NOT finns_gammal THEN
        RAISE NOTICE 'Kolumn %.%.% -> % redan applicerad — hoppar', p_schema, p_tabell, p_gammal, p_ny;
    ELSIF NOT finns_ny AND NOT finns_gammal THEN
        RAISE EXCEPTION 'Varken kolumn % eller % finns i %.%', p_gammal, p_ny, p_schema, p_tabell;
    ELSE
        RAISE EXCEPTION 'BÅDA kolumnerna % och % finns i %.%, manuell utredning kravs',
                        p_gammal, p_ny, p_schema, p_tabell;
    END IF;
END;
$func$ LANGUAGE plpgsql;


-- ----------------------------------------------------------
-- 1) Tabellrenamn
-- ----------------------------------------------------------
SELECT pg_temp.byt_tabell('sfsr', 'sfsr_laws',       'sfsr_lagar');
SELECT pg_temp.byt_tabell('sfsr', 'sfsr_amendments', 'sfsr_andringar');

-- ----------------------------------------------------------
-- 2) Kolumnrenamn i sfsr.sfsr_lagar
-- ----------------------------------------------------------
SELECT pg_temp.byt_kolumn('sfsr', 'sfsr_lagar', 'cached_at',     'cachad_vid');
SELECT pg_temp.byt_kolumn('sfsr', 'sfsr_lagar', 'cache_source',  'cache_kalla');

-- (sfsr_andringar har inga engelska kolumnnamn att rena — alla är redan
--  ASCII-svenska eller vedertagna förkortningar som prop, bet, rskr, celex.)

COMMIT;

-- Efterkontroll (kör utanför transaktionen):
-- \dt sfsr.*           ska visa: sfsr_lagar, sfsr_andringar
-- \d sfsr.sfsr_lagar   ska visa kolumner: sfs_nr, rubrik, ikraft_grundforfattning,
--                       celex_grundforfattning, cachad_vid, cache_kalla
