# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Magnus Kolsjö
# Se LICENSE-filen i repots rot för fullständig licenstext.

"""
db.py — Databasinitiering för SFSR MCP-server

Skapar tabeller och index vid serverstart (idempotent).
Robustifierat mot att PostgreSQL-containern kan vara nere vid uppstart:
ett fel vid initieringen loggas som varning men stoppar inte servern.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///sfsr_cache.db")

_SCHEMA_DIR = Path(__file__).parent / "db"


def _ar_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")


def initiera_schema() -> None:
    """
    Skapar tabeller och index om de inte redan finns (idempotent).

    Anropas från mcp_server.py vid uppstart. Fel loggas som varning —
    servern avbryts inte om databasen är otillgänglig.
    """
    if not DATABASE_URL:
        log.warning("DATABASE_URL är inte satt — databasen används inte")
        return

    try:
        if _ar_postgres():
            try:
                import psycopg2
            except ImportError:
                log.error("psycopg2 saknas. Kör: pip install psycopg2-binary")
                sys.exit(1)
            schema = (_SCHEMA_DIR / "schema_postgres.sql").read_text(encoding="utf-8")
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute(schema)
            finally:
                conn.close()
            log.info("PostgreSQL-schema initierat (sfsr).")
        else:
            import sqlite3
            db_path = DATABASE_URL.replace("sqlite:///", "")
            schema = (_SCHEMA_DIR / "schema_sqlite.sql").read_text(encoding="utf-8")
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(schema)
                conn.commit()
            finally:
                conn.close()
            log.info("SQLite-databas initierad: %s", db_path)
    except Exception as exc:
        log.warning("Schema-initiering misslyckades — servern fortsätter ändå: %s", exc)
