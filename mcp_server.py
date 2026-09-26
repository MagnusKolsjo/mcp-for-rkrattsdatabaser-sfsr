# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Magnus Kolsjö
# Se LICENSE-filen i repots rot för fullständig licenstext.

"""
mcp_server.py — MCP-server för SFSR ändringsregister

Exponerar fyra verktyg till MCP-kompatibla AI-verktyg:
  sfsr_hamta_andringshistorik  — hela ändringshistoriken för en lag
  sfsr_hamta_paragrafhistorik  — ändringar som berör en specifik paragraf
  sfsr_folj_andringskedja      — följer ändringskedjan bakåt (med propositionsreferenser)
  sfsr_hamta_lagtext           — hämtar konsoliderad lagtext för en grundförfattning

Krav:
  - Konfiguration via .env (se config.example.env)
  - Installerade beroenden: pip install -r requirements.txt

Transport styrs via MCP_TRANSPORT i .env: stdio (standard, lokal användning)
eller http (hostad driftsättning, kräver MCP_API_KEY). Se mcp_transport.py.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Callable, NotRequired, Optional, TypedDict, TypeVar

import httpx
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(_SCRIPT_DIR / ".env")

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from pydantic import Field  # noqa: E402

try:
    import psycopg2
    _DB_FEL: tuple[type[Exception], ...] = (sqlite3.Error, psycopg2.Error)
except ImportError:
    _DB_FEL = (sqlite3.Error,)

# Käll- och databasfel som är förväntade driftlägen (nätet är nere,
# databasen är otillgänglig) — inte kodfel — och därför ska ge ett
# begripligt ToolError i stället för att krascha anropet utan förklaring.
_KALLFEL: tuple[type[Exception], ...] = (httpx.HTTPError, OSError, *_DB_FEL)

from db import initiera_schema  # noqa: E402
from mcp_annotationer import CACHE_HINTAR, LASNING_EXTERN  # noqa: E402
from mcp_transport import starta  # noqa: E402
from sfsr_tools import sfsr_hamta_andringshistorik as _hamta_andringshistorik  # noqa: E402
from sfsr_tools import sfsr_hamta_lagtext as _hamta_lagtext  # noqa: E402
from sfsr_tools import sfsr_hamta_paragrafhistorik as _hamta_paragrafhistorik  # noqa: E402

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Standardtak för fulltext i hämtverktygen. Utan ett tak som gäller by default
# kan ett anrop mot ett stort dokument överskrida MCP-protokollets storleksgräns
# och misslyckas helt, utan väg runt. Anroparen kan alltid höja taket, eller
# sätta 0 för hela texten som ett uttryckligt val.
SFSR_MAX_TECKEN = int(os.getenv("SFSR_MAX_TECKEN", "60000"))

# Versionen följer senaste släppta version i CHANGELOG.md.
SERVERVERSION = "5.0.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Svarstyper
#
# SFSR:s API lämnar många fält null (särskilt för äldre författningar och
# ändringar som bara rör ikraftträdandebestämmelser), så nästan alla fält
# utom sfs_nr/andrings_sfs är valfria. Ett fält som typen kräver men som
# saknas i svaret får hela anropet att misslyckas.
# ---------------------------------------------------------------------------

class Andring(TypedDict):
    """En ändrings-SFS i en grundförfattnings ändringshistorik."""
    andrings_sfs:         str | None
    rubrik:                str | None
    ikrafttradande:        str | None   # ÅÅÅÅ-MM-DD
    paragrafer:             str | None
    prop:                   str | None
    bet:                    str | None
    rskr:                   str | None
    celex:                  list[str]
    eu_direktiv:            bool
    overgangsbestammelse:   bool
    historisk:              bool


class Andringshistorik(TypedDict):
    """Svar från sfsr_hamta_andringshistorik."""
    sfs_nr:                       str
    rubrik:                       str | None
    ikraft_grundforfattning:      str | None   # ÅÅÅÅ-MM-DD
    utfardad_grundforfattning:    str | None   # ÅÅÅÅ-MM-DD
    upphavd_datum:                str | None   # ÅÅÅÅ-MM-DD, None om ej upphävd
    upphavd_genom:                str | None   # ersättande SFS-nummer
    departement:                  str | None
    t_o_m_sfs:                    str | None
    celex_grundforfattning:       list[str]
    prop_grundforfattning:        str | None
    bet_grundforfattning:         str | None
    rskr_grundforfattning:        str | None
    cache_kalla:                  str | None   # "api" eller "html"
    cachad_vid:                   str | None   # ISO-tidpunkt för senaste cachning
    antal_andringar:              int
    andringar:                    list[Andring]


class Lagtext(TypedDict):
    """Svar från sfsr_hamta_lagtext."""
    sfs_nr:                str
    rubrik:                 str | None
    t_o_m_sfs:               str | None
    lagtext:                 str | None
    tecken_totalt:           NotRequired[int]
    tecken_visade:           NotRequired[int]
    trunkerad:                NotRequired[bool]
    fortsatt_fran_tecken:     NotRequired[int | None]
    las_vidare:               NotRequired[str]


# Fältet heter "not" i den befintliga returstrukturen — reserverat ord i
# Python, så TypedDict byggs med den funktionella syntaxen i stället för
# class-satsen som övriga typer.
Andringskedja = TypedDict(
    "Andringskedja",
    {
        "sfs_nr":   str,
        "paragraf": str | None,
        "djup":     int,
        "kedjeled": list[Andring],
        "not":      str,
    },
)


# ---------------------------------------------------------------------------
# Textutdrag och trunkering
# ---------------------------------------------------------------------------

def _skar_ut(text: str | None, max_tecken: int, fran_tecken: int = 0) -> dict:
    """
    Skär ut ett textutdrag och redovisa alltid vad som kapats.

    Trunkering utan markering är ett tyst datafel — svaret ser ut att vara hela
    innehållet. max_tecken <= 0 betyder ingen trunkering. Klipper på ordgräns.
    """
    text   = text or ""
    totalt = len(text)
    start  = max(0, min(fran_tecken, totalt))
    rest   = text[start:]

    if max_tecken and max_tecken > 0 and len(rest) > max_tecken:
        utdrag    = rest[:max_tecken]
        brytpunkt = max(utdrag.rfind(" "), utdrag.rfind("\n"))
        if brytpunkt > max_tecken * 0.6:
            utdrag = utdrag[:brytpunkt]
        utdrag    = utdrag.rstrip()
        trunkerad = True
    else:
        utdrag    = rest
        trunkerad = False

    slut = start + len(utdrag)
    return {
        "text":                 utdrag,
        "tecken_totalt":        totalt,
        "tecken_visade":        len(utdrag),
        "trunkerad":            trunkerad,
        "fortsatt_fran_tecken": slut if slut < totalt else None,
    }


def _andring(a: dict) -> Andring:
    """Plockar ut de fält en Andring lovar, ur sfsr_tools svar (som även bär `borttagen`)."""
    return {
        "andrings_sfs":         a.get("andrings_sfs"),
        "rubrik":                a.get("rubrik"),
        "ikrafttradande":        a.get("ikrafttradande"),
        "paragrafer":            a.get("paragrafer"),
        "prop":                  a.get("prop"),
        "bet":                   a.get("bet"),
        "rskr":                  a.get("rskr"),
        "celex":                 a.get("celex") or [],
        "eu_direktiv":           bool(a.get("eu_direktiv")),
        "overgangsbestammelse":  bool(a.get("overgangsbestammelse")),
        "historisk":             bool(a.get("historisk")),
    }


_T = TypeVar("_T")


def _sakert_anrop(beskrivning: str, fn: Callable[[], _T]) -> _T:
    """Kör fn() och omvandlar kända käll- och databasfel till ToolError.

    ValueError signalerar att SFS-numret inte hittades i källan — meddelandet
    är redan begripligt och skickas vidare oförändrat. Nätverks- och
    databasfel (_KALLFEL: httpx, sqlite3, ev. psycopg2, OSError) signalerar
    att källan eller cachen är otillgänglig just nu — ett förväntat driftläge,
    inte ett kodfel. Den tekniska detaljen loggas; klienten får ett svenskt
    meddelande som säger vad som hände utan att läcka stacktrace-detaljer.

    Oväntade undantag (programmeringsfel) fångas inte här och ger MCP:s
    generiska felsvar, med spåret på stderr, som avsett.
    """
    try:
        return fn()
    except ValueError as e:
        raise ToolError(str(e)) from e
    except _KALLFEL as e:
        log.exception("%s: käll- eller databasfel", beskrivning)
        raise ToolError(
            f"{beskrivning} misslyckades på grund av ett käll- eller databasfel "
            f"({type(e).__name__}: {e}). Försök igen senare."
        ) from e


# ---------------------------------------------------------------------------
# MCP-server
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "sfsr-v2",
    instructions=(
        "MCP-server för Regeringskansliets rättsdatabaser (SFSR) — det strukturerade "
        "ändringsregistret för svensk författningssamling. Verktygen har prefixet sfsr_. "
        "Ger på paragrafnivå vilka ändrings-SFS som berört en bestämmelse, när de trädde "
        "i kraft och vilka förarbeten som ligger bakom. "
        "DISCOVERY: anta aldrig att ett SFS-nummer är gällande rätt utifrån förhandskunskap "
        "— lagar upphävs och ersätts. Sök först fram aktuell lagstiftning på ämnestermer "
        "(t.ex. med rd_search mot riksdagens öppna data) och bekräfta med "
        "sfsr_hamta_andringshistorik innan paragrafhistorik hämtas. "
        "SVARSSTORLEK: sfsr_hamta_lagtext tar max_tecken och fran_tecken. En "
        "konsoliderad balk kan vara hundratusentals tecken och överskrida svarsgränsen "
        "om hela texten begärs. Ett kapat svar bär trunkerad och fortsatt_fran_tecken. "
        "CITAT: citera aldrig lagtext ur ett svar markerat som trunkerat — läs vidare "
        "med fran_tecken tills hela bestämmelsen är hämtad."
    ),
    version=SERVERVERSION,
    cache_hints=CACHE_HINTAR,
)


@mcp.tool(title="Hämta ändringshistorik", annotations=LASNING_EXTERN)
def sfsr_hamta_andringshistorik(
    sfs_nr: Annotated[str, Field(description="SFS-nummer för grundförfattningen, t.ex. \"1993:1617\"")],
) -> Andringshistorik:
    """
    Hämtar hela ändringshistoriken för en lag från SFSR.

    Returnerar metadata om grundförfattningen samt en kronologisk lista av alla
    ändrings-SFS, med ikraftträdandedatum, berörda paragrafer och förarbeten
    (proposition, betänkande, riksdagsskrivelse).

    Fältet historisk=true markerar poster som är inaktuella enligt källan
    (t.ex. ersatta av en ny version av samma ändring).
    """
    resultat = _sakert_anrop(
        f"Hämta ändringshistorik för {sfs_nr}",
        lambda: _hamta_andringshistorik(sfs_nr),
    )

    return {
        "sfs_nr":                    resultat["sfs_nr"],
        "rubrik":                    resultat.get("rubrik"),
        "ikraft_grundforfattning":   resultat.get("ikraft_grundforfattning"),
        "utfardad_grundforfattning": resultat.get("utfardad_grundforfattning"),
        "upphavd_datum":             resultat.get("upphavd_datum"),
        "upphavd_genom":             resultat.get("upphavd_genom"),
        "departement":               resultat.get("departement"),
        "t_o_m_sfs":                 resultat.get("t_o_m_sfs"),
        "celex_grundforfattning":    resultat.get("celex_grundforfattning") or [],
        "prop_grundforfattning":     resultat.get("prop_grundforfattning"),
        "bet_grundforfattning":      resultat.get("bet_grundforfattning"),
        "rskr_grundforfattning":     resultat.get("rskr_grundforfattning"),
        "cache_kalla":               resultat.get("cache_kalla"),
        "cachad_vid":                resultat.get("cachad_vid"),
        "antal_andringar":           resultat.get("antal_andringar", 0),
        "andringar":                 [_andring(a) for a in resultat.get("andringar", [])],
    }


@mcp.tool(title="Hämta paragrafhistorik", annotations=LASNING_EXTERN)
def sfsr_hamta_paragrafhistorik(
    sfs_nr: Annotated[str, Field(description="SFS-nummer för grundförfattningen, t.ex. \"1993:1617\"")],
    paragraf: Annotated[str, Field(description="Paragrafbeteckning, t.ex. \"2 kap. 8 §\" eller \"3 §\"")],
) -> list[Andring]:
    """
    Filtrerar ändringshistoriken till poster som berör en specifik paragraf.

    Använd detta för att spåra hur en enskild paragraf förändrats över tid —
    t.ex. vilka propositioner som lett till att paragrafen ändrats och när.

    Accepterar naturliga uttryck: "2:8", "andra kapitlet 8 §", "para 8 kap 2".
    Tom lista om inga träffar.

    Tips: hämta först hela historiken med sfsr_hamta_andringshistorik för att
    se vilka paragrafer som ändrats och hur de är betecknade i SFSR.
    """
    resultat = _sakert_anrop(
        f"Hämta paragrafhistorik för {sfs_nr} §{paragraf}",
        lambda: _hamta_paragrafhistorik(sfs_nr, paragraf),
    )

    return [_andring(a) for a in resultat]


@mcp.tool(title="Följ ändringskedja", annotations=LASNING_EXTERN)
def sfsr_folj_andringskedja(
    sfs_nr: Annotated[str, Field(description="SFS-nummer för grundförfattningen, t.ex. \"1993:1617\"")],
    paragraf: Annotated[
        Optional[str],
        Field(description="Om angiven filtreras kedjan till ändringar som rör just den paragrafen, t.ex. \"2 kap. 8 §\""),
    ] = None,
    djup: Annotated[int, Field(description="Max antal kedjeled att följa (standard: 5, max: 20)")] = 5,
) -> Andringskedja:
    """
    Följer ändringskedjan bakåt för en lag (eller paragraf) och returnerar
    en ordnad lista av kedjeled med källa, datum och propositionsreferens.

    Varje kedjeled representerar ett ändrings-SFS med tillhörande förarbeten.
    Kombinera med riksdagens API-server för att hämta propositionstexter och
    få fullständig spårbarhet från gällande rätt tillbaka till ursprungsproposition.
    """
    djup = min(max(1, djup), 20)

    def _hamta() -> list[dict]:
        if paragraf:
            return _hamta_paragrafhistorik(sfs_nr, paragraf)
        return _hamta_andringshistorik(sfs_nr)["andringar"]

    andringar = _sakert_anrop(f"Följ ändringskedja för {sfs_nr}", _hamta)

    # Returnera de senaste `djup` ändringarna i omvänd ordning (nyast först)
    kedjeled = list(reversed(andringar[-djup:]))

    return {
        "sfs_nr":   sfs_nr,
        "paragraf": paragraf,
        "djup":     djup,
        "kedjeled": [_andring(a) for a in kedjeled],
        "not":      (
            "Propositionstexter hämtas via rd_get_document i riksdagens API-server. "
            "Ange prop-värdet som dok_id."
        ),
    }


@mcp.tool(title="Hämta konsoliderad lagtext", annotations=LASNING_EXTERN)
def sfsr_hamta_lagtext(
    sfs_nr: Annotated[str, Field(description="SFS-nummer för grundförfattningen, t.ex. \"1993:1617\"")],
    max_tecken: Annotated[
        int,
        Field(description="Teckentak för lagtexten (0 = hela texten). Bläddra med fran_tecken när texten är stor."),
    ] = SFSR_MAX_TECKEN,
    fran_tecken: Annotated[
        int,
        Field(description="Börja lagtexten vid denna teckenposition — värdet ur fortsatt_fran_tecken från förra anropet."),
    ] = 0,
) -> Lagtext:
    """
    Hämtar den konsoliderade lagtexten för en grundförfattning.

    Lagtexten är den version som visas på rkrattsbaser.gov.se, uppdaterad
    t.o.m. det SFS-nummer som anges i t_o_m_sfs.

    Om lagtexten saknas i cachen hämtas posten automatiskt om från källan.
    Fältet lagtext kan vara null om källan inte tillhandahåller fulltext
    för den aktuella grundförfattningen.

    Citera aldrig ur ett svar där trunkerad är true — läs vidare först.
    """
    resultat = _sakert_anrop(
        f"Hämta lagtext för {sfs_nr}",
        lambda: _hamta_lagtext(sfs_nr),
    )

    svar: Lagtext = {
        "sfs_nr":    resultat["sfs_nr"],
        "rubrik":    resultat.get("rubrik"),
        "t_o_m_sfs": resultat.get("t_o_m_sfs"),
        "lagtext":   resultat.get("lagtext"),
    }

    lagtext = resultat.get("lagtext")
    if lagtext:
        utdrag = _skar_ut(lagtext, max_tecken, fran_tecken)
        svar["lagtext"]              = utdrag["text"]
        svar["tecken_totalt"]        = utdrag["tecken_totalt"]
        svar["tecken_visade"]        = utdrag["tecken_visade"]
        svar["trunkerad"]            = utdrag["trunkerad"]
        svar["fortsatt_fran_tecken"] = utdrag["fortsatt_fran_tecken"]
        if utdrag["trunkerad"]:
            svar["las_vidare"] = (
                f"Lagtexten är kapad. Läs vidare med "
                f"sfsr_hamta_lagtext('{sfs_nr}', "
                f"fran_tecken={utdrag['fortsatt_fran_tecken']})."
            )

    return svar


# ---------------------------------------------------------------------------
# Startpunkt
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    starta(mcp, standardport=8000, initiera=initiera_schema)
