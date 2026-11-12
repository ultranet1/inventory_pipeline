#!/usr/bin/env bash
# Load -> dbt build (seeds, models, tests) in order, as a full rebuild.
#
# Usage:  scripts/run_pipeline.sh [--reset] [--state none|after_batch1|after_late] FILE.csv [FILE.csv ...]
#   --reset   drop raw_movements first (clean slate); otherwise loading is idempotent per file
#   --state   which fixture expectations the exact-result tests assert (default: none)
# Env:      INVENTORY_DB (default: data/inventory.duckdb)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export INVENTORY_DB="${INVENTORY_DB:-$ROOT/data/inventory.duckdb}"
export DBT_PROFILES_DIR="$ROOT/dbt_project"

RESET=""; STATE="none"; FILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset) RESET="--reset"; shift ;;
    --state) STATE="$2"; shift 2 ;;
    *) FILES+=("$1"); shift ;;
  esac
done
[[ ${#FILES[@]} -gt 0 ]] || { echo "usage: $0 [--reset] [--state S] FILE.csv ..." >&2; exit 2; }

echo "==> 1/2 load raw_movements"
python loader/load_raw.py --db "$INVENTORY_DB" $RESET "${FILES[@]}"

echo "==> 2/2 dbt build --full-refresh (seeds + models + tests), fixture_state=$STATE"
cd dbt_project
dbt build --full-refresh --vars "{fixture_state: $STATE}"
