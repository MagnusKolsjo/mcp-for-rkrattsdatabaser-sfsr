"""
db/init_db.py — Initierar databasen för arbetsström 8 (SFSR ändringsregister)

Läser DATABASE_URL från .env och skapar rätt tabeller beroende på databastyp:
  - postgresql://...  →  PostgreSQL med schema sfsr  (schema_postgres.sql)
  - sqlite:///...     →  SQLite, separat .db-fil      (schema_sqlite.sql)

Körning:
    python db/init_db.py

Krav (PostgreSQL):
    pip install psycopg2-binary

Krav (SQLite):
    Inga extra beroenden — sqlite3 ingår i Python-standardbiblioteket.
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///sfsr_cache.db")
SCHEMA_DIR = Path(__file__).parent


def init_postgres(url: str) -> None:
    """Initierar PostgreSQL-databas med sfsr-schema."""
    try:
        import psycopg2
    except ImportError:
        print("Fel: psycopg2 saknas. Kör: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    schema = (SCHEMA_DIR / "schema_postgres.sql").read_text(encoding="utf-8")

    conn = psycopg2.connect(url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(schema)
    conn.close()

    print("PostgreSQL-databas initierad (schema: sfsr).")


def init_sqlite(url: str) -> None:
    """Initierar SQLite-databas."""
    db_path = url.replace("sqlite:///", "")
    schema = (SCHEMA_DIR / "schema_sqlite.sql").read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    print(f"SQLite-databas initierad: {db_path}")


def main() -> None:
    print(f"DATABASE_URL: {DATABASE_URL}")

    if DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://"):
        init_postgres(DATABASE_URL)
    elif DATABASE_URL.startswith("sqlite:///"):
        init_sqlite(DATABASE_URL)
    else:
        print(f"Fel: okänt URL-format: {DATABASE_URL}", file=sys.stderr)
        print("Ange antingen postgresql://... eller sqlite:///...", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
