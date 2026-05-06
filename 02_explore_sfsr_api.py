#!/usr/bin/env python3
"""
Utforskningsskript för beta-API:et på beta.rkrattsbaser.gov.se.

Dokumenterar hur API-anropen ser ut, testar kantfall och visar hur
API-svaret mappas mot datamodellen i arbetsström 8. Används som
referens när mcp_server.py implementeras med SFSR_BACKEND=api.

API-endpoint (POST):
  https://beta.rkrattsbaser.gov.se/elasticsearch/SearchEsByRawJson

Bakgrund:
  beta.rkrattsbaser.gov.se är en JavaScript-SPA som anropar detta
  Elasticsearch-API internt. "Beta" avser att inte alla databaser
  är migrerade ännu — inte att tekniken är instabil. SFSR-databasen
  (den vi behöver) är fullt migrerad. API:et är primärkälla i
  arbetsström 8; HTML-skrapningen (01_explore_sfsr.py) är fallback.

Testlagar:
  SFS 1993:1617 — Ordningslag (liten lag, ett CELEX-nr)
  SFS 1998:808  — Miljöbalk (stor lag, 173 andringar, många CELEX-nr)
  SFS 1942:740  — Rättegångsbalk (396 andringar, gammal lag, rubrik=None)

Körning:
  pip install requests
  python3 02_explore_sfsr_api.py

Fynd från körning 2026-05-03:
  - API:et kräver ingen autentisering.
  - andringsforfattningar är INTE sorterade kronologiskt — sortera på
    ikraftDateTime eller beteckning i applikationskoden.
  - rubrik kan vara None (ej bara tom sträng) för gamla andringar.
  - ikraftDateTime kan vara None (andring av ikraftträdandebestämmelse).
  - celexnummer på grundförfattningen är radbrytningsseparerade (\n).
  - celexnummer på andring är kommaseparerade (, ).
  - eUdirektiv är en separat bool-flagga (i tillägg till celexnummer).
  - ikraftOvergangsbestammelse är en riktig bool — ingen texttolkning krävs.
  - URL:en innehåller "beta." — uppdatera SFSR_API_BASE_URL i .env när
    beta-sajten blir produktion (troligen bara ta bort "beta.").
"""

import re
from datetime import date, datetime

import requests

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

SFSR_API_BASE_URL = "https://beta.rkrattsbaser.gov.se"
SFSR_API_ENDPOINT = f"{SFSR_API_BASE_URL}/elasticsearch/SearchEsByRawJson"
USER_AGENT = "Mozilla/5.0 (compatible; riksdag-mcp-bot/1.0)"

TESTLAGAR = [
    ("1993:1617", "Ordningslag — liten lag, ett CELEX-nr"),
    ("1998:808",  "Miljöbalk — stor lag, många CELEX-nr"),
    ("1942:740",  "Rättegångsbalk — 396 andringar, gammal lag"),
]


# ---------------------------------------------------------------------------
# API-anrop
# ---------------------------------------------------------------------------

def hamta_via_api(beteckning: str) -> dict | None:
    """
    Hämtar en lag från beta-API:et via SFS-beteckning.

    Returnerar hela _source-objektet från Elasticsearch, eller None
    om lagen inte hittas.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": SFSR_API_BASE_URL + "/",
        "Origin": SFSR_API_BASE_URL,
    }
    payload = {
        "searchIndexes": ["Sfs"],
        "api": "search",
        "json": {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"beteckning.keyword": beteckning}},
                        {"term": {"publicerad": True}},
                    ]
                }
            },
            "size": 1,
        },
    }
    r = requests.post(SFSR_API_ENDPOINT, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    # Svaret är en JSON-sträng inuti JSON (dubbel-serialiserat)
    hits = r.json()
    if isinstance(hits, str):
        import json
        hits = json.loads(hits)
    traffar = hits.get("hits", {}).get("hits", [])
    return traffar[0]["_source"] if traffar else None


# ---------------------------------------------------------------------------
# Mappning mot datamodellen
# ---------------------------------------------------------------------------

def _datum(iso: str | None) -> str:
    """Konverterar ISO-datumstring till ÅÅÅÅ-MM-DD, eller tom sträng."""
    if not iso:
        return ""
    return iso[:10]  # "2005-04-01T00:00:00" → "2005-04-01"


def _parse_forarbeten(text: str | None) -> tuple[str, str, str]:
    """
    Extraherar prop, bet och rskr ur ett förarbeten-fält.
    Samma logik som i HTML-skraparen — fältet har samma textformat i API:et.
    """
    if not text:
        return "", "", ""
    prop = bet = rskr = ""
    pm = re.search(r"Prop\.\s*\S+", text, re.IGNORECASE)
    bm = re.search(r"bet\.\s*\S+",  text, re.IGNORECASE)
    rm = re.search(r"rskr\.\s*\S+", text, re.IGNORECASE)
    if pm:
        prop = pm.group(0).rstrip(",")
    if bm:
        bet  = bm.group(0).rstrip(",")
    if rm:
        rskr = rm.group(0).rstrip(",")
    return prop, bet, rskr


def _parse_celex_grundforfattning(text: str | None) -> list[str]:
    """
    Parsar CELEX-fältet på grundförfattningen.
    Numren är radbrytningsseparerade i API-svaret.
    """
    if not text:
        return []
    return [t.strip() for t in text.splitlines() if t.strip()]


def _parse_celex_andring(text: str | None) -> list[str]:
    """
    Parsar CELEX-fältet på en andring.

    Separatorn är inkonsekvent i API-svaret:
    - Komma (vanligast): "32000L0076, 32003R0304, ..."
    - Mellanslag (äldre poster): "387R2658 370L0220 388L0077"
    - Enstaka varde: "32010L0075"
    - EU-tidningsreferens (ej CELEX): "EUTL342/2009 s59" — behålls som-är

    Strategi: om komma förekommer, dela på komma, annars på mellanslag.
    """
    if not text:
        return []
    if "," in text:
        return [t.strip() for t in text.split(",") if t.strip()]
    return [t.strip() for t in text.split() if t.strip()]


def till_datamodell(kalldata: dict) -> dict:
    """
    Mappar ett API-svar mot datamodellen som definieras i arbetsström 8.

    Returnerar samma struktur som parsa_sfsr() i 01_explore_sfsr.py,
    vilket gör att mcp_server.py kan kalla endera backend och få
    identisk output.

    Mappningstabell:
      sfs_nr               ← beteckning
      rubrik               ← rubrik
      departement          ← organisation.namnOchEnhet
      ikraft               ← ikraftDateTime (ISO → datum)
      prop/bet/rskr        ← register.forarbeten (regex)
      celex (grundförfattning)     ← register.celexnummer (radbrytning-sep.)
      andrings_sfs         ← andringsforfattningar[n].beteckning
      rubrik (andring)     ← andringsforfattningar[n].rubrik (kan vara None)
      omfattning           ← andringsforfattningar[n].anteckningar
      ikrafttradande       ← andringsforfattningar[n].ikraftDateTime (ISO → datum)
      overgangsbestammelse ← andringsforfattningar[n].ikraftOvergangsbestammelse (bool)
      prop/bet/rskr        ← andringsforfattningar[n].forarbeten (regex)
      celex (andring)      ← andringsforfattningar[n].celexnummer (komma-sep.)
    """
    reg = kalldata.get("register", {})
    org = kalldata.get("organisation", {})
    prop, bet, rskr = _parse_forarbeten(reg.get("forarbeten"))

    # Ändringar — API:et ger dem i intern ordning, inte kronologisk.
    # Sorterar på ikraftDateTime (None-värden sist), sedan beteckning.
    def sorteringsnyckel(a):
        # Ändringar utan ikraftdatum (None) sorteras sist.
        # "9999" är större än alla riktiga datum på formatet "ÅÅÅÅ-MM-DD".
        dt = a.get("ikraftDateTime") or "9999-12-31"
        return (dt, a.get("beteckning", ""))

    raa_andringar = sorted(
        kalldata.get("andringsforfattningar", []),
        key=sorteringsnyckel
    )

    andringar = []
    for a in raa_andringar:
        ap, ab, ar = _parse_forarbeten(a.get("forarbeten"))
        andringar.append({
            "andrings_sfs":         a.get("beteckning", ""),
            "rubrik":               a.get("rubrik") or "",  # None → ""
            "omfattning":           a.get("anteckningar") or "",
            "ikrafttradande":       _datum(a.get("ikraftDateTime")),
            "overgangsbestammelse": bool(a.get("ikraftOvergangsbestammelse")),
            "prop":                 ap,
            "bet":                  ab,
            "rskr":                 ar,
            "celex":                _parse_celex_andring(a.get("celexnummer")),
        })

    return {
        "sfs_nr":      kalldata.get("beteckning", ""),
        "rubrik":      kalldata.get("rubrik", ""),
        "departement": org.get("namnOchEnhet", ""),
        "ikraft":      _datum(kalldata.get("ikraftDateTime")),
        "prop":        prop,
        "bet":         bet,
        "rskr":        rskr,
        "celex":       _parse_celex_grundforfattning(reg.get("celexnummer")),
        "andringar":   andringar,
    }


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def rapport(beteckning: str, beskrivning: str) -> None:
    """Hämtar och rapporterar om en lag via API:et."""
    print(f"\n{'='*60}")
    print(f"  {beteckning} — {beskrivning}")
    print(f"{'='*60}")

    try:
        kalldata = hamta_via_api(beteckning)
    except requests.RequestException as e:
        print(f"  FEL vid API-anrop: {e}")
        return

    if kalldata is None:
        print(f"  Lagen hittades inte i API:et.")
        return

    data = till_datamodell(kalldata)

    print(f"  Rubrik:        {data['rubrik']}")
    print(f"  Departement:   {data['departement']}")
    print(f"  Ikraft (lag):  {data['ikraft']}")
    print(f"  Prop (lag):    {data['prop']}")
    print(f"  CELEX (lag):   {len(data['celex'])} nummer")

    andringar = data["andringar"]
    print(f"\n  Antal andringar: {len(andringar)}")

    med_celex     = [a for a in andringar if a["celex"]]
    med_overg     = [a for a in andringar if a["overgangsbestammelse"]]
    saknar_rubrik = [a for a in andringar if not a["rubrik"]]
    saknar_ikraft = [a for a in andringar if not a["ikrafttradande"]]

    print(f"  Varav med CELEX-nr:         {len(med_celex)}")
    print(f"  Varav med overg.best.:      {len(med_overg)}")
    print(f"  Saknar rubrik:              {len(saknar_rubrik)}")
    print(f"  Saknar ikraft-datum:        {len(saknar_ikraft)}")

    if andringar:
        print(f"\n  Första andring (kronologisk):")
        for k, v in andringar[0].items():
            print(f"    {k}: {v}")
        if len(andringar) > 1:
            print(f"\n  Senaste andring (#{len(andringar)}):")
            for k, v in andringar[-1].items():
                print(f"    {k}: {v}")

    if med_celex:
        ex = med_celex[0]
        print(f"\n  Exempel med CELEX: SFS {ex['andrings_sfs']}: {ex['celex']}")

    if saknar_rubrik:
        ex = saknar_rubrik[0]
        print(f"\n  OBS: Ändring utan rubrik — SFS {ex['andrings_sfs']}")
        print(f"       Omfattning: {ex['omfattning'][:80]}")


def main() -> None:
    print("SFSR API-utforskning (beta.rkrattsbaser.gov.se)")
    print(f"Datum:    {date.today()}")
    print(f"Endpoint: {SFSR_API_ENDPOINT}")

    for beteckning, beskrivning in TESTLAGAR:
        rapport(beteckning, beskrivning)

    print(f"\n{'='*60}")
    print("Dokumenterade kantfall")
    print(f"{'='*60}")
    print("""
  1. andringsforfattningar är INTE kronologiskt sorterade i API-svaret.
     Sortera på ikraftDateTime + beteckning i applikationskoden.
     None-värden (ingen ikraft) placeras sist med fallback '9999-12-31'.

  2. rubrik kan vara None (inte bara tom sträng) för gamla andringar.
     Normaliseras till "" i till_datamodell().

  3. ikraftDateTime kan vara None. Normaliseras till "" i _datum().

  4. celexnummer på grundförfattningen: radbrytningsseparerade (\n).
     celexnummer på andring: kommaseparerade (, ).
     Skilda parsningsfunktioner krävs.

  5. ikraftOvergangsbestammelse är en riktig bool — ingen texttolkning.
     I HTML-skraparen krävde "overg.best." textmatchning.

  6. eUdirektiv är en separat bool-flagga på ändringsposten.
     Finns inte i HTML-skrapningens datamodell — lägg till i schemat.

  7. Dubbla poster i HTML-sajten (t.ex. SFS 2023:426 visades 2 ggr)
     förekommer inte i API:et — det deduplicerar automatiskt.

  8. URL:en innehåller "beta." — uppdatera SFSR_API_BASE_URL i .env
     när beta-sajten blir produktion.
""")


if __name__ == "__main__":
    main()
