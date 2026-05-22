# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Magnus Kolsjö
# Se LICENSE-filen i repots rot för fullständig licenstext.

"""
sfsr_scraper.py — Hämtar och cachar SFSR-data (Svensk författningssamlings register)

Stöder två backends, styrda via miljövariabeln SFSR_BACKEND:
  - "api"  (standard): anropar beta.rkrattsbaser.gov.se Elasticsearch-API
  - "html"            : skrapar rkrattsbaser.gov.se med BeautifulSoup4

Resultaten cachelagras i PostgreSQL eller SQLite (beroende på DATABASE_URL).
Cache-TTL styrs av SFSR_CACHE_TTL_HOURS (standard: 24 h).

Vid API-anropsfel aktiveras automatisk HTML-fallback så att frågorna
alltid besvaras — oavsett vilket SFSR_BACKEND som valts vid installation.
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
DATABASE_URL         = os.getenv("DATABASE_URL", "sqlite:///sfsr_cache.db")
SFSR_BACKEND         = os.getenv("SFSR_BACKEND", "api").lower()
SFSR_BASE_URL        = os.getenv("SFSR_BASE_URL", "https://rkrattsbaser.gov.se/sfsr")
SFSR_API_URL         = os.getenv(
    "SFSR_API_URL",
    "https://beta.rkrattsbaser.gov.se/elasticsearch/SearchEsByRawJson",
)
SFSR_CACHE_TTL_HOURS = int(os.getenv("SFSR_CACHE_TTL_HOURS", "24"))
USER_AGENT           = os.getenv(
    "USER_AGENT",
    "mcp-for-rkrattsdatabaser-sfsr/1.0 (+https://github.com/MagnusKolsjo/mcp-for-rkrattsdatabaser-sfsr)",
)

# ---------------------------------------------------------------------------
# Hjälpfunktioner — databas (per-anrops-mönstret)
# ---------------------------------------------------------------------------

def _ar_postgres() -> bool:
    """Returnerar True om DATABASE_URL pekar på en PostgreSQL-instans."""
    return DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")


def _hamta_db():
    """Öppnar en ny databasanslutning (stängs av anroparen)."""
    if _ar_postgres():
        try:
            import psycopg2
        except ImportError:
            log.error("psycopg2 saknas. Kör: pip install psycopg2-binary")
            sys.exit(1)
        return psycopg2.connect(DATABASE_URL)
    else:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _ph() -> str:
    """Platshållare för SQL-parametrar (%s för PostgreSQL, ? för SQLite)."""
    return "%s" if _ar_postgres() else "?"


def _prefix() -> str:
    """Tabellprefix (sfsr. för PostgreSQL, tomt för SQLite)."""
    return "sfsr." if _ar_postgres() else ""


# ---------------------------------------------------------------------------
# Hjälpfunktioner — gemensamma
# ---------------------------------------------------------------------------

def _normalisera_sfs(sfs_nr: str) -> str:
    """
    Normaliserar SFS-nummer till formatet ÅÅÅÅ:NNN (t.ex. '1993:1617').

    Hanterar varianter som "SFS 1993:1617", "SFS1993:1617", "1993 : 1617".
    """
    sfs_nr = sfs_nr.strip()
    # Ta bort eventuellt "SFS "-prefix (case-insensitivt)
    sfs_nr = re.sub(r"^(?:SFS\s*)", "", sfs_nr, flags=re.IGNORECASE)
    # Normalisera mellanslag runt kolon
    sfs_nr = re.sub(r"\s*:\s*", ":", sfs_nr)
    return sfs_nr.strip()


# ---------------------------------------------------------------------------
# Cache-hantering
# ---------------------------------------------------------------------------

def _cache_giltig(sfs_nr: str) -> bool:
    """Returnerar True om en färsk cache-post finns för sfs_nr."""
    p, ph = _prefix(), _ph()
    ttl_grans = datetime.now(timezone.utc) - timedelta(hours=SFSR_CACHE_TTL_HOURS)
    conn = _hamta_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT cachad_vid FROM {p}sfsr_lagar WHERE sfs_nr = {ph}",
            (sfs_nr,),
        )
        rad = cur.fetchone()
    finally:
        conn.close()

    if rad is None:
        return False
    cv = rad[0]
    if isinstance(cv, str):
        cv = datetime.fromisoformat(cv)
    if cv.tzinfo is None:
        cv = cv.replace(tzinfo=timezone.utc)
    return cv >= ttl_grans


def _spara_i_cache(data: dict) -> None:
    """Sparar hämtad SFSR-data i databasen (ersätter eventuell befintlig post)."""
    p, ph = _prefix(), _ph()
    sfs_nr = data["sfs_nr"]
    nu = datetime.now(timezone.utc).isoformat()

    # CELEX-listor serialiseras som kommaseparerade strängar för DB-lagring
    celex_g = ",".join(data.get("celex_grundforfattning") or [])

    conn = _hamta_db()
    if _ar_postgres():
        conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {p}sfsr_lagar WHERE sfs_nr = {ph}", (sfs_nr,))
        cur.execute(
            f"""INSERT INTO {p}sfsr_lagar
                (sfs_nr, rubrik,
                 ikraft_grundforfattning, utfardad_grundforfattning,
                 upphavd_datum, upphavd_genom, departement,
                 celex_grundforfattning, t_o_m_sfs, lagtext,
                 prop_grundforfattning, bet_grundforfattning, rskr_grundforfattning,
                 cachad_vid, cache_kalla)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (
                sfs_nr,
                data.get("rubrik"),
                data.get("ikraft_grundforfattning"),
                data.get("utfardad_grundforfattning"),
                data.get("upphavd_datum"),
                data.get("upphavd_genom"),
                data.get("departement"),
                celex_g or None,
                data.get("t_o_m_sfs"),
                data.get("lagtext"),
                data.get("prop_grundforfattning"),
                data.get("bet_grundforfattning"),
                data.get("rskr_grundforfattning"),
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
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (
                    sfs_nr,
                    a.get("andrings_sfs"),
                    a.get("rubrik"),
                    a.get("ikrafttradande"),
                    a.get("paragrafer"),
                    a.get("prop"),
                    a.get("bet"),
                    a.get("rskr"),
                    ",".join(a.get("celex") or []) or None,
                    a.get("eu_direktiv", False),
                    a.get("overgangsbestammelse", False),
                    a.get("historisk", False),
                    a.get("borttagen", False),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _las_fran_cache(sfs_nr: str) -> dict | None:
    """Läser en lag med alla dess andringar från cachen."""
    p, ph = _prefix(), _ph()

    conn = _hamta_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT sfs_nr, rubrik,
                       ikraft_grundforfattning, utfardad_grundforfattning,
                       upphavd_datum, upphavd_genom, departement,
                       celex_grundforfattning, t_o_m_sfs, lagtext,
                       cache_kalla, cachad_vid,
                       prop_grundforfattning, bet_grundforfattning, rskr_grundforfattning
                FROM {p}sfsr_lagar WHERE sfs_nr = {ph}""",
            (sfs_nr,),
        )
        lag = cur.fetchone()
        if lag is None:
            return None

        cur.execute(
            f"""SELECT andrings_sfs, rubrik, ikrafttradande, paragrafer,
                       prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse,
                       historisk, borttagen
                FROM {p}sfsr_andringar
                WHERE sfs_nr = {ph}
                ORDER BY COALESCE(CAST(ikrafttradande AS TEXT), '9999-12-31'), SUBSTR(andrings_sfs, 1, 4)""",
            (sfs_nr,),
        )
        andringar_rader = cur.fetchall()
    finally:
        conn.close()

    def _celex_lista(text) -> list[str]:
        # Hanterar både komma- och radbrytningsseparerade värden (bakåtkompatibelt)
        if not text:
            return []
        return [c.strip() for c in re.split(r"[,\n]", text) if c.strip()]

    return {
        "sfs_nr":                    lag[0],
        "rubrik":                    lag[1],
        "ikraft_grundforfattning":   str(lag[2]) if lag[2] else None,
        "utfardad_grundforfattning": str(lag[3]) if lag[3] else None,
        "upphavd_datum":             str(lag[4]) if lag[4] else None,
        "upphavd_genom":             lag[5],
        "departement":               lag[6],
        "celex_grundforfattning":    _celex_lista(lag[7]),
        "t_o_m_sfs":                 lag[8],
        "lagtext":                   lag[9],
        "cache_kalla":               lag[10],
        "cachad_vid":                str(lag[11]) if lag[11] else None,
        "prop_grundforfattning":     lag[12],
        "bet_grundforfattning":      lag[13],
        "rskr_grundforfattning":     lag[14],
        "andringar": [
            {
                "andrings_sfs":         r[0],
                "rubrik":               r[1],
                "ikrafttradande":       str(r[2]) if r[2] else None,
                "paragrafer":           r[3],
                "prop":                 r[4],
                "bet":                  r[5],
                "rskr":                 r[6],
                "celex":                _celex_lista(r[7]),
                "eu_direktiv":          bool(r[8]),
                "overgangsbestammelse": bool(r[9]),
                "historisk":            bool(r[10]),
                "borttagen":            bool(r[11]),
            }
            for r in andringar_rader
        ],
    }


# ---------------------------------------------------------------------------
# CELEX-parsning
# ---------------------------------------------------------------------------

def _parse_celex_grundforfattning(text: str | None) -> list[str]:
    """Parsar CELEX-nummer för grundförfattningen (radbrytnings- eller kommaseparerade)."""
    if not text:
        return []
    return [c.strip() for c in re.split(r"[,\n]", text) if c.strip()]


def _parse_celex_andring(text: str | None) -> list[str]:
    """Parsar CELEX-nummer för en andring (komma- eller blankstegseparerade)."""
    if not text:
        return []
    text = text.strip()
    if not text:
        return []
    if "," in text:
        return [d.strip() for d in text.split(",") if d.strip()]
    return [d for d in text.split() if d]


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

    # Defensiv hantering — API:et kan returnera dubbelserialiserat JSON i vissa lägen
    yttre = svar.json()
    data = json.loads(yttre) if isinstance(yttre, str) else yttre

    traffar = data.get("hits", {}).get("hits", [])
    if not traffar:
        raise ValueError(f"SFS {sfs_nr} hittades inte i API:et.")

    kalla = traffar[0]["_source"]
    return _till_datamodell_api(kalla, sfs_nr)


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
            # Normalisera prefixet till gemener; resten bevaras som det är
            # så att utskottsbeteckningar (JuU, KU m.fl.) behåller korrekt stil.
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
            # eu_direktiv återger API:ets eUdirektiv-flagga direkt.
            # CELEX-närvaro utan flaggan innebär EU-koppling men inte
            # nödvändigtvis direktiv-genomförande — se celex-fältet.
            "eu_direktiv":          bool(a.get("eUdirektiv")),
            "overgangsbestammelse": bool(a.get("ikraftOvergangsbestammelse")),
            "historisk":            bool(a.get("historisk")),
            "borttagen":            False,
            "_sort_dt":             dt,
            "_sort_ar":             ar_sfs,
        })

    andringar.sort(key=lambda x: (x.pop("_sort_dt"), x.pop("_sort_ar", "0000")))

    fulltext = kalla.get("fulltext") or {}

    return {
        "sfs_nr":                    sfs_nr,
        "rubrik":                    kalla.get("rubrik"),
        "ikraft_grundforfattning":   _datum_api(kalla.get("ikraftDateTime")),
        "utfardad_grundforfattning": _datum_api(kalla.get("utfardadDateTime")),
        "upphavd_datum":             _datum_api(kalla.get("upphavdDateTime")),
        "upphavd_genom":             fulltext.get("upphavdGenom"),
        "departement":               (kalla.get("organisation") or {}).get("namnOchEnhet"),
        "celex_grundforfattning":    _parse_celex_grundforfattning(
                                         (kalla.get("register") or {}).get("celexnummer")
                                     ),
        "t_o_m_sfs":                 fulltext.get("andringInford"),
        "lagtext":                   fulltext.get("forfattningstext"),
        "prop_grundforfattning":     prop_g,
        "bet_grundforfattning":      bet_g,
        "rskr_grundforfattning":     rskr_g,
        "cache_kalla":               "api",
        "andringar":                 andringar,
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

    Övergångsbestämmelse anger regler för hur skiftet mellan gammal och ny
    bestämmelse ska hanteras — t.ex. att pågående mål avgörs enligt äldre rätt.
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


def _parse_celex_html(text: str) -> list[str]:
    """Parsar CELEX-nummer från HTML (mellanslags- eller kommaseparerade)."""
    text = text.strip()
    if not text:
        return []
    if "," in text:
        return [d.strip() for d in text.split(",") if d.strip()]
    return [d for d in text.split() if d]


def _parsa_sfsr_html(html: str, sfs_nr: str) -> dict:
    """Parsar HTML från rkrattsbaser.gov.se/sfsr och returnerar datamodell."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # -- Grundförfattningsmetadata --
    rubrik = None
    ikraft_grundforfattning = None
    celex_grundforfattning: list[str] = []

    huvud = soup.find("div", class_="result-inner-box")
    if huvud:
        for box in huvud.find_all("div", class_="result-inner-sub-box", recursive=False):
            full_text = box.get_text(separator=" ", strip=True)
            bold_tag = box.find("strong")
            bold_text = bold_tag.get_text(strip=True) if bold_tag else ""
            if full_text == bold_text and bold_text and not rubrik:
                rubrik = bold_text
                continue
            etikett = _etikett(box)
            varde = box.get_text(separator=" ", strip=True)
            if etikett and varde.startswith(etikett):
                varde = varde[len(etikett):].lstrip(":").strip()
            if etikett == "Ikraft":
                ikraft_grundforfattning, _ = _parse_ikraft_html(varde)
            elif etikett == "CELEX-nr":
                celex_grundforfattning.extend(_parse_celex_html(varde))

    # -- Ändringar --
    andringar = []
    sedda_sfs: set[str] = set()  # Deduplicering — dubbletter förekommer i HTML men ej i API

    for container in soup.find_all("div", class_="result-inner-sub-box-container"):
        header = container.find("div", class_="result-inner-sub-box-header")
        header_text = header.get_text(strip=True) if header else ""

        # Extrahera SFS-numret ur "Ändring, SFS ÅÅÅÅ:NNN"-rubriken
        m = re.search(r"SFS\s+(\d{4}:\d+)", header_text)
        andrings_sfs = m.group(1) if m else (header_text or None)

        # Hoppa över dubletter (HTML-sajten kan lista samma ändring två gånger)
        if andrings_sfs and andrings_sfs in sedda_sfs:
            continue
        if andrings_sfs:
            sedda_sfs.add(andrings_sfs)

        a_rubrik = a_ikraft = a_paragrafer = None
        a_prop = a_bet = a_rskr = None
        a_celex: list[str] = []
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
            # HTML-backenden saknar eUdirektiv-flaggan; eu_direktiv sätts till False.
            # CELEX-närvaro i celex-fältet indikerar EU-koppling men är inte
            # detsamma som direktiv-genomförande.
            "eu_direktiv":          False,
            "overgangsbestammelse": a_overg,
            "historisk":            False,
            "borttagen":            False,
        })

    return {
        "sfs_nr":                    sfs_nr,
        "rubrik":                    rubrik,
        "ikraft_grundforfattning":   ikraft_grundforfattning,
        "utfardad_grundforfattning": None,   # saknas i HTML
        "upphavd_datum":             None,   # saknas i HTML
        "upphavd_genom":             None,   # saknas i HTML
        "departement":               None,   # saknas i HTML
        "celex_grundforfattning":    celex_grundforfattning,
        "t_o_m_sfs":                 None,   # saknas i HTML
        "lagtext":                   None,   # saknas i HTML
        "prop_grundforfattning":     None,   # saknas i HTML
        "bet_grundforfattning":      None,   # saknas i HTML
        "rskr_grundforfattning":     None,   # saknas i HTML
        "cache_kalla":               "html",
        "andringar":                 andringar,
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
        Dict med sfs_nr, rubrik, ikraft_grundforfattning, utfardad_grundforfattning,
        upphavd_datum, upphavd_genom, departement, celex_grundforfattning (list),
        t_o_m_sfs, lagtext, cache_kalla, andringar (lista)
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
        except ValueError:
            # SFS-numret hittades inte i API:et — ingen fallback, inget cacheande
            raise
        except Exception as e:
            log.warning(
                "API-anrop misslyckades för %s (%s) — automatisk HTML-fallback aktiveras",
                sfs_nr, e,
            )
            data = _hamta_via_html(sfs_nr)

    _spara_i_cache(data)
    data["cachad_vid"] = datetime.now(timezone.utc).isoformat()
    return data
