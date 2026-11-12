#!/usr/bin/env bash
# Phase 5 demonstration: fixture run -> identical rerun -> late-arriving batch.
# Uses its own database file so it never touches data/inventory.duckdb.
# Exits non-zero if any claim (idempotent rerun, expected before/after values) is false.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export INVENTORY_DB="$ROOT/data/demo.duckdb"
rm -f "$INVENTORY_DB" "$INVENTORY_DB.wal"
TMP="$(mktemp -d)"
B1=fixture/batch_001.csv; B2=fixture/batch_002_late.csv

run() {  # run pipeline quietly, show only the dbt summary line
  local log="$TMP/run.log"
  if ! scripts/run_pipeline.sh "$@" >"$log" 2>&1; then cat "$log"; echo "PIPELINE FAILED"; exit 1; fi
  grep -E "^(loaded|raw_movements now)" "$log" | sed 's/^/   /'
  grep -E "Done\. PASS" "$log" | sed 's/\x1b\[[0-9;]*m//g; s/^[0-9:]* *//; s/^/   dbt: /'
}

echo "################ A. FIXTURE RUN (batch_001 only) ################"
run --reset --state after_batch1 $B1
python scripts/snapshot.py | tee "$TMP/A.txt"

echo; echo "################ B. RERUN, IDENTICAL INPUT (loader + dbt again) ################"
run --state after_batch1 $B1
python scripts/snapshot.py | tee "$TMP/B.txt"
if diff -q "$TMP/A.txt" "$TMP/B.txt" >/dev/null; then
  echo ">> PASS: counts and every daily balance identical to run A (no double counting)"
else
  echo ">> FAIL: rerun changed results"; diff "$TMP/A.txt" "$TMP/B.txt"; exit 1
fi
echo "   (also rerunning the loader alone twice more:)"
python loader/load_raw.py --db "$INVENTORY_DB" $B1 | tail -1 | sed 's/^/   /'
python loader/load_raw.py --db "$INVENTORY_DB" $B1 | tail -1 | sed 's/^/   /'

echo; echo "################ C. LATE-ARRIVING BATCH (batch_002_late) ################"
echo "-- BEFORE, P101/W01 (from run A):"; python scripts/snapshot.py --pair P101/W01 | tail -n +2
run --state after_late $B1 $B2
echo "-- AFTER, P101/W01:"; python scripts/snapshot.py --pair P101/W01 | tail -n +2
python scripts/snapshot.py --counts-only

python - <<'PY'
import duckdb, os
con = duckdb.connect(os.environ["INVENTORY_DB"], read_only=True)
g = lambda d: con.execute("select closing_quantity from analytics.daily_inventory where product_id='P101' and warehouse_id='W01' and inventory_date=?", [d]).fetchone()[0]
got = {d: g(d) for d in ("2026-03-01", "2026-03-02", "2026-03-03")}
exp = {"2026-03-01": 15, "2026-03-02": 33, "2026-03-03": 3}   # before: 15, 13, -17
print(">> closing after late batch:", got)
assert got == exp, f"expected {exp}"
neg = con.execute("select count(*) from analytics.daily_inventory where negative_balance").fetchone()[0]
print(f">> negative-balance rows: before=1 (P101/W01 on 03-03, -17), after={neg}")
assert neg == 0
p102 = con.execute("select closing_quantity from analytics.daily_inventory where product_id='P102' order by inventory_date").fetchall()
assert [r[0] for r in p102] == [10, 10, 6], "unrelated pair must not change"
print(">> PASS: 03-01 unchanged; 03-02 (late movement's date) 13 -> 33; 03-03 (subsequent) -17 -> 3; P102/W02 untouched")
PY
rm -rf "$TMP"
