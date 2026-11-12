#!/usr/bin/env python3
"""Phase 4 proof: the dbt tests can actually FAIL.

Builds the batch-1 fixture once (all tests must pass), then for each mutation
copies that database, deliberately corrupts the built tables with one SQL
statement, re-runs `dbt test`, and asserts the intended test(s) fail.

    python scripts/test_the_tests.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt_project"
WORK = ROOT / "data" / "mutation"
PRISTINE, SCRATCH = WORK / "pristine.duckdb", WORK / "scratch.duckdb"
VARS = '{"fixture_state": "after_batch1"}'
DBT = Path(sys.executable).parent / "dbt"
DBT = str(DBT) if DBT.exists() else shutil.which("dbt")

P101 = "product_id = 'P101' and warehouse_id = 'W01'"
# name -> (corrupting SQL, tests that MUST fail)
MUTATIONS = {
    "closing off by one (3/2)": (
        f"update analytics.daily_inventory set closing_quantity = closing_quantity + 1 "
        f"where {P101} and inventory_date = '2026-03-02'",
        ["assert_balance_formula", "assert_closing_matches_clean_movements",
         "assert_opening_equals_previous_closing", "assert_fixture_daily_inventory"]),
    "opening reset to 0 (3/3)": (
        f"update analytics.daily_inventory set opening_quantity = 0 "
        f"where {P101} and inventory_date = '2026-03-03'",
        ["assert_opening_equals_previous_closing", "assert_balance_formula"]),
    "no-activity/middle day missing": (
        f"delete from analytics.daily_inventory where {P101} and inventory_date = '2026-03-02'",
        ["assert_no_date_gaps", "assert_fixture_daily_inventory"]),
    "spine stops early": (
        "delete from analytics.daily_inventory where product_id = 'P102' and inventory_date = '2026-03-03'",
        ["assert_spine_bounds", "assert_fixture_daily_inventory"]),
    "negative flag not set": (
        "update analytics.daily_inventory set negative_balance = false where closing_quantity < 0",
        ["assert_negative_flag_matches_closing", "assert_fixture_daily_inventory"]),
    "duplicate daily grain row": (
        f"insert into analytics.daily_inventory select * from analytics.daily_inventory where {P101} "
        f"and inventory_date = '2026-03-01'",
        ["unique_combination_daily_inventory_product_id__warehouse_id__inventory_date"]),
    "shipments stored as negative": (
        f"update analytics.daily_inventory set shipped_quantity = -shipped_quantity "
        f"where {P101} and inventory_date = '2026-03-03'",
        ["assert_activity_not_negative"]),
    "duplicate movement_id in clean": (
        "insert into analytics.clean_movements select * from analytics.clean_movements where movement_id = 'M001'",
        ["unique_clean_movements_movement_id"]),
    "bad movement_type in clean": (
        "update analytics.clean_movements set movement_type = 'sale' where movement_id = 'M001'",
        ["accepted_values_clean_movements_movement_type__receipt__shipment__adjustment"]),
    "raw row lost (not in any bucket)": (
        "insert into main.raw_movements (raw_row_id, source_file, source_row_number, movement_id) "
        "values ('ghost.csv:1', 'ghost.csv', 1, 'GHOST')",
        ["assert_row_accounting", "assert_fixture_counts"]),
    "wrong rejection reason": (
        "update analytics.rejected_movements set rejection_reason = 'invalid_timestamp' where movement_id = 'M011'",
        ["assert_fixture_rejections"]),
    "duplicate row not removed": (
        "delete from analytics.duplicate_movements where movement_id = 'M002'",
        ["assert_fixture_duplicates", "assert_row_accounting", "assert_fixture_counts"]),
    "non-exact duplicate": (
        "update analytics.duplicate_movements set is_exact_duplicate = false",
        ["assert_duplicates_are_exact"]),
}


def dbt(db, *args):
    import os
    env = dict(os.environ, INVENTORY_DB=str(db), DBT_PROFILES_DIR=str(DBT_DIR))
    return subprocess.run([DBT, *args], cwd=DBT_DIR, env=env, capture_output=True, text=True)


def failing_tests():
    res = json.load(open(DBT_DIR / "target" / "run_results.json"))["results"]
    return {r["unique_id"].split(".")[2] for r in res if r["status"] in ("fail", "error")}, len(res)


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    subprocess.run([sys.executable, ROOT / "loader" / "load_raw.py", "--db", PRISTINE, "--reset",
                    ROOT / "fixture" / "batch_001.csv"], check=True, capture_output=True)
    for step in (["seed", "--full-refresh"], ["run", "--full-refresh"]):
        r = dbt(PRISTINE, *step, "--vars", VARS)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)

    dbt(PRISTINE, "test", "--vars", VARS)
    bad, n = failing_tests()
    print(f"baseline (uncorrupted): {n} tests, {len(bad)} failing")
    if bad:
        sys.exit(f"baseline must be green, failing: {sorted(bad)}")

    missed = 0
    print(f"\n{'mutation':<36} {'expected tests caught':<24} also failed")
    for name, (sql, expected) in MUTATIONS.items():
        shutil.copy(PRISTINE, SCRATCH)
        con = duckdb.connect(str(SCRATCH))
        con.execute(sql)
        con.close()
        dbt(SCRATCH, "test", "--vars", VARS)
        bad, _ = failing_tests()
        caught = [t for t in expected if t in bad]
        ok = len(caught) == len(expected)
        missed += not ok
        extra = sorted(bad - set(expected))
        print(f"{'OK  ' if ok else 'MISS'} {name:<31} {len(caught)}/{len(expected):<22} {', '.join(extra) or '-'}")
        if not ok:
            print(f"     not caught: {sorted(set(expected) - bad)}")
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n{len(MUTATIONS) - missed}/{len(MUTATIONS)} mutations caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
