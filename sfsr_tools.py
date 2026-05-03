"""
sfsr_tools.py — MCP-verktygsfunktioner för SFSR ändringsregister

Verktygen används av mcp_server.py och kan även importeras direkt vid testning.
Alla funktioner returnerar JSON-serialiserbara dict/list-strukturer.
"""

from __future__ import annotations

import re
from typing import Any

from sfsr_scraper import hamta_lag


# ---------------------------------------------------------------------------
# sfsr_get_law_history
# ---------------------------------------------------------------------------

def sfsr_get_law_history(sfs_nr: str, inkludera_historiska: bool = False) -> dict:
    """
    Hämtar hela ändringshistoriken för en lag.

    Returnerar metadata om grundlagen samt en kronologisk lista av alla
    ändrings-SFS, med ikraftträdandedatum, berörda paragrafer och förarbeten.

    Args:
        sfs_nr:               SFS-nummer för grundlagen, t.ex. "1993:1617"
        inkludera_historiska: Om True inkluderas historiska och borttagna poster
                              (standard: False — filtreras bort)

    Returns:
        {
          "sfs_nr":          str,
          "rubrik":          str | None,
          "ikraft_grundlag": str | None,   # ÅÅÅÅ-MM-DD
          "celex_grundlag":  str | None,   # radbrytningsseparerade CELEX-nr
          "antal_andringar": int,
          "andringar": [
            {
              "andrings_sfs":         str,
              "rubrik":               str | None,
              "ikrafttradande":       str | None,
              "paragrafer":           str | None,
              "prop":                 str | None,
              "bet":                  str | None,
              "rskr":                 str | None,
              "celex":                str | None,
              "eu_direktiv":          bool,
              "overgangsbestammelse": bool,
            }, ...
          ]
        }
    """
    data = hamta_lag(sfs_nr)

    andringar = data.get("andringar", [])
    if not inkludera_historiska:
        andringar = [
            a for a in andringar
            if not a.get("historisk") and not a.get("borttagen")
        ]

    # Rensa interna fält som inte ska exponeras via MCP
    andringar_ut = [
        {k: v for k, v in a.items() if k not in ("historisk", "borttagen")}
        for a in andringar
    ]

    return {
        "sfs_nr":          data["sfs_nr"],
        "rubrik":          data.get("rubrik"),
        "ikraft_grundlag": data.get("ikraft_grundlag"),
        "celex_grundlag":  data.get("celex_grundlag"),
        "antal_andringar": len(andringar_ut),
        "andringar":       andringar_ut,
    }


# ---------------------------------------------------------------------------
# sfsr_get_paragraph_history
# ---------------------------------------------------------------------------

def _beror_paragraf(paragrafer_text: str | None, paragraf: str) -> bool:
    """
    Returnerar True om paragrafer_text berör den givna paragrafen.

    Hanterar:
    - Exakt match:        "3 §" matchar "3 §"
    - Intervall:          "3-5 §§" matchar "3 §", "4 §", "5 §"
    - Kapitelreferens:    "2 kap. 3 §" matchar "2 kap. 3 §"
    - Fri text:           innehåller paragrafnumret som delord
    """
    if not paragrafer_text:
        return False

    # Normalisera söktermen
    paragraf_norm = paragraf.strip().lower()

    # Enkel fallback: literal substring-match
    if paragraf_norm in paragrafer_text.lower():
        return True

    # Försök matcha "N §" med intervalltolkning
    nummer_match = re.search(r"(\d+)\s*§", paragraf_norm)
    if not nummer_match:
        return False
    sokt_nr = int(nummer_match.group(1))

    # Kolla kapitelkontext (om söktermen innehåller "kap.")
    kap_match = re.search(r"(\d+)\s*kap", paragraf_norm)
    sokt_kap = int(kap_match.group(1)) if kap_match else None

    text_lower = paragrafer_text.lower()

    # Hitta alla intervall i paragrafer_text
    for m in re.finditer(r"(\d+)\s*-\s*(\d+)\s*§§?", text_lower):
        start, slut = int(m.group(1)), int(m.group(2))
        # Om söktermen har kapitelkontext, kolla att rätt kap. nämns
        if sokt_kap:
            kap_i_text = re.search(r"(\d+)\s*kap", text_lower[:m.start()])
            if not kap_i_text or int(kap_i_text.group(1)) != sokt_kap:
                continue
        if start <= sokt_nr <= slut:
            return True

    return False


def sfsr_get_paragraph_history(sfs_nr: str, paragraf: str) -> list[dict]:
    """
    Filtrerar ändringshistoriken till de poster som berör en specifik paragraf.

    Args:
        sfs_nr:   SFS-nummer för grundlagen, t.ex. "1993:1617"
        paragraf: Paragrafbeteckning, t.ex. "2 kap. 8 §" eller "3 §"

    Returns:
        Lista av ändrings-SFS (samma fältuppsättning som i sfsr_get_law_history)
        som berörs av den angivna paragrafen, i kronologisk ordning.
        Tom lista om inga träffar.
    """
    data = hamta_lag(sfs_nr)
    andringar = [
        a for a in data.get("andringar", [])
        if not a.get("historisk")
        and not a.get("borttagen")
        and _beror_paragraf(a.get("paragrafer"), paragraf)
    ]

    return [
        {k: v for k, v in a.items() if k not in ("historisk", "borttagen")}
        for a in andringar
    ]
