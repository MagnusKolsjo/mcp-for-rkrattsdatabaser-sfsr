#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Magnus Kolsjö
# Se LICENSE-filen i repots rot för fullständig licenstext.

"""
db/efterfyll_utfardad_grundforfattning.py — engångsskript som fyller i
`utfardad_grundforfattning` för redan cachade rader.

Bakgrund: fram till rättelsen i sfsr_scraper.py lästes API-svarets
`utfardadDateTime` på fel nivå (toppnivå i stället för `fulltext.utfardadDateTime`),
så kolumnen `utfardad_grundforfattning` sparades alltid som null för rader
hämtade via API-backenden — oavsett vad källan faktiskt anger. Skriptet
hämtar om varje sådan rad direkt från API:et (`_hamta_via_api`, inte
`hamta_lag`) och skriver tillbaka hela posten.

Skriptet går förbi `hamta_lag()` med avsikt: den funktionen faller tillbaka
till HTML-skrapning om API-anropet misslyckas, och HTML-backenden saknar
`utfardadDateTime` helt. Ett sådant fallback skulle skriva över en redan
cachad API-rad med sämre HTML-data och göra bristen permanent — raden
skulle se ut som om källan saknade datumet, fast API-anropet bara råkade
misslyckas just då. Ett misslyckat API-anrop hoppas därför bara över (ingen
skrivning) och räknas separat, så att en omkörning tar upp raden igen.
Detta gäller oavsett vad `SFSR_BACKEND` står satt till i miljön.

Idempotent: en andra körning träffar bara rader som fortfarande saknar
utfardad_grundforfattning — antingen för att källan verkligen saknar
datumet via API:et (ett äkta innehållsgap, skilt från kodbuggen ovan),
för att förra körningens API-anrop misslyckades, eller för att raden
tillkommit sedan förra körningen.

Berör bara rader med cache_kalla='api'. HTML-backenden har aldrig haft
tillgång till fältet och lämnas orörd.

Körning mot en temporär testdatabas (rör aldrig driftdatabasen härifrån
under utveckling):

    DATABASE_URL=sqlite:////tmp/sfsr-test.db python3 db/efterfyll_utfardad_grundforfattning.py

Körning vid installation (mot driftdatabasen, som ett avsiktligt separat
steg — se README, avsnittet "Efterfyllning av utfardad_grundforfattning"):

    python3 db/efterfyll_utfardad_grundforfattning.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Sparsam paus mellan käll-anrop, projektets konvention för att inte belasta källan.
_PAUS_SEKUNDER = 0.5


def _hamta_paverkade_sfs_nr() -> list[str]:
    """Hämtar SFS-nummer för API-cachade rader som saknar utfardad_grundforfattning."""
    from sfsr_scraper import _hamta_db, _ph, _prefix

    p, ph = _prefix(), _ph()
    conn = _hamta_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT sfs_nr FROM {p}sfsr_lagar
                WHERE utfardad_grundforfattning IS NULL
                  AND cache_kalla = 'api'
                ORDER BY sfs_nr"""
        )
        return [rad[0] for rad in cur.fetchall()]
    finally:
        conn.close()


def kor_efterfyllning() -> None:
    """Hämtar om varje påverkad rad direkt via API-backenden och skriver tillbaka posten.

    Anropar `_hamta_via_api` direkt (se modul-docstringen för varför
    `hamta_lag()` och dess HTML-fallback medvetet undviks här).
    """
    from sfsr_scraper import _hamta_via_api, _normalisera_sfs, _spara_i_cache

    sfs_nummer = _hamta_paverkade_sfs_nr()
    log.info(
        "%d rader saknar utfardad_grundforfattning och hämtas om via API-backenden.",
        len(sfs_nummer),
    )

    lyckade = 0
    fortfarande_null = 0
    api_fel: list[str] = []

    for i, sfs_nr in enumerate(sfs_nummer, start=1):
        try:
            data = _hamta_via_api(_normalisera_sfs(sfs_nr))
        except Exception as exc:
            # API-anropet misslyckades (nätverk, källan nere, eller SFS-numret
            # inte längre i API:et). Ingen skrivning — raden tas upp igen vid
            # nästa körning i stället för att tystas ned som ett innehållsgap.
            log.warning("(%d/%d) %s: API-anrop misslyckades — %s", i, len(sfs_nummer), sfs_nr, exc)
            api_fel.append(sfs_nr)
            time.sleep(_PAUS_SEKUNDER)
            continue

        _spara_i_cache(data)
        if data.get("utfardad_grundforfattning"):
            lyckade += 1
        else:
            # API:et svarade, men saknar fortfarande datumet för denna
            # författning — ett äkta innehållsgap, inte ett tecken på att
            # rättelsen inte fungerar.
            fortfarande_null += 1
        log.info(
            "(%d/%d) %s: utfardad_grundforfattning=%s",
            i, len(sfs_nummer), sfs_nr, data.get("utfardad_grundforfattning"),
        )
        time.sleep(_PAUS_SEKUNDER)

    log.info(
        "Klart. %d rader fyllda i, %d fortfarande null (källans egna innehållsgap via API), "
        "%d API-fel (tas upp igen vid nästa körning).",
        lyckade, fortfarande_null, len(api_fel),
    )
    if api_fel:
        log.warning("API-fel för: %s", ", ".join(api_fel))


if __name__ == "__main__":
    from init_db import _maskera_url

    log.info("DATABASE_URL: %s", _maskera_url(os.getenv("DATABASE_URL", "sqlite:///sfsr_cache.db")))
    kor_efterfyllning()
