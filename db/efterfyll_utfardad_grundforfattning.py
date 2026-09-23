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
hämtar om varje sådan rad från källan och skriver tillbaka hela posten,
via samma upsert som normal cachning (`hamta_lag(..., tvinga_uppdatering=True)`).

Idempotent: en andra körning träffar bara rader som fortfarande saknar
utfardad_grundforfattning — antingen för att källan verkligen saknar
datumet (ett äkta innehållsgap, skilt från kodbuggen ovan) eller för att
raden tillkommit sedan förra körningen.

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
    """Hämtar om varje påverkad rad och skriver tillbaka den fullständiga posten."""
    from sfsr_scraper import hamta_lag

    sfs_nummer = _hamta_paverkade_sfs_nr()
    log.info("%d rader saknar utfardad_grundforfattning och hämtas om.", len(sfs_nummer))

    lyckade = 0
    fortfarande_null = 0
    misslyckade: list[str] = []

    for i, sfs_nr in enumerate(sfs_nummer, start=1):
        try:
            data = hamta_lag(sfs_nr, tvinga_uppdatering=True)
            if data.get("utfardad_grundforfattning"):
                lyckade += 1
            else:
                # Källan saknar fortfarande datumet för denna författning —
                # ett äkta innehållsgap, inte ett tecken på att rättelsen
                # inte fungerar.
                fortfarande_null += 1
            log.info(
                "(%d/%d) %s: utfardad_grundforfattning=%s",
                i, len(sfs_nummer), sfs_nr, data.get("utfardad_grundforfattning"),
            )
        except Exception as exc:
            log.warning("(%d/%d) %s: hämtning misslyckades — %s", i, len(sfs_nummer), sfs_nr, exc)
            misslyckade.append(sfs_nr)
        time.sleep(_PAUS_SEKUNDER)

    log.info(
        "Klart. %d rader fyllda i, %d fortfarande null (källans egna innehållsgap), "
        "%d misslyckade.",
        lyckade, fortfarande_null, len(misslyckade),
    )
    if misslyckade:
        log.warning("Misslyckade SFS-nummer: %s", ", ".join(misslyckade))


if __name__ == "__main__":
    from init_db import _maskera_url

    log.info("DATABASE_URL: %s", _maskera_url(os.getenv("DATABASE_URL", "sqlite:///sfsr_cache.db")))
    kor_efterfyllning()
