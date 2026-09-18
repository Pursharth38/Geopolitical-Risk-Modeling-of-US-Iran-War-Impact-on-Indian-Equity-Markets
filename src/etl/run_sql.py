"""Execute a .sql file (DDL) against the warehouse. Splits on ';'.

Usage: py src/etl/run_sql.py sql/views.sql
"""
from __future__ import annotations

import sys

from sqlalchemy import text

import config


def run_file(path: str) -> None:
    raw = open(path, encoding="utf-8").read()
    body = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("--"))
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    eng = config.get_engine()
    with eng.begin() as conn:
        for st in stmts:
            if st.upper().startswith("USE "):
                continue
            conn.execute(text(st))
    eng.dispose()
    print(f"ran {len(stmts)} statement(s) from {path}")


if __name__ == "__main__":
    run_file(sys.argv[1])
