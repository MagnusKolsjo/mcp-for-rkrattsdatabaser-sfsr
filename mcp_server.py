# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Magnus Kolsjö
# Se LICENSE-filen i repots rot för fullständig licenstext.

"""
mcp_server.py — MCP-server för SFSR ändringsregister

Exponerar tre verktyg till MCP-kompatibla AI-verktyg:
  sfsr_get_law_history       — hela ändringshistoriken för en lag
  sfsr_get_paragraph_history — ändringar som berör en specifik paragraf
  sfsr_trace_chain           — följer ändringskedjan bakåt (med propositionsreferenser)

Krav:
  - Konfiguration via .env (se config.example.env)
  - Installerade beroenden: pip install -r requirements.txt

Transport-lägen (styrs via MCP_TRANSPORT i .env):

  stdio (standard, lokal användning):
    python3 mcp_server.py
    MCP-klienten startar och hanterar processen direkt.

  http (hostad driftsättning):
    MCP_TRANSPORT=http python3 mcp_server.py
    Servern lyssnar på MCP_HOST:MCP_PORT (standard 127.0.0.1:8000).
    Sätt MCP_API_KEY till ett slumpmässigt genererat token:
      python3 -c "import secrets; print(secrets.token_hex(32))"
    I produktion: lägg en reverse proxy (t.ex. Nginx) framför servern.
"""

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").lower()
MCP_HOST      = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT      = int(os.getenv("MCP_PORT", "8000"))
MCP_API_KEY   = os.getenv("MCP_API_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP-server
# ---------------------------------------------------------------------------
mcp = FastMCP("SFSR — Svensk författningssamlings register")

# Importera verktygsfunktionerna efter att servern skapats (de läser .env)
from sfsr_tools import sfsr_get_law_history as _get_law_history
from sfsr_tools import sfsr_get_paragraph_history as _get_paragraph_history


@mcp.tool()
def sfsr_get_law_history(
    sfs_nr: str,
    inkludera_historiska: bool = False,
) -> str:
    """
    Hämtar hela ändringshistoriken för en lag från SFSR.

    Returnerar metadata om grundlagen samt en kronologisk lista av alla
    ändrings-SFS, med ikraftträdandedatum, berörda paragrafer och förarbeten
    (proposition, betänkande, riksdagsskrivelse).

    Parametrar:
      sfs_nr               — SFS-nummer för grundlagen, t.ex. "1993:1617"
      inkludera_historiska — om True inkluderas historiska poster (standard: False)

    Returnerar JSON med fälten:
      sfs_nr, rubrik, ikraft_grundlag, celex_grundlag,
      antal_andringar, andringar (lista)

    Varje ändring innehåller: andrings_sfs, rubrik, ikrafttradande,
    paragrafer, prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse.
    """
    try:
        resultat = _get_law_history(sfs_nr, inkludera_historiska=inkludera_historiska)
        return json.dumps(resultat, ensure_ascii=False, indent=2)
    except Exception as e:
        log.exception("Fel i sfsr_get_law_history för %s", sfs_nr)
        return json.dumps({"fel": str(e)}, ensure_ascii=False)


@mcp.tool()
def sfsr_get_paragraph_history(
    sfs_nr: str,
    paragraf: str,
) -> str:
    """
    Filtrerar ändringshistoriken till poster som berör en specifik paragraf.

    Använd detta för att spåra hur en enskild paragraf förändrats över tid —
    t.ex. vilka propositioner som lett till att paragrafen ändrats och när.

    Parametrar:
      sfs_nr   — SFS-nummer för grundlagen, t.ex. "1993:1617"
      paragraf — paragrafbeteckning, t.ex. "2 kap. 8 §" eller "3 §"

    Returnerar JSON-lista av ändrings-SFS i kronologisk ordning.
    Varje post innehåller: andrings_sfs, rubrik, ikrafttradande,
    paragrafer, prop, bet, rskr, celex, eu_direktiv, overgangsbestammelse.
    Tom lista om inga träffar.

    Tips: hämta först hela historiken med sfsr_get_law_history för att se
    vilka paragrafer som ändrats och hur de är betecknade i SFSR.
    """
    try:
        resultat = _get_paragraph_history(sfs_nr, paragraf)
        return json.dumps(resultat, ensure_ascii=False, indent=2)
    except Exception as e:
        log.exception("Fel i sfsr_get_paragraph_history för %s §%s", sfs_nr, paragraf)
        return json.dumps({"fel": str(e)}, ensure_ascii=False)


@mcp.tool()
def sfsr_trace_chain(
    sfs_nr: str,
    paragraf: Optional[str] = None,
    djup: int = 5,
) -> str:
    """
    Följer ändringskedjan bakåt för en lag (eller paragraf) och returnerar
    en ordnad lista av kedjeled med källa, datum och propositionsreferens.

    Varje kedjeled representerar ett ändrings-SFS med tillhörande förarbeten.
    Verktyget kombinerar data från SFSR med riksdagens API för att ge
    fullständig spårbarhet från gällande rätt tillbaka till ursprungsproposition.

    Parametrar:
      sfs_nr  — SFS-nummer för grundlagen, t.ex. "1993:1617"
      paragraf — om angiven filtreras kedjan till ändringar som rör just
                 den paragrafen, t.ex. "2 kap. 8 §"
      djup    — max antal kedjeled att följa (standard: 5, max: 20)

    Returnerar JSON-lista av kedjeled i omvänd kronologisk ordning (nyast först).
    Varje led innehåller: andrings_sfs, ikrafttradande, paragrafer,
    prop, bet, rskr, celex, eu_direktiv.

    OBS: Integration med riksdagens API (för att hämta propositionstexter)
    implementeras i nästa version. Nuvarande version returnerar SFSR-data
    med propositionsreferenser — slå upp propositionerna med rd_get_document
    från arbetsström 3.
    """
    djup = min(max(1, djup), 20)
    try:
        if paragraf:
            andringar = _get_paragraph_history(sfs_nr, paragraf)
        else:
            lag = _get_law_history(sfs_nr)
            andringar = lag["andringar"]

        # Returnera de senaste `djup` ändringarna i omvänd ordning (nyast först)
        kedjeled = list(reversed(andringar[-djup:]))

        resultat = {
            "sfs_nr":   sfs_nr,
            "paragraf": paragraf,
            "djup":     djup,
            "kedjeled": kedjeled,
            "not":      (
                "Propositionstexter hämtas via rd_get_document i riksdagens API-server "
                "(arbetsström 3). Ange prop-värdet som dok_id."
            ),
        }
        return json.dumps(resultat, ensure_ascii=False, indent=2)
    except Exception as e:
        log.exception("Fel i sfsr_trace_chain för %s", sfs_nr)
        return json.dumps({"fel": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Startpunkt
# ---------------------------------------------------------------------------

def _starta_http() -> None:
    """Startar servern i HTTP-läge med valfri Bearer-token-autentisering."""
    try:
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response
        import uvicorn
    except ImportError:
        log.error("HTTP-läge kräver: pip install starlette uvicorn")
        raise

    class ApiKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if MCP_API_KEY:
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or auth[7:] != MCP_API_KEY:
                    return Response("Obehörig åtkomst", status_code=401)
            return await call_next(request)

    starlette_app = Starlette(middleware=[Middleware(ApiKeyMiddleware)])
    # Montera MCP-applikationen på Starlette
    starlette_app.mount("/", mcp.get_asgi_app())

    log.info("Startar HTTP-server på %s:%s", MCP_HOST, MCP_PORT)
    uvicorn.run(starlette_app, host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    if MCP_TRANSPORT == "http":
        _starta_http()
    else:
        log.info("Startar stdio-server")
        mcp.run()
