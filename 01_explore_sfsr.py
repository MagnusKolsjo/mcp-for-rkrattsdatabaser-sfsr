#!/usr/bin/env python3
"""
Utforskningsskript för SFSR (Svensk Författningssamlings Register).

Skriptet hämtar och analyserar HTML-strukturen på rkrattsbaser.gov.se/sfsr
för att dokumentera hur ändringsregistret är uppbyggt och verifiera att
parsningen fungerar korrekt. Används som underlag för mcp_server.py.

Testlagar:
  SFS 1993:1617 — Ordningslag (liten lag, ett CELEX-nr)
  SFS 1998:808  — Miljöbalk (stor lag, 173+ andringar, många CELEX-nr)
  SFS 1942:740  — Rättegångsbalk (gammal lag, lång ändringshistorik)

Körning:
  pip install requests beautifulsoup4
  python3 01_explore_sfsr.py

Fynd från körning 2026-05-03:
  - Strukturen är konsistent mellan lagar och storlekar.
  - SFSR kräver ingen autentisering och inga speciella headers.
  - Rubrik, Ikraft och Förarbeten kan saknas för gamla andringar (pre-1980).
  - CELEX-nr kan innehålla flera nummer i ett fält (mellanslag-separerade).
  - Grundförfattningen kan ha CELEX-nr (t.ex. Miljöbalken: 36 nummer).
  - "overg.best." i Ikraft-fältet signalerar en övergångsbestämmelse.
  - Ikraft-fält kan saknas helt för andringar av ikraftträdandebestämmelser.
"""

import re
from datetime import date

import requests
from bs4 import BeautifulSoup

SFSR_BASE_URL = "https://rkrattsbaser.gov.se/sfsr"
USER_AGENT = "Mozilla/5.0 (compatible; riksdag-mcp-bot/1.0)"

TESTLAGAR = [
    ("1993:1617", "Ordningslag — liten lag, ett CELEX-nr"),
    ("1998:808",  "Miljöbalk — stor lag, 173+ andringar, många CELEX-nr"),
    ("1942:740",  "Rättegångsbalk — gammal lag, lång ändringshistorik"),
]


# ---------------------------------------------------------------------------
# Hämtning
# ---------------------------------------------------------------------------

def hamta_sfsr(sfs_nr: str) -> str:
    """Hämtar HTML för ett SFS-nummer från SFSR."""
    url = f"{SFSR_BASE_URL}?bet={sfs_nr}"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Parsning
# ---------------------------------------------------------------------------

def _text(element) -> str:
    """Hämtar rengjord text från ett BeautifulSoup-element."""
    if element is None:
        return ""
    return " ".join(element.get_text().split())


def _parse_ikraft(text: str) -> tuple[str, bool]:
    """
    Delar upp ett Ikraft-fält i datum och övergångsbestämmelse-flagga.

    En övergångsbestämmelse (overg.best.) reglerar hur skiftet mellan gammal
    och ny bestämmelse ska hanteras — t.ex. att pågående mål avgörs enligt
    äldre rätt, eller att en övergångsperiod löper under en tid.

    Exempel:
      "2005-04-01 overg.best." → ("2005-04-01", True)
      "2024-11-08"             → ("2024-11-08", False)
    """
    overg = "overg.best" in text
    datum = text.replace("overg.best.", "").strip()
    return datum, overg


def _parse_forarbeten(text: str) -> tuple[str, str, str]:
    """
    Extraherar prop, bet och rskr ur ett Förarbeten-fält.

    Exempel:
      "Prop. 2005/06:11, bet. 2005/06:JuU3, rskr. 2005/06:72"
      → ("Prop. 2005/06:11", "bet. 2005/06:JuU3", "rskr. 2005/06:72")
    """
    prop = bet = rskr = ""
    prop_m = re.search(r"Prop\.\s*\S+", text, re.IGNORECASE)
    bet_m  = re.search(r"bet\.\s*\S+",  text, re.IGNORECASE)
    rskr_m = re.search(r"rskr\.\s*\S+", text, re.IGNORECASE)
    if prop_m:
        prop = prop_m.group(0).rstrip(",")
    if bet_m:
        bet = bet_m.group(0).rstrip(",")
    if rskr_m:
        rskr = rskr_m.group(0).rstrip(",")
    return prop, bet, rskr


def _parse_celex(text: str) -> list[str]:
    """
    Returnerar lista med CELEX-nummer ur ett CELEX-nr-fält.
    Fältet kan innehålla flera nummer separerade med mellanslag.

    Exempel:
      "387R2658 370L0220 388L0077" → ["387R2658", "370L0220", "388L0077"]
    """
    return [token.strip() for token in text.split() if token.strip()]


def _etikett(sub_box) -> tuple[str, str]:
    """Returnerar (etikett, varde) för ett result-inner-sub-box-element."""
    bold = sub_box.select_one(".bold")
    etikett = _text(bold).rstrip(":") if bold else ""
    text = _text(sub_box)
    if etikett and text.startswith(etikett):
        text = text[len(etikett):].lstrip(":").strip()
    return etikett, text


def parsa_sfsr(html: str) -> dict:
    """
    Parsar en SFSR-sida och returnerar strukturerad data.

    Returstruktur:
    {
        "sfs_nr":      str,
        "rubrik":      str,
        "departement": str,
        "ikraft":      str,
        "prop":        str,
        "bet":         str,
        "rskr":        str,
        "celex":       [str],
        "andringar":   [
            {
                "andrings_sfs":         str,
                "rubrik":               str,
                "omfattning":           str,
                "ikrafttradande":       str,
                "overgangsbestammelse": bool,
                "prop":                 str,
                "bet":                  str,
                "rskr":                 str,
                "celex":                [str],
            }
        ]
    }

    Kantfall:
      - Rubrik på grundförfattningen identifieras via full_text == bold_text
        (SFS-numret innehåller ":", vilket utesluter villkor på ":").
      - Rubrik, Ikraft och Förarbeten kan saknas i gamla andringar (pre-1980).
      - CELEX-nr kan innehålla flera nummer (mellanslag-separerade).
      - Grundförfattningen kan ha egna CELEX-nr (t.ex. Miljöbalken: 36 nummer).
      - Ikraft-fält kan innehålla "overg.best." — flaggas som bool.
    """
    soup = BeautifulSoup(html, "html.parser")

    meta: dict = {
        "sfs_nr": "", "rubrik": "", "departement": "",
        "ikraft": "", "prop": "", "bet": "", "rskr": "", "celex": []
    }

    for box in soup.select(".result-inner-box"):
        if box.find_parent(class_="result-inner-sub-box-container"):
            continue

        full_text = _text(box)
        bold = box.select_one(".bold")
        bold_text = _text(bold) if bold else ""

        if "SFS-nummer" in full_text:
            m = re.search(r"(\d{4}:\d+)", full_text)
            if m:
                meta["sfs_nr"] = m.group(1)
        elif bold and full_text == bold_text:
            # Lagens rubrik: hela box-texten är den feta texten (inga etiketter)
            meta["rubrik"] = bold_text
        elif bold_text.startswith("Departement"):
            meta["departement"] = full_text.replace("Departement:", "").strip()
        elif bold_text.startswith("Ikraft"):
            meta["ikraft"] = full_text.replace("Ikraft:", "").strip()
        elif bold_text.startswith("Förarbeten"):
            ft = full_text.replace("Förarbeten:", "").strip()
            meta["prop"], meta["bet"], meta["rskr"] = _parse_forarbeten(ft)
        elif bold_text.startswith("CELEX"):
            ct = full_text.replace("CELEX-nr:", "").strip()
            meta["celex"] = _parse_celex(ct)

    # Ändringar
    andringar = []
    for container in soup.select(".result-inner-sub-box-container"):
        header = container.select_one(".result-inner-sub-box-header")
        header_text = _text(header)
        sfs_m = re.search(r"SFS\s+(\d{4}:\d+)", header_text)
        andrings_sfs = sfs_m.group(1) if sfs_m else header_text

        andring: dict = {
            "andrings_sfs": andrings_sfs,
            "rubrik": "",
            "omfattning": "",
            "ikrafttradande": "",
            "overgangsbestammelse": False,
            "prop": "",
            "bet": "",
            "rskr": "",
            "celex": [],
        }

        for sub in container.select(".result-inner-sub-box"):
            etikett, varde = _etikett(sub)
            if etikett == "Rubrik":
                andring["rubrik"] = varde
            elif etikett == "Omfattning":
                andring["omfattning"] = varde
            elif etikett == "Ikraft":
                datum, overg = _parse_ikraft(varde)
                andring["ikrafttradande"] = datum
                andring["overgangsbestammelse"] = overg
            elif etikett == "Förarbeten":
                p, b, r = _parse_forarbeten(varde)
                andring["prop"] = p
                andring["bet"] = b
                andring["rskr"] = r
            elif etikett == "CELEX-nr":
                andring["celex"] = _parse_celex(varde)

        andringar.append(andring)

    meta["andringar"] = andringar
    return meta


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def rapport(sfs_nr: str, beskrivning: str) -> None:
    """Hämtar och rapporterar om en lag."""
    print(f"\n{'='*60}")
    print(f"  {sfs_nr} — {beskrivning}")
    print(f"{'='*60}")

    try:
        html = hamta_sfsr(sfs_nr)
    except requests.RequestException as e:
        print(f"  FEL vid hämtning: {e}")
        return

    data = parsa_sfsr(html)

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
    print(f"  Varav med overg.best:       {len(med_overg)}")
    print(f"  Saknar Rubrik-fält:         {len(saknar_rubrik)}")
    print(f"  Saknar Ikraft-datum:        {len(saknar_ikraft)}")

    if andringar:
        print(f"\n  Första andring:")
        for k, v in andringar[0].items():
            print(f"    {k}: {v}")
        if len(andringar) > 1:
            print(f"\n  Senaste andring (#{len(andringar)}):")
            for k, v in andringar[-1].items():
                print(f"    {k}: {v}")

    if med_celex:
        ex = med_celex[0]
        print(f"\n  Exempel med CELEX-nr: SFS {ex['andrings_sfs']}: {ex['celex']}")

    if saknar_rubrik:
        print(f"\n  OBS: Ändring utan Rubrik — {saknar_rubrik[0]['andrings_sfs']}")
        print(f"       Omfattning: {saknar_rubrik[0]['omfattning']}")


def main() -> None:
    print("SFSR-strukturutforskning")
    print(f"Datum: {date.today()}")
    print(f"Källa: {SFSR_BASE_URL}")

    for sfs_nr, beskrivning in TESTLAGAR:
        rapport(sfs_nr, beskrivning)

    print(f"\n{'='*60}")
    print("Dokumenterade kantfall")
    print(f"{'='*60}")
    print("""
  1. Rubrik på grundförfattningen identifieras via full_text == bold_text
     (SFS-numret innehåller ":", vilket utesluter check på ":").

  2. Rubrik-fältet kan saknas på en andring (t.ex. SFS 1998:811 —
     en ren ikraftträdandepost utan separat ändringsrubrik).

  3. Ikraft-datum kan saknas (andringar av ikraftträdandebestämmelser
     eller gamla andringar med ofullständig registrering).

  4. "overg.best." i Ikraft-fältet signalerar en övergångsbestämmelse:
     regler för hur skiftet mellan gammal och ny bestämmelse ska hanteras
     (t.ex. att pågående mål avgörs enligt äldre rätt). Flaggas som bool.

  5. CELEX-nr kan innehålla flera nummer i ett fält (mellanslag-sep.).

  6. Grundförfattningen kan ha egna CELEX-nr (Miljöbalken: 36 nummer).

  7. Ändringar av andringar förekommer (t.ex. SFS 2021:862 ändrar 2021:6).
""")


if __name__ == "__main__":
    main()
