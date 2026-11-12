#!/usr/bin/env python3
"""Verify the core constraint end to end:

  1. each accepted movement affects stock exactly once,
  2. reprocessing the same inputs preserves row counts and balances,
  3. a late movement updates its business date and all later balances of its
     product/warehouse, and nothing else,
  4. a full rebuild from all raw files is what produces this.

Every scenario rebuilds with scripts/run_pipeline.sh and compares daily_inventory
with an INDEPENDENT Python oracle that re-implements the rules from the raw CSV
files (validation, first-delivery dedup, daily running balance). The pipeline
SQL is never used to compute the expected values.

    python scripts/verify_core_constraint.py          # fixture + edge cases (~40 s)
    python scripts/verify_core_constraint.py --scale  # also 20,220 generated rows (~1 min more)

Works in data/core_check/ and deletes it afterwards. Exits non-zero on any failure.
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "data" / "core_check"
DB = WORK / "check.duckdb"
FIX = ROOT / "fixture"
failures = []


def check(ok, msg):
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        failures.append(msg)


# ---------------------------------------------------------------- oracle ----
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}$")
INT_RE = re.compile(r"^[+-]?[0-9]+$")
FIELDS = ["movement_id", "product_id", "warehouse_id", "movement_type", "quantity", "event_timestamp"]


def oracle(files):
    """Expected clean movements and daily balances, from the CSV files alone (UTC -> UTC)."""
    rows = []
    for f in files:
        with open(f, newline="") as fh:
            for n, rec in enumerate(csv.DictReader(fh), start=1):
                rows.append((Path(f).name, n, {k: (rec.get(k) or "").strip() for k in FIELDS}))
    rows.sort(key=lambda r: (r[0], r[1]))          # first delivery = (file name, line)
    accepted, rejected, dups = {}, 0, 0
    for _, _, r in rows:
        ok = all(r[k] for k in FIELDS) and TS_RE.match(r["event_timestamp"])
        if ok:
            try:
                ts = datetime.strptime(r["event_timestamp"].replace("T", " "), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                ok = False
        ok = ok and r["movement_type"] in ("receipt", "shipment", "adjustment") and INT_RE.match(r["quantity"])
        if ok:
            q = int(r["quantity"])
            ok = (q > 0) if r["movement_type"] != "adjustment" else (q != 0)
        if not ok:
            rejected += 1
            continue
        if r["movement_id"] in accepted:
            dups += 1
            continue
        signed = -q if r["movement_type"] == "shipment" else q
        accepted[r["movement_id"]] = (r["product_id"], r["warehouse_id"], ts.date(), signed)
    per_pair = defaultdict(lambda: defaultdict(int))
    for p, w, d, s in accepted.values():
        per_pair[(p, w)][d] += s
    last = max(d for p, w, d, s in accepted.values())
    daily = {}
    for pair, days in per_pair.items():
        d, bal = min(days), 0
        while d <= last:
            bal += days.get(d, 0)
            daily[(pair[0], pair[1], d)] = bal
            d += timedelta(days=1)
    return {"raw": len(rows), "accepted": len(accepted), "rejected": rejected, "duplicates": dups,
            "daily": daily, "clean": accepted}


# -------------------------------------------------------------- pipeline ----
def build(files, reset=True):
    cmd = [str(ROOT / "scripts" / "run_pipeline.sh"), *(["--reset"] if reset else []), *map(str, files)]
    r = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, INVENTORY_DB=str(DB)), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-4000:], r.stderr[-2000:])
        check(False, f"pipeline build on {[Path(f).name for f in files]}")
        return False
    return True


def state():
    con = duckdb.connect(str(DB), read_only=True)
    acc = dict(zip(["raw", "accepted", "rejected", "duplicates", "daily_rows"],
                   con.execute("select raw_rows, accepted, rejected, duplicates, daily_rows "
                               "from analytics.movement_accounting").fetchone()))
    daily = {(p, w, d): c for p, w, d, c in con.execute(
        "select product_id, warehouse_id, inventory_date, closing_quantity from analytics.daily_inventory").fetchall()}
    full = con.execute("select * from analytics.daily_inventory order by all").fetchall()
    clean = {r[0]: r[1:] for r in con.execute(
        "select movement_id, product_id, warehouse_id, business_date, signed_quantity from analytics.clean_movements").fetchall()}
    con.close()
    return acc, daily, full, clean


def compare_to_oracle(label, files):
    exp = oracle(files)
    acc, daily, _, clean = state()
    check(all(acc[k] == exp[k] for k in ("raw", "accepted", "rejected", "duplicates")),
          f"{label}: counts {acc['raw']} = {acc['accepted']} + {acc['rejected']} + {acc['duplicates']} match oracle")
    check(acc["raw"] == acc["accepted"] + acc["rejected"] + acc["duplicates"], f"{label}: every raw row in one bucket")
    check(clean == {k: tuple(v) for k, v in exp["clean"].items()},
          f"{label}: clean_movements = oracle ({len(clean)} movements, each exactly once)")
    check(daily == exp["daily"], f"{label}: all {len(daily)} daily closings = oracle")
    return exp


def late_effect(label, before, after, clean_before, clean_after):
    """after - before must equal, for every pair and date, the sum of NEW movements up to that date."""
    new = {m: v for m, v in clean_after.items() if m not in clean_before}
    bad, changed, untouched = 0, 0, 0
    for (p, w, d), c in after.items():
        delta = sum(s for (pp, ww, dd, s) in new.values() if pp == p and ww == w and dd <= d)
        if c - before.get((p, w, d), 0) != delta:
            bad += 1
        changed += delta != 0
        untouched += delta == 0
    lost = [k for k in before if k not in after]
    check(bad == 0 and not lost,
          f"{label}: {len(new)} new movement(s) change exactly their date and later dates of their pair "
          f"({changed} rows changed, {untouched} unchanged, {bad} wrong)")


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        w.writerows(rows)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", action="store_true")
    a = ap.parse_args()
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    B1, B2 = FIX / "batch_001.csv", FIX / "batch_002_late.csv"

    print("\n[1] Exactly once: fixture batch 1 vs independent oracle")
    build([B1])
    compare_to_oracle("batch_001", [B1])
    acc, daily, full_a, clean_a = state()
    check(daily[("P101", "W01", date(2026, 3, 1))] == 15, "M002 sent twice is subtracted once (P101/W01 03-01 closing 15, not 10)")

    print("\n[2] Reprocessing identical inputs")
    for i in (1, 2):
        build([B1], reset=False)
        acc2, _, full_b, _ = state()
        check(acc2 == acc and full_b == full_a, f"rerun {i}: raw rows still {acc2['raw']}, every daily row identical")
    r = subprocess.run([sys.executable, "loader/load_raw.py", "--db", str(DB), str(B1), str(B1)],
                       cwd=ROOT, capture_output=True, text=True)
    check("raw_movements now holds 12 rows" in r.stdout, "loading the same file twice in one call: still 12 raw rows")
    resend = write(WORK / "batch_003_resend.csv", list(csv.reader(open(B1)))[1:])
    build([B1, resend])
    _, _, full_c, _ = state()
    compare_to_oracle("batch_001 + identical copy under a NEW file name", [B1, resend])
    check(full_c == full_a, "same rows under a new file name: balances unchanged (caught as duplicates)")

    empty = write(WORK / "batch_005_empty.csv", [])
    build([B1, empty])
    _, _, full_e, _ = state()
    compare_to_oracle("batch_001 + header-only file", [B1, empty])
    check(full_e == full_a, "a header-only file loads as zero rows and changes nothing")

    print("\n[3] Late-arriving movement (fixture late batch)")
    build([B1])
    _, before, _, cb = state()
    build([B1, B2])
    compare_to_oracle("batch_001 + batch_002_late", [B1, B2])
    _, after, _, ca = state()
    late_effect("batch_002_late", before, after, cb, ca)
    check([after[("P101", "W01", date(2026, 3, d))] for d in (1, 2, 3)] == [15, 33, 3]
          and [before[("P101", "W01", date(2026, 3, d))] for d in (1, 2, 3)] == [15, 13, -17],
          "P101/W01 closing 15, 13, -17 -> 15, 33, 3 (03-01 unchanged, 03-02 and 03-03 +20)")

    print("\n[4] Late-arrival edge cases")
    edge = write(WORK / "batch_004_late_edge.csv", [
        ["E001", "P102", "W02", "receipt", "5", "2026-02-27 10:00:00"],    # before the pair's AND dataset's first date
        ["E002", "P103", "W01", "receipt", "7", "2026-03-02 09:00:00"],    # brand-new pair, mid-range
        ["E003", "P101", "W01", "shipment", "4", "2026-03-03 23:59:59"],   # last second of the last date
        ["E004", "P101", "W01", "adjustment", "3", "2026-03-01 00:00:00"],  # first second of the first date
        ["M001", "P101", "W01", "receipt", "20", "2026-03-01 09:00:00"],   # re-delivery of M001
        ["M005", "P101", "W01", "receipt", "8", "2026-03-03 12:00:00"],    # M005 rejected in batch 1, now valid
    ])
    build([B1, B2])
    _, before, _, cb = state()
    build([B1, B2, edge])
    compare_to_oracle("+ edge-case batch", [B1, B2, edge])
    _, after, _, ca = state()
    late_effect("edge-case batch", before, after, cb, ca)
    check([after.get(("P102", "W02", date(2026, 2, d))) for d in (27, 28)] == [5, 5]
          and after[("P102", "W02", date(2026, 3, 3))] == 11,
          "movement before the earliest date: spine extends back to 02-27; P102/W02 now 5, 5, 15, 15, 11")
    check(after.get(("P103", "W01", date(2026, 3, 1))) is None and after[("P103", "W01", date(2026, 3, 3))] == 7,
          "new pair starts on its own first date (03-02) and carries to the last date")

    print("\n[5] Load order does not matter (late file loaded first)")
    build([B2])
    build([B1], reset=False)
    _, _, full_rev, _ = state()
    build([B1, B2])
    _, _, full_fwd, _ = state()
    check(full_rev == full_fwd, "loading batch_002 before batch_001 gives identical balances (first delivery = file order)")

    if a.scale:
        print("\n[6] Generated data: 20,000-row batch + 220-row late batch")
        out = WORK / "sample"
        subprocess.run([sys.executable, "generator/generate_movements.py", "--rows", "20000", "--seed", "42",
                        "--out-dir", str(out)], cwd=ROOT, check=True, capture_output=True)
        g1, g2 = out / "batch_001.csv", out / "batch_002_late.csv"
        build([g1])
        compare_to_oracle("generated batch_001", [g1])
        _, before, full_1, cb = state()
        build([g1], reset=False)
        _, _, full_2, _ = state()
        check(full_1 == full_2, f"generated rerun: all {len(full_1)} daily rows identical")
        build([g1, g2])
        compare_to_oracle("generated batch_001 + late", [g1, g2])
        _, after, _, ca = state()
        late_effect("generated late batch", before, after, cb, ca)

    shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
