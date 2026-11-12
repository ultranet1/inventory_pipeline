#!/usr/bin/env python3
"""Phase 6: run the reporting queries on the fixture and verify them.

For each fixture state (after_batch1, then after_late) this script
  1. rebuilds the pipeline with scripts/run_pipeline.sh (load + dbt build, tests included),
  2. runs queries/q1_*.sql and queries/q2_*.sql exactly as committed,
  3. compares the results to fixture/expected/<query>_<state>.csv (exact match),
  4. cross-checks them against independent recomputations from clean_movements,
  5. saves the results to queries/results/<query>_<state>.csv.
It also checks that the date-range filter of query 2 really filters.

    python scripts/verify_queries.py            # fixture only (seconds)
    python scripts/verify_queries.py --scale    # also invariant checks on 20k generated rows

Uses its own database (data/queries.duckdb). Exits non-zero on any mismatch.
"""
import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
QDIR, RESULTS, EXPECTED = ROOT / "queries", ROOT / "queries" / "results", ROOT / "fixture" / "expected"
DB = ROOT / "data" / "queries.duckdb"
QUERIES = {
    "daily_stock_by_warehouse": QDIR / "q1_daily_stock_by_warehouse.sql",
    "negative_closing": QDIR / "q2_negative_closing_stock.sql",
}
failures = []


def check(ok, msg):
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def build(state, files, reset=True):
    cmd = [str(ROOT / "scripts" / "run_pipeline.sh"), *(["--reset"] if reset else []), "--state", state, *files]
    r = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, INVENTORY_DB=str(DB)), capture_output=True, text=True)
    summary = [l for l in r.stdout.splitlines() if "Done. PASS" in l]
    print(f"  build: {summary[-1].split('Done. ')[-1] if summary else 'no dbt summary'}")
    if r.returncode:
        sys.exit(r.stdout[-3000:] + r.stderr[-3000:] + "\npipeline failed")


def run_query(con, path, start=None, end=None):
    con.execute("reset variable start_date") if start is None else con.execute(f"set variable start_date = date '{start}'")
    con.execute("reset variable end_date") if end is None else con.execute(f"set variable end_date = date '{end}'")
    cur = con.execute(path.read_text())
    cols = [d[0] for d in cur.description]
    return cols, [tuple(str(v).lower() if isinstance(v, bool) else str(v) for v in row) for row in cur.fetchall()]


def read_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], [tuple(r) for r in rows[1:]]


def write_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        w.writerows(rows)


def invariants(con):
    """Recompute both reports from clean_movements, independently of daily_inventory."""
    # Q1: warehouse closing on day d = sum of signed movements of that warehouse up to d.
    _, q1 = run_query(con, QUERIES["daily_stock_by_warehouse"])
    bad = con.execute("""
        with q1 as (select * from (values {}) t(warehouse_id, inventory_date, closing))
        select count(*) from q1
        where cast(closing as bigint) <> (
            select coalesce(sum(signed_quantity), 0) from analytics.clean_movements m
            where m.warehouse_id = q1.warehouse_id and m.business_date <= cast(q1.inventory_date as date))
    """.format(",".join(f"('{r[0]}','{r[1]}','{r[6]}')" for r in q1) or "(null,null,null)")).fetchone()[0]
    check(bad == 0, f"Q1 closing = cumulative signed movements per warehouse ({len(q1)} rows, {bad} mismatches)")
    # Q1 rows must also satisfy the balance identity at warehouse level.
    ident = sum(int(r[2]) + int(r[3]) - int(r[4]) + int(r[5]) != int(r[6]) for r in q1)
    check(ident == 0, f"Q1 closing = opening + received - shipped + adjustment on every row ({ident} violations)")
    # Q2: exactly the days whose recomputed running balance is negative.
    _, q2 = run_query(con, QUERIES["negative_closing"])
    truth = con.execute("""
        with d as (select product_id, warehouse_id, inventory_date,
                     (select sum(signed_quantity) from analytics.clean_movements m
                      where m.product_id = s.product_id and m.warehouse_id = s.warehouse_id
                        and m.business_date <= s.inventory_date) as bal
                   from analytics.daily_inventory s)
        select product_id, warehouse_id, cast(inventory_date as varchar), cast(bal as varchar)
        from d where bal < 0 order by 1, 2, 3""").fetchall()
    check(q2 == [tuple(r) for r in truth], f"Q2 = days with recomputed balance < 0 ({len(q2)} rows)")


def verify_state(state, files):
    print(f"\n=== fixture state: {state}  ({' + '.join(Path(f).name for f in files)})")
    build(state, files)
    con = duckdb.connect(str(DB), read_only=True)
    for name, path in QUERIES.items():
        cols, rows = run_query(con, path)
        exp_cols, exp_rows = read_csv(EXPECTED / f"{name}_{state}.csv")
        check(cols == exp_cols and rows == exp_rows,
              f"{path.name} matches fixture/expected/{name}_{state}.csv ({len(rows)} rows)")
        if cols != exp_cols or rows != exp_rows:
            print("        got:", cols, rows, "\n        expected:", exp_cols, exp_rows)
        out = RESULTS / f"{name}_{state}.csv"
        write_csv(out, cols, rows)
        print(f"        saved {out.relative_to(ROOT)}")
        for r in [cols, *rows]:
            print("        " + " | ".join(f"{v:>10}" for v in r))
    invariants(con)
    return con


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", action="store_true", help="also run invariant checks on generated data")
    a = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    B1, B2 = "fixture/batch_001.csv", "fixture/batch_002_late.csv"

    con = verify_state("after_batch1", [B1])
    print("  date-range filter of Q2 (after_batch1):")
    for (s, e), n in {("2026-03-01", "2026-03-02"): 0, ("2026-03-03", "2026-03-03"): 1, (None, None): 1}.items():
        _, rows = run_query(con, QUERIES["negative_closing"], s, e)
        check(len(rows) == n, f"Q2 range [{s or 'min'} .. {e or 'max'}] -> {len(rows)} row(s), expected {n}")
    _, rows = run_query(con, QUERIES["daily_stock_by_warehouse"], "2026-03-02", "2026-03-02")
    check(rows == [("W01", "2026-03-02", "15", "0", "0", "-2", "13", "1"),
                   ("W02", "2026-03-02", "10", "0", "0", "0", "10", "1")],
          "Q1 range [2026-03-02 .. 2026-03-02] -> one row per warehouse incl. W02's no-activity day")
    con.close()

    verify_state("after_late", [B1, B2]).close()

    if a.scale:
        print("\n=== generated data (20,000 rows + late batch, seed 42): invariant checks only")
        subprocess.run([sys.executable, "generator/generate_movements.py", "--rows", "20000", "--seed", "42",
                        "--out-dir", "data/sample"], cwd=ROOT, check=True, capture_output=True)
        build("none", ["data/sample/batch_001.csv", "data/sample/batch_002_late.csv"])
        con = duckdb.connect(str(DB), read_only=True)
        invariants(con)
        _, q2 = run_query(con, QUERIES["negative_closing"])
        pairs = {(r[0], r[1]) for r in q2}
        print(f"  Q2 on generated data: {len(q2)} negative days across {len(pairs)} product/warehouse pairs")
        con.close()

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
