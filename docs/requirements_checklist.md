# Requirements checklist

How each requirement of the assessment brief is met. Section numbers refer to `README.md`.

## Hard requirements

**1. Reproducible inputs**

| Condition | How it is met |
|---|---|
| Configurable generator | `generator/generate_movements.py` options: `--rows`, `--seed`, `--products`, `--days`, `--start-date`, `--duplicate-rate`, `--invalid-rate`, `--late-rate`, `--out-dir`. |
| Fixed seed / deterministic | One `random.Random(seed)` drives everything, so the same options give byte-identical files (same MD5 on repeated runs; a different seed gives different files). |
| Two warehouses, multiple products | `W01` and `W02`; 50 products by default (`--products`). |
| Exact duplicates | Identical copies of existing rows (3% by default: 600 extra copies in the 20,000-row batch). |
| Invalid rows | One defect per row, of 8 kinds: null product_id, null warehouse_id, null quantity, bad timestamp, bad movement_type, non-positive receipt/shipment, zero adjustment, fractional quantity (3% by default). |
| Separate late-arriving batch | `batch_002_late.csv`: new movement_ids all dated before the latest date of batch 1, plus some exact re-deliveries of batch-1 rows. |
| Small fixture with known expected balances | `fixture/batch_001.csv` (12 rows) and `fixture/batch_002_late.csv` (2 rows), with expected results in `fixture/expected/` (P101/W01 closing 15, 13, -17, then 15, 33, 3 after the late batch). See Section 4. |
| Simple loading command | `python loader/load_raw.py --db data/inventory.duckdb FILE.csv ...`, or `scripts/run_pipeline.sh` to load and build in one step. |

**2. The dbt pipeline**

| Condition | How it is met |
|---|---|
| dbt Core models produce clean movements, rejected rows and daily inventory | `clean_movements`, `rejected_movements` and `daily_inventory` are dbt models materialized as tables in DuckDB (plus `duplicate_movements`, so removed duplicates are visible too). |
| Dependencies through dbt references | Every model reads its input with `ref()` or `source()`; no model SQL names a table directly. Lineage: `source(raw_movements)` → `stg_movements_validated` → `rejected_movements` and `stg_valid_movements_ranked` → `clean_movements` → `int_date_spine` and `int_daily_movement_totals` → `daily_inventory`. `dbt docs generate` draws this graph (Section 2.8). |
| Full refresh | `scripts/run_pipeline.sh` runs `dbt build --full-refresh`; no model is incremental. |
| Tests for required fields | `not_null` on every required column of `clean_movements` and `daily_inventory`, and on the key columns of the other models (26 tests). |
| Tests for uniqueness | `unique` on `clean_movements.movement_id` and on `raw_row_id` in four models; the custom generic test `unique_combination` on the daily grain (product + warehouse + date). |
| Tests for accepted values | `accepted_values` on `clean_movements.movement_type` (receipt, shipment, adjustment) and on `rejection_reason`. |
| Tests for balance logic | 13 singular tests, including: closing = opening + received - shipped + adjustment, opening = previous closing, negative flag = closing < 0, no date gaps, spine bounds, closing recomputed from `clean_movements`, row accounting, and exact comparison with the fixture's expected balances. All 48 tests are listed in Section 9. |

**3. Correctness and rerun safety**

Expected and actual results for every check, side by side: `fixture/actual/COMPARISON.md` (`python scripts/fixture_results.py`).

Run `scripts/demo_phase5.sh` (output: `docs/phase5_demo_output.txt`); it exits non-zero if any value below is wrong.
The exact-result dbt tests compare against `fixture/expected/`.

| Check | Exact expected result | Verified by |
|---|---|---|
| Validation | M005 `missing_product_id`, M008 `non_positive_quantity`, M009 `invalid_movement_type`, M010 `invalid_timestamp`, M011 `zero_adjustment` | `assert_fixture_rejections` against `fixture/expected/rejections.csv` |
| Duplicate handling | batch 1: 12 raw = 6 accepted + 5 rejected + **1 duplicate** (the second M002 row); after the late batch: **2** (M004 re-sent) | `assert_fixture_duplicates` against `duplicates.csv` (which rows, and which row was kept), `assert_fixture_counts`, `assert_row_accounting`, `assert_duplicates_are_exact` |
| Daily balances | P101/W01 closing **15, 13, -17** (negative on 03-03); P102/W02 **10, 10, 6** (03-02 is a no-activity day) | `assert_fixture_daily_inventory` against `daily_inventory_after_batch1.csv`, plus the balance-rule tests |
| Rerun with identical inputs | still **12** raw rows, the same counts and every daily row identical | demo step B diffs the two snapshots; the exact-result tests pass again |
| Late-arriving batch | P101/W01 **15, 13, -17 → 15, 33, 3**: 03-01 unchanged, the late date (03-02) and later dates +20; P102/W02 unchanged | demo step C asserts these values; `assert_fixture_daily_inventory` against `daily_inventory_after_late.csv` |

How loading and materializations prevent double counting: Section 7 (idempotent per-file load, full-refresh table
rebuild, one row per movement_id). `scripts/verify_core_constraint.py` repeats these checks against an independent
Python calculation, including edge cases and the generated data.

**4. Model logic**

| Condition | Where |
|---|---|
| Dependency path from raw to daily inventory | Diagram at the top of this README; Section 6 |
| Two reporting queries, verified against the fixture | Section 8: `queries/q1_daily_stock_by_warehouse.sql`, `queries/q2_negative_closing_stock.sql`, checked by `scripts/verify_queries.py`, results in `queries/results/` |
| Model boundaries and materializations | Section 6 |
| Test coverage and gaps | Section 9 |
| Limitation as data grows, and an improvement | Section 10 (full rebuild of the date spine and window function → incremental rebuild of only the affected product/warehouse pairs) |

**6.1 Compute and storage**

| Condition | How it is met |
|---|---|
| Database with a compatible dbt Core adapter | DuckDB 2.0.0 with dbt-duckdb 1.11.1 on dbt Core 1.12.6 (README Section 1.1). |
| Simplest option you can reproduce | DuckDB runs inside Python and stores everything in one local file: `pip install -r requirements.txt` is the whole setup. |
| Keep generated inputs available | The generated files are committed in `data/sample/` with checksums, and the fixed-seed generator recreates them byte for byte (Section 3). |
| Synthetic data only | Every product, warehouse and movement id, quantity and timestamp is made up by the generator or written by hand for the fixture. |
| Example configuration without credentials | `dbt_project/profiles.yml` contains only a local file path (Section 1.4). |
| Explain database-specific behavior | Section 6, "DuckDB-specific behavior that affects the SQL or results". |

**6.2 Execution**

| Condition | How it is met |
|---|---|
| Commands or a small script to load, run models and test, in order | `scripts/run_pipeline.sh` runs the loader first, then `dbt build --full-refresh`, which loads seeds, builds models and runs tests. The same steps run by hand are in Section 2.3. |
| dbt manages model dependencies | Every model uses `ref()`/`source()`; `dbt build` follows that graph, runs each model's tests right after the model and skips downstream models if a test fails. Nothing in the scripts lists models or their order. |
| No CI/CD, orchestrator or scheduling | None is used; everything runs from the command line. |

**6.3 GitHub and Loom**

| Condition | How it is met |
|---|---|
| GitHub and Loom links, accessible or with access instructions | Links and access instructions at the top of this README. |
| dbt project | `dbt_project/` |
| Input generator and loading instructions | `generator/generate_movements.py`, `loader/load_raw.py`; commands in Sections 2.1–2.3 and 2.7 |
| Example configuration | `dbt_project/profiles.yml` (Section 1.4) |
| Small fixture | `fixture/` with expected results in `fixture/expected/` (Section 4) |
| No credentials | The profile is a local file path only; nothing else needs a secret. |
| No large generated datasets | Database files are git-ignored and rebuilt by every run. The only generated data committed is `data/sample/` (about 1 MB, 20,220 rows), kept so the documented numbers can be reproduced; the whole repository is about 1.3 MB. |

## Deliverables

| Deliverable | Where |
|---|---|
| dbt Core project with models and tests | `dbt_project/` |
| Input generator, loading script, both reporting queries | `generator/`, `loader/` + `scripts/run_pipeline.sh`, `queries/` |
| Concise README: setup, versions, example config, commands, assumptions, data volume | README Sections 1–5 |
| Fixture with expected and actual results (rejected rows, duplicates, missing activity dates, daily balances, reruns, late data) | `fixture/expected/`, `fixture/actual/`, `fixture/actual/COMPARISON.md` |
| Model dependencies, materializations, test coverage, limitation as data grows | README Sections 6, 9 and 10 |
| Loom walkthrough linked in the README; known limitations and unfinished work | Top of README; README Section 11 |
