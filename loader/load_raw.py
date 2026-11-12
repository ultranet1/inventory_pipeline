#!/usr/bin/env python3
"""Load movement files into the raw_movements table of a DuckDB database.

Design (see README "Rerun safety"):
  * Columns are loaded as VARCHAR exactly as received: raw rows are never
    mutated or dropped, so every input row stays available for review.
  * Every row gets raw_row_id = '<source_file>:<line number>'. This is the primary key.
  * Loading is idempotent PER FILE: rows previously loaded from the same file
    name are deleted and re-inserted in one transaction. Re-running the loader on
    the same files therefore never adds rows.
  * --reset drops the table first (clean slate).
"""
import argparse
import csv
from pathlib import Path

import duckdb

DDL = """
create table if not exists raw_movements (
    raw_row_id        varchar primary key,
    source_file       varchar not null,
    source_row_number integer not null,
    movement_id       varchar,
    product_id        varchar,
    warehouse_id      varchar,
    movement_type     varchar,
    quantity          varchar,
    event_timestamp   varchar,
    loaded_at         timestamp default current_timestamp
)
"""
COLS = ["movement_id", "product_id", "warehouse_id", "movement_type", "quantity", "event_timestamp"]


def load_file(con, path: Path) -> int:
    rows = []
    with open(path, newline="") as f:
        for n, rec in enumerate(csv.DictReader(f), start=1):
            rows.append(
                (f"{path.name}:{n}", path.name, n, *[(rec.get(c) if rec.get(c) != "" else None) for c in COLS])
            )
    con.execute("begin")
    con.execute("delete from raw_movements where source_file = ?", [path.name])
    if rows:  # a header-only file is a valid delivery with zero rows (and replaces any earlier load of that file)
        con.executemany(
            "insert into raw_movements (raw_row_id, source_file, source_row_number, "
            + ", ".join(COLS)
            + ") values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    con.execute("commit")
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="path to the DuckDB database file")
    p.add_argument("files", nargs="+", help="CSV files to load (loaded in the order given)")
    p.add_argument("--reset", action="store_true", help="drop raw_movements before loading")
    a = p.parse_args()

    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(a.db)
    if a.reset:
        con.execute("drop table if exists raw_movements")
    con.execute(DDL)
    for f in a.files:
        n = load_file(con, Path(f))
        print(f"loaded {n} rows from {f}")
    total = con.execute("select count(*) from raw_movements").fetchone()[0]
    print(f"raw_movements now holds {total} rows")
    con.close()


if __name__ == "__main__":
    main()
