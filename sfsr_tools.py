# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Magnus Kolsjö
# Se LICENSE-filen i repots rot för fullständig licenstext.

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
# sfsr_hamta_andringshistorik
# ---------------------------------------------------------------------------

def sfsr_hamta_andringshistorik(sfs_nr: str) -> dict:
    """
    Hämtar hela ändringshistoriken för en lag.

    Returnerar metadata om grundförfattningen samt en kronologisk lista av alla
    ändrings-SFS, med ikraftträdandedatum, berörda paragrafer och förarbeten.

    Args:
        sfs_nr:               SFS-nummer för grundförfattningen, t.ex. "1993:1617"
    Returns:
        {
          "sfs_nr":                    str,
          "rubrik":                    str | None,
          "ikraft_grundforfattning":   str | None,   # ÅÅÅÅ-MM-DD
          "utfardad_grundforfattning": str | None,   # ÅÅÅÅ-MM-DD
          "upphavd_datum":             str | None,   # ÅÅÅÅ-MM-DD, None om ej upphävd
          "upphavd_genom":             str | None,   # ersättande SFS-nummer
          "departement":               str | None,
          "t_o_m_sfs":                 str | None,   # vilken version som visas
          "celex_grundforfattning":    list[str],    # CELEX-nr för grundförfattningen
          "prop_grundforfattning":     str | None,   # proposition för grundförfattningen
          "bet_grundforfattning":      str | None,   # betänkande för grundförfattningen
          "rskr_grundforfattning":     str | None,   # riksdagsskrivelse för grundförfattningen
          "cache_kalla":               str | None,   # "api" eller "html"
          "cachad_vid":                str | None,   # ISO-tidpunkt för senaste cachning
          "antal_andringar":           int,
          "andringar": [
            {
              "andrings_sfs":         str,
              "rubrik":               str | None,
              "ikrafttradande":       str | None,
              "paragrafer":           str | None,
              "prop":                 str | None,
              "bet":                  str | None,
              "rskr":                 str | None,
              "celex":                list[str],
              "eu_direktiv":          bool,
              "overgangsbestammelse": bool,
              "historisk":            bool,
            }, ...
          ]
        }
    """
    data = hamta_lag(sfs_nr)

    andringar = data.get("andringar", [])

    # Rensa interna fält som inte ska exponeras via MCP
    # 'borttagen' är ett internt API-fält som inte är meningsfullt utåt.
    # 'historisk' exponeras — det är relevant för att tolka datakvaliteten.
    andringar_ut = [
        {k: v for k, v in a.items() if k != "borttagen"}
        for a in andringar
    ]

    return {
        "sfs_nr":                    data["sfs_nr"],
        "rubrik":                    data.get("rubrik"),
        "ikraft_grundforfattning":   data.get("ikraft_grundforfattning"),
        "utfardad_grundforfattning": data.get("utfardad_grundforfattning"),
        "upphavd_datum":             data.get("upphavd_datum"),
        "upphavd_genom":             data.get("upphavd_genom"),
        "departement":               data.get("departement"),
        "t_o_m_sfs":                 data.get("t_o_m_sfs"),
        "celex_grundforfattning":    data.get("celex_grundforfattning") or [],
        "prop_grundforfattning":     data.get("prop_grundforfattning"),
        "bet_grundforfattning":      data.get("bet_grundforfattning"),
        "rskr_grundforfattning":     data.get("rskr_grundforfattning"),
        "cache_kalla":               data.get("cache_kalla"),
        "cachad_vid":                data.get("cachad_vid"),
        "antal_andringar":           len(andringar_ut),
        "andringar":                 andringar_ut,
    }


# ---------------------------------------------------------------------------
# sfsr_hamta_lagtext
# ---------------------------------------------------------------------------

def sfsr_hamta_lagtext(sfs_nr: str) -> dict:
    """
    Hämtar den konsoliderade lagtexten för en grundförfattning.

    Lagtexten är den version som visas på rkrattsbaser.gov.se, uppdaterad
    t.o.m. det SFS-nummer som anges i t_o_m_sfs.

    Om lagtexten saknas i cachen (t.ex. för äldre cachade rader) hämtas
    posten om automatiskt från källan.

    Args:
        sfs_nr:   SFS-nummer för grundförfattningen, t.ex. "1993:1617"
    Returns:
        {
          "sfs_nr":    str,
          "rubrik":    str | None,
          "t_o_m_sfs": str | None,   # "t.o.m. SFS ÅÅÅÅ:NNN"
          "lagtext":   str | None,   # konsoliderad lagtext (kan vara None om
                                     #  källan inte tillhandahåller fulltext)
        }
    """
    data = hamta_lag(sfs_nr)

    # Om lagtexten saknas i cachen (äldre post), tvinga en ny hämtning.
    if data.get("lagtext") is None:
        data = hamta_lag(sfs_nr, tvinga_uppdatering=True)

    return {
        "sfs_nr":    data["sfs_nr"],
        "rubrik":    data.get("rubrik"),
        "t_o_m_sfs": data.get("t_o_m_sfs"),
        "lagtext":   data.get("lagtext"),
    }


# ---------------------------------------------------------------------------
# sfsr_hamta_paragrafhistorik
# ---------------------------------------------------------------------------

# Ordinaltal (svenska) → arabiska siffror
_ORDINALTAL: dict[str, str] = {
    "första": "1", "andre": "2", "andra": "2", "tredje": "3",
    "fjärde": "4", "femte": "5", "sjätte": "6", "sjunde": "7",
    "åttonde": "8", "nionde": "9", "tionde": "10",
    "elfte": "11", "tolfte": "12", "trettonde": "13",
}


def _normalisera_paragraf_input(paragraf: str) -> str:
    """
    Normaliserar en paragrafbeteckning från godtyckligt naturligt språk
    till kanonisk form "N kap M §" (eller "M §" om inget kapitel anges).

    Hanterar bl.a.:
    - "2 kap. 8 §", "2 kap 8 §"            (formell juridisk form)
    - "2:8", "2:8 §"                        (förkortad form)
    - "8 § i kap. 2", "8 § kap 2"          (omvänd ordning)
    - "8 paragrafen i 2:a kapitlet"         (talspråk)
    - "andra kapitlet 8 §"                  (ordinaltal)
    - "kapitel 2 paragraf 8"                (utskrivet)
    - "para 8 kap 2"                        (informell förkortning)
    """
    text = paragraf.lower().strip()

    # Ersätt svenska ordinaltal med siffror
    for ord_text, siffra in _ORDINALTAL.items():
        text = re.sub(rf"\b{ord_text}\b", siffra, text)

    # Normalisera böjningsändelser: "2:a", "3:e", "2:de" → "2", "3"
    text = re.sub(r"(\d+)\s*:(?:a|e|de|te|nde|dje)\b", r"\1", text)

    # Normalisera "para N" → "paragraf N" (undviker att N felaktigt tas som kapitel)
    text = re.sub(r"\bpara\.?\s+(\d+)", r"paragraf \1", text)

    # Normalisera "kap.", "kapitlet", "kapitel" → "kap"
    text = re.sub(r"\bkap\.", "kap", text)
    text = re.sub(r"\bkapitlet\b", "kap", text)
    text = re.sub(r"\bkapitel\b", "kap", text)

    # Format "N:M" → kap N, para M (t.ex. "2:8")
    m = re.match(r"^(\d+):(\d+)\s*§?$", text.strip())
    if m:
        return f"{m.group(1)} kap {m.group(2)} §"

    # Standardmönstret "N kap M §" som ett block — det vanligaste formatet.
    # Täcker t.ex. "2 kap 8 §", "andra kapitlet 5 §" (efter ordinalersättning).
    m = re.search(r"(\d+)\s*kap\s+(\d+)\s*§", text)
    if m:
        return f"{m.group(1)} kap {m.group(2)} §"

    # Extrahera kapitel och paragraf separat (omvänd ordning m.m.)
    kap_nr = None
    para_nr = None

    # Kapitel: "kap N" (nummer efter kap) — t.ex. "8 § i kap 2"
    kap_m = re.search(r"\bkap\s+(\d+)", text)
    if kap_m:
        kap_nr = int(kap_m.group(1))
    else:
        # Kapitel: "N kap" (nummer före kap)
        kap_m = re.search(r"(\d+)\s*kap\b", text)
        if kap_m:
            kap_nr = int(kap_m.group(1))

    # Paragraf: "N §", "N paragrafen", "paragraf N"
    para_m = re.search(r"(\d+)\s*(?:§|paragrafen?\b)", text)
    if not para_m:
        para_m = re.search(r"(?:paragraf)\s+(\d+)", text)
    if para_m:
        para_nr = int(para_m.group(1))

    if kap_nr and para_nr:
        return f"{kap_nr} kap {para_nr} §"
    elif para_nr:
        return f"{para_nr} §"
    else:
        return paragraf

def _beror_paragraf(paragrafer_text: str | None, paragraf: str) -> bool:
    """
    Returnerar True om paragrafer_text berör den givna paragrafen.

    Hanterar alla format som förekommer i SFSR:s API-svar:
    - Explicit: "2 kap 8 §"  (§ direkt efter numret)
    - Lista:    "2 kap 8, 13, 28 §§"  (§§ i slutet av listan)
    - Med punkt: "2 kap. 8 §" eller "2 kap. 6, 7 a, 8, 9 §§"
    - Intervall: "3-5 §§"
    - Utan kapitel: "3 §"
    """
    if not paragrafer_text:
        return False

    # Normalisera: ta bort punkt efter "kap" i båda strängarna för konsekvent jämförelse
    def norm(s: str) -> str:
        return re.sub(r"\bkap\.", "kap", s.lower())

    text_norm = norm(paragrafer_text)
    para_norm = norm(paragraf.strip())

    # Steg 1: Direkt substring-match efter normalisering
    # Täcker t.ex. "2 kap 8 §" som explicit delsträng i texten
    if para_norm in text_norm:
        return True

    # Extrahera kapitel- och paragrafnummer ur söktermen
    kap_match = re.search(r"(\d+)\s*kap", para_norm)
    nr_match = re.search(r"(\d+)\s*§", para_norm)
    if not nr_match:
        return False
    sokt_nr = int(nr_match.group(1))
    sokt_kap = int(kap_match.group(1)) if kap_match else None

    if sokt_kap:
        # Steg 2: Kapitel-medveten listmatchning
        # Hitta "N kap <lista> §§?" och kontrollera om paragrafnumret finns i listan
        # Exempel: "2 kap 8, 13, 28 §§" → kapitel=2, lista=[8, 13, 28]
        kap_pattern = rf"\b{sokt_kap}\s+kap\s+([\d\s,a-z]+?)\s*§§?"
        for m in re.finditer(kap_pattern, text_norm):
            numrar = re.findall(r"\b(\d+)\b", m.group(1))
            if str(sokt_nr) in numrar:
                return True
    else:
        # Steg 3: Utan kapitelkontext — sök paragrafnumret i alla paragrafsektioner
        for m in re.finditer(r"([\d\s,a-z]+?)\s*§§?", text_norm):
            numrar = re.findall(r"\b(\d+)\b", m.group(1))
            if str(sokt_nr) in numrar:
                return True

    # Steg 4: Intervall-matchning, t.ex. "3-5 §§"
    for m in re.finditer(r"(\d+)\s*-\s*(\d+)\s*§§?", text_norm):
        start, slut = int(m.group(1)), int(m.group(2))
        if sokt_kap:
            kap_i_text = re.search(r"(\d+)\s*kap", text_norm[:m.start()])
            if not kap_i_text or int(kap_i_text.group(1)) != sokt_kap:
                continue
        if start <= sokt_nr <= slut:
            return True

    return False


def sfsr_hamta_paragrafhistorik(sfs_nr: str, paragraf: str) -> list[dict]:
    """
    Filtrerar ändringshistoriken till de poster som berör en specifik paragraf.

    Args:
        sfs_nr:   SFS-nummer för grundförfattningen, t.ex. "1993:1617"
        paragraf: Paragrafbeteckning, t.ex. "2 kap. 8 §" eller "3 §"

    Returns:
        Lista av ändrings-SFS (samma fältuppsättning som i sfsr_hamta_andringshistorik)
        som berörs av den angivna paragrafen, i kronologisk ordning.
        Tom lista om inga träffar.
    """
    data = hamta_lag(sfs_nr)
    # Normalisera söktermen för att hantera naturliga uttryck
    paragraf_norm = _normalisera_paragraf_input(paragraf)
    andringar = [
        a for a in data.get("andringar", [])
        if _beror_paragraf(a.get("paragrafer"), paragraf_norm)
    ]

    return [
        {k: v for k, v in a.items() if k != "borttagen"}
        for a in andringar
    ]
