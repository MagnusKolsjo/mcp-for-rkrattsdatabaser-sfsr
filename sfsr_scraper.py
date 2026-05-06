"""
sfsr_scraper.py — Hämtar och cachar SFSR-data (Svensk författningssamlings register)

Stöder två backends, styrda via miljövariabeln SFSR_BACKEND:
  - "api"  (standard): anropar beta.rkrattsbaser.gov.se Elasticsearch-API — strukturerad JSON
  - "html"             : skrapar rkrattsbaser.gov.se med BeautifulSoup4 — reserv om API:et ändras

Resultaten cachelagras i SQLite eller PostgreSQL (beroende på DATABASE_URL).
Cache-TTL styrs av SFSR_CACHE_TTL_HOURS (standard: 24 h).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
DATABASE_URL        = os.getenv("DATABASE_URL", "sqlite:///sfsr_cache.db")
SFSR_BACKEND        = os.getenv("SFSR_BACKEND", "api").lower()
SFSR_BASE_URL       = os.getenv("SFSR_BASE_URL", "https://rkrattsbaser.gov.se/sfsr")
SFSR_API_URL        = os.getenv(
    "SFSR_API_URL",
    "https://beta.rkrattsbaser.gov.se/elasticsearch/SearchEsByRawJson"
)
SFSR_CACHE_TTL_HOURS = int(os.getenv("SFSR_CACHE_TTL_HOURS", "24"))
USER_AGENT          = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; sfsr-mcp-bot/1.0)"
)

# ---------------------------------------------------------------------------
# Hjälpfunktioner — gemensamma
# ---------------------------------------------------------------------------

def _normalisera_sfs(sfs_nr: str) -> str:
    """Normaliserar SFS-nummer till formatet ÅÅÅÅ:NNN (t.ex. '1993:1617')."""
    return sfs_nr.strip()


def _tabell_prefix() -> str:
    """Returnerar rätt tabellprefix beroende på databastyp."""
    if DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://"):
        return "sfsr."
    return ""


# ---------------------------------------------------------------------------
# Databasanslutning
# ---------------------------------------------------------------------------

def _get_pg_conn():
    """Öppnar en PostgreSQL-anslutning."""
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        log.error("psycopg2 saknas. Kör: pip install psycopg2-binary")
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL)


def _get_sqlite_conn() -> sqlite3.Connection:
    """Öppnar en SQLite-anslutning."""
    db_path = DATABASE_URL.replace("sqlite:///", "")
    return sqlite3.connect(db_path)


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")


# ---------------------------------------------------------------------------
# Cache-hantering
# ---------------------------------------------------------------------------

def _cache_giltig(sfs_nr: str) -> bool:
    """Returnerar True om en färsk cache-post finns för sfs_nr."""
    p = _tabell_prefix()
    ttl_grans = datetime.now(timezone.utc) - timedelta(hours=SFSR_CACHE_TTL_HOURS)

    if _is_postgres():
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT cachad_vid FROM {p}sfsr_lagar WHERE sfs_nr = %s",
                (sfs_nr,)
            )
            rad = cur.fetchone()
        conn.close()
        if rad is None:
            return False
        cachad_vid = rad[0]
        if cachad_vid.tzinfo is None:
            cachad_vid = cachad_vid.replace(tzinfo=timezone.utc)
        return cachad_vid >= ttl_grans
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            f"SELECT cachad_vid FROM {p}sfsr_lagar WHERE sfs_nr = ?",
            (sfs_nr,)
        )
        rad = cur.fetchone()
        conn.close()
        if rad is None:
            return False
        cachad_vid = datetime.fromisoformat(rad[0]).replace(tzinfo=timezone.utc)
        return cachad_vid >= ttl_grans


def _spara_i_cache(data: dict) -> None:
    """Sparar hämtad SFSR-data i databasen (ersätter eventuell befintlig post)."""
    p = _tabell_prefix()
    sfs_nr = data["sfs_nr"]
    nu = datetime.now(timezone.utc).isoformat()

    if _is_postgres():
        conn = _get_pg_conn()
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # Radera gamla poster (CASCADE tar hand om sfsr_andringar)
                cur.execute(f"DELETE FROM {p}sfsr_lagar WHERE sfs_nr = %s", (sfs_nr,))
                cur.execute(
                    f"""INSERT INTO {p}sfsr_lagar
                        (sfs_nr, rubrik, ikraft_grundforfattning, celex_grundforfattning, cachad_vid, cache_kalla)
                        VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        sfs_nr,
                        data.get("rubrik"),
                        data.get("ikraft_grundforfattning"),
                        data.get("celex_grundforfattning"),
                        nu,
                        data.get("cache_kalla", SFSR_BACKEND),
                    ),
                )
                for a in data.get("andringar", []):
                    cur.execute(
                        f"""INSERT INTO {p}sfsr_andringar
                            (sfs_nr, andrings_sfs, rubrik, ikrafttradande, paragrafer,
                             prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse,
                             historisk, borttagen)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            sfs_nr,
                            a.get("andrings_sfs"),
                            a.get("rubrik"),
                            a.get("ikrafttradande"),
                            a.get("paragrafer"),
                            a.get("prop"),
                            a.get("bet"),
                            a.get("rskr"),
                            a.get("celex"),
                            a.get("eu_direktiv", False),
                            a.get("overgangsbestammelse", False),
                            a.get("historisk", False),
                            a.get("borttagen", False),
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
    else:
        conn = _get_sqlite_conn()
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(f"DELETE FROM {p}sfsr_lagar WHERE sfs_nr = ?", (sfs_nr,))
            conn.execute(
                f"""INSERT INTO {p}sfsr_lagar
                    (sfs_nr, rubrik, ikraft_grundforfattning, celex_grundforfattning, cachad_vid, cache_kalla)
                    VALUES (?,?,?,?,?,?)""",
                (
                    sfs_nr,
                    data.get("rubrik"),
                    data.get("ikraft_grundforfattning"),
                    data.get("celex_grundforfattning"),
                    nu,
                    data.get("cache_kalla", SFSR_BACKEND),
                ),
            )
            for a in data.get("andringar", []):
                conn.execute(
                    f"""INSERT INTO {p}sfsr_andringar
                        (sfs_nr, andrings_sfs, rubrik, ikrafttradande, paragrafer,
                         prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse,
                         historisk, borttagen)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sfs_nr,
                        a.get("andrings_sfs"),
                        a.get("rubrik"),
                        a.get("ikrafttradande"),
                        a.get("paragrafer"),
                        a.get("prop"),
                        a.get("bet"),
                        a.get("rskr"),
                        a.get("celex"),
                        1 if a.get("eu_direktiv") else 0,
                        1 if a.get("overgangsbestammelse") else 0,
                        1 if a.get("historisk") else 0,
                        1 if a.get("borttagen") else 0,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def _las_fran_cache(sfs_nr: str) -> dict | None:
    """Läser en lag med alla dess andringar från cachen."""
    p = _tabell_prefix()

    if _is_postgres():
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT sfs_nr, rubrik, ikraft_grundforfattning, celex_grundforfattning FROM {p}sfsr_lagar WHERE sfs_nr = %s",
                (sfs_nr,)
            )
            lag = cur.fetchone()
            if lag is None:
                conn.close()
                return None
            cur.execute(
                f"""SELECT andrings_sfs, rubrik, ikrafttradande, paragrafer,
                           prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse,
                           historisk, borttagen
                    FROM {p}sfsr_andringar
                    WHERE sfs_nr = %s
                    ORDER BY ikrafttradande NULLS LAST, andrings_sfs""",
                (sfs_nr,)
            )
            andringar = cur.fetchall()
        conn.close()
    else:
        conn = _get_sqlite_conn()
        lag = conn.execute(
            f"SELECT sfs_nr, rubrik, ikraft_grundforfattning, celex_grundforfattning FROM {p}sfsr_lagar WHERE sfs_nr = ?",
            (sfs_nr,)
        ).fetchone()
        if lag is None:
            conn.close()
            return None
        andringar = conn.execute(
            f"""SELECT andrings_sfs, rubrik, ikrafttradande, paragrafer,
                       prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse,
                       historisk, borttagen
                FROM {p}sfsr_andringar
                WHERE sfs_nr = ?
                ORDER BY COALESCE(ikrafttradande, '9999-12-31'), andrings_sfs""",
            (sfs_nr,)
        ).fetchall()
        conn.close()

    def _bool(v) -> bool:
        return bool(v)

    return {
        "sfs_nr": lag[0],
        "rubrik": lag[1],
        "ikraft_grundforfattning": str(lag[2]) if lag[2] else None,
        "celex_grundforfattning": lag[3],
        "andringar": [
            {
                "andrings_sfs":         r[0],
                "rubrik":               r[1],
                "ikrafttradande":       str(r[2]) if r[2] else None,
                "paragrafer":           r[3],
                "prop":                 r[4],
                "bet":                  r[5],
                "rskr":                 r[6],
                "celex":                r[7],
                "eu_direktiv":          _bool(r[8]),
                "overgangsbestammelse": _bool(r[9]),
                "historisk":            _bool(r[10]),
                "borttagen":            _bool(r[11]),
            }
            for r in andringar
        ],
    }


# ---------------------------------------------------------------------------
# API-backend (beta.rkrattsbaser.gov.se Elasticsearch)
# ---------------------------------------------------------------------------

def _hamta_via_api(sfs_nr: str) -> dict:
    """Hämtar lag från beta-API:ets Elasticsearch-endpoint."""
    payload = {
        "searchIndexes": ["Sfs"],
        "api": "search",
        "json": {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"beteckning.keyword": sfs_nr}},
                        {"term": {"publicerad": True}},
                    ]
                }
            },
            "size": 1,
        },
    }

    with httpx.Client(timeout=30) as klient:
        svar = klient.post(
            SFSR_API_URL,
            json=payload,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        )
    svar.raise_for_status()

    # API:et returnerar dubbelserialiserad JSON (JSON-sträng inuti JSON)
    yttre = svar.json()
    data = json.loads(yttre) if isinstance(yttre, str) else yttre

    traffar = data.get("hits", {}).get("hits", [])
    if not traffar:
        raise ValueError(f"SFS {sfs_nr} hittades inte i API:et.")

    kalla = traffar[0]["_source"]
    return _till_datamodell_api(kalla, sfs_nr)


def _parse_celex_grundforfattning(text: str | None) -> str | None:
    """Parsar radbrytningsseparerade CELEX-nummer för grundförfattningen."""
    if not text:
        return None
    rader = [r.strip() for r in text.splitlines() if r.strip()]
    return chr(10).join(rader) if rader else None


def _parse_celex_andring(text: str | None) -> str | None:
    """Parsar CELEX-nummer för en andring (komma- eller blankstegseparerade)."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    if "," in text:
        delar = [d.strip() for d in text.split(",") if d.strip()]
    else:
        delar = text.split()
    return ",".join(delar) if delar else None


def _datum_api(iso: str | None) -> str | None:
    """Konverterar ISO-datumtid till ÅÅÅÅ-MM-DD."""
    if not iso:
        return None
    return iso[:10]


def _till_datamodell_api(kalla: dict, sfs_nr: str) -> dict:
    """Mappar API-svar till intern datamodell."""

    def _forarbeten(text: str | None) -> tuple[str | None, str | None, str | None]:
        """Delar upp en förarbetessträng i prop, bet, rskr."""
        if not text:
            return None, None, None
        prop = bet = rskr = None
        for del_ in re.split(r"[,;\n]+", text):
            del_ = del_.strip()
            # API:et returnerar "Prop." med stor bokstav — jämför case-insensitivt
            # men normalisera bara prefixet till gemener; resten bevaras som det är
            # så att utskottsbeteckningar (JuU, KU, FöU m.fl.) behåller korrekt stil.
            del_lower = del_.lower()
            if del_lower.startswith("prop."):
                prop = "prop." + del_[5:]
            elif del_lower.startswith("bet."):
                bet = "bet." + del_[4:]
            elif del_lower.startswith("rskr."):
                rskr = "rskr." + del_[5:]
        return prop, bet, rskr

    prop_g, bet_g, rskr_g = _forarbeten(kalla.get("register", {}).get("forarbeten"))

    andringar = []
    for a in kalla.get("andringsforfattningar", []):
        if a.get("borttagen"):
            continue
        prop, bet, rskr = _forarbeten(a.get("forarbeten"))
        dt = a.get("ikraftDateTime") or "9999-12-31"
        # Extrahera år ur andrings_sfs (t.ex. "2022:216" → "2022") som sekundär sorteringsnyckel
        ar_sfs = (a.get("beteckning") or "0000:0").split(":")[0]
        andringar.append({
            "andrings_sfs":         a.get("beteckning"),
            "rubrik":               a.get("rubrik"),
            "ikrafttradande":       _datum_api(a.get("ikraftDateTime")),
            "paragrafer":           a.get("anteckningar"),
            "prop":                 prop,
            "bet":                  bet,
            "rskr":                 rskr,
            "celex":                _parse_celex_andring(a.get("celexnummer")),
            "eu_direktiv":          bool(a.get("eUdirektiv")) or bool(_parse_celex_andring(a.get("celexnummer"))),
            "overgangsbestammelse": bool(a.get("ikraftOvergangsbestammelse")),
            "historisk":            bool(a.get("historisk")),
            "borttagen":            False,
            "_sort_dt":             dt,
            "_sort_ar":             ar_sfs,
        })

    andringar.sort(key=lambda x: (x.pop("_sort_dt"), x.pop("_sort_ar", "0000")))

    return {
        "sfs_nr":          sfs_nr,
        "rubrik":          kalla.get("rubrik"),
        "ikraft_grundforfattning": _datum_api(kalla.get("ikraftDateTime")),
        "celex_grundforfattning":  _parse_celex_grundforfattning(
            kalla.get("register", {}).get("celexnummer")
        ),
        "cache_kalla":    "api",
        "andringar":       andringar,
    }


# ---------------------------------------------------------------------------
# HTML-backend (rkrattsbaser.gov.se — BeautifulSoup4)
# ---------------------------------------------------------------------------

def _hamta_via_html(sfs_nr: str) -> dict:
    """Hämtar och parsar SFSR-sidan för sfs_nr med BeautifulSoup4."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.error("beautifulsoup4 saknas. Kör: pip install beautifulsoup4")
        sys.exit(1)

    url = f"{SFSR_BASE_URL}?bet={sfs_nr}"
    with httpx.Client(timeout=30) as klient:
        svar = klient.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "sv,en;q=0.9",
            },
            follow_redirects=True,
        )
    svar.raise_for_status()

    return _parsa_sfsr_html(svar.text, sfs_nr)


def _etikett(box) -> str:
    """Extraherar etiketttexten (fälttitel) ur en result-inner-sub-box."""
    strong = box.find("strong")
    return strong.get_text(strip=True).rstrip(":") if strong else ""


def _parse_ikraft_html(text: str) -> tuple[str | None, bool]:
    """
    Parsar ikraftträdandetext och returnerar (datum, har_overgangsbestammelse).

    Övergångsbestämmelse (overg.best.) anger regler för hur skiftet mellan
    gammal och ny bestämmelse ska hanteras — t.ex. att pågående mål avgörs
    enligt äldre rätt.
    """
    overg = "overg.best." in text.lower()
    datumtext = re.sub(r"overg\.best\.", "", text, flags=re.IGNORECASE).strip()
    datummatch = re.search(r"\d{4}-\d{2}-\d{2}", datumtext)
    datum = datummatch.group(0) if datummatch else None
    return datum, overg


def _parse_forarbeten_html(text: str) -> tuple[str | None, str | None, str | None]:
    """Delar upp en förarbetessträng i prop, bet, rskr."""
    prop = bet = rskr = None
    for del_ in re.split(r"[,\n]+", text):
        del_ = del_.strip()
        if del_.startswith("prop."):
            prop = del_
        elif del_.startswith("bet."):
            bet = del_
        elif del_.startswith("rskr."):
            rskr = del_
    return prop, bet, rskr


def _parse_celex_html(text: str) -> str | None:
    """Parsar CELEX-nummer från HTML (mellanslags- eller kommaseparerade)."""
    text = text.strip()
    if not text:
        return None
    if "," in text:
        delar = [d.strip() for d in text.split(",") if d.strip()]
    else:
        delar = text.split()
    return ",".join(delar) if delar else None


def _parsa_sfsr_html(html: str, sfs_nr: str) -> dict:
    """Parsar HTML från rkrattsbaser.gov.se/sfsr och returnerar datamodell."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # -- Grundförfattningsmetadata --
    rubrik = None
    ikraft_grundforfattning = None
    celex_grundforfattning_lista: list[str] = []

    huvud = soup.find("div", class_="result-inner-box")
    if huvud:
        for box in huvud.find_all("div", class_="result-inner-sub-box", recursive=False):
            full_text = box.get_text(separator=" ", strip=True)
            bold_tag = box.find("strong")
            bold_text = bold_tag.get_text(strip=True) if bold_tag else ""
            # Rubrik: hela textinnehållet är samma som bold-texten
            if full_text == bold_text and bold_text and not rubrik:
                rubrik = bold_text
                continue
            etikett = _etikett(box)
            varde = box.get_text(separator=" ", strip=True)
            # Ta bort etiketten från värdet
            if etikett and varde.startswith(etikett):
                varde = varde[len(etikett):].lstrip(":").strip()
            if etikett == "Ikraft":
                ikraft_grundforfattning, _ = _parse_ikraft_html(varde)
            elif etikett == "CELEX-nr":
                celex_str = _parse_celex_html(varde)
                if celex_str:
                    celex_grundforfattning_lista.extend(celex_str.split(","))

    celex_grundforfattning = "\n".join(celex_grundforfattning_lista) if celex_grundforfattning_lista else None

    # -- Ändringar --
    andringar = []
    for container in soup.find_all("div", class_="result-inner-sub-box-container"):
        header = container.find("div", class_="result-inner-sub-box-header")
        andrings_sfs = header.get_text(strip=True) if header else None

        a_rubrik = a_ikraft = a_paragrafer = None
        a_prop = a_bet = a_rskr = a_celex = None
        a_overg = False

        for box in container.find_all("div", class_="result-inner-sub-box"):
            full_text = box.get_text(separator=" ", strip=True)
            bold_tag = box.find("strong")
            bold_text = bold_tag.get_text(strip=True) if bold_tag else ""
            if full_text == bold_text and bold_text and not a_rubrik:
                a_rubrik = bold_text
                continue
            etikett = _etikett(box)
            varde = box.get_text(separator=" ", strip=True)
            if etikett and varde.startswith(etikett):
                varde = varde[len(etikett):].lstrip(":").strip()
            if etikett == "Ikraft":
                a_ikraft, a_overg = _parse_ikraft_html(varde)
            elif etikett == "Omfattning":
                a_paragrafer = varde
            elif etikett == "Förarbeten":
                a_prop, a_bet, a_rskr = _parse_forarbeten_html(varde)
            elif etikett == "CELEX-nr":
                a_celex = _parse_celex_html(varde)

        andringar.append({
            "andrings_sfs":         andrings_sfs,
            "rubrik":               a_rubrik,
            "ikrafttradande":       a_ikraft,
            "paragrafer":           a_paragrafer,
            "prop":                 a_prop,
            "bet":                  a_bet,
            "rskr":                 a_rskr,
            "celex":                a_celex,
            "eu_direktiv":          bool(a_celex),  # CELEX-nr indikerar EU-koppling
            "overgangsbestammelse": a_overg,
            "historisk":            False,
            "borttagen":            False,
        })

    return {
        "sfs_nr":          sfs_nr,
        "rubrik":          rubrik,
        "ikraft_grundforfattning": ikraft_grundforfattning,
        "celex_grundforfattning":  celex_grundforfattning,
        "cache_kalla":    "html",
        "andringar":       andringar,
    }


# ---------------------------------------------------------------------------
# Publik API
# ---------------------------------------------------------------------------

def hamta_lag(sfs_nr: str, tvinga_uppdatering: bool = False) -> dict:
    """
    Hämtar SFSR-data för sfs_nr. Returnerar cachad data om den är färsk.

    Args:
        sfs_nr:             SFS-nummer, t.ex. "1993:1617"
        tvinga_uppdatering: Om True hoppas cache-kontrollen över

    Returns:
        Dict med sfs_nr, rubrik, ikraft_grundforfattning, celex_grundforfattning, andringar
    """
    sfs_nr = _normalisera_sfs(sfs_nr)

    if not tvinga_uppdatering and _cache_giltig(sfs_nr):
        log.debug("Returnerar cachad data för %s", sfs_nr)
        return _las_fran_cache(sfs_nr)

    log.info("Hämtar %s från %s-backend", sfs_nr, SFSR_BACKEND)

    if SFSR_BACKEND == "html":
        data = _hamta_via_html(sfs_nr)
    else:
        try:
            data = _hamta_via_api(sfs_nr)
        except Exception as e:
            log.warning("API-hämtning misslyckades för %s (%s) — försöker HTML-fallback", sfs_nr, e)
            data = _hamta_via_html(sfs_nr)

    _spara_i_cache(data)
    return data
