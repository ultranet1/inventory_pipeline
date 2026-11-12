# Phase 5: Demonstrating correctness

Reproduce everything below with `scripts/demo_phase5.sh` (full captured output: `docs/phase5_demo_output.txt`).
The script exits non-zero if any claim below is false.

## 1. Fixture run (batch_001)

| raw rows | accepted | rejected | duplicates | accepted+rejected+duplicates | daily_inventory rows |
|---|---|---|---|---|---|
| 12 | 6 | 5 | 1 | 12 | 6 |

Rejected: M005 `missing_product_id`, M008 `non_positive_quantity`, M009 `invalid_movement_type`,
M010 `invalid_timestamp`, M011 `zero_adjustment`. Duplicate: the second M002 row.

| product/warehouse | date | opening | received | shipped | adjustment | closing | negative |
|---|---|---|---|---|---|---|---|
| P101/W01 | 2026-03-01 | 0 | 20 | 5 | 0 | **15** | false |
| P101/W01 | 2026-03-02 | 15 | 0 | 0 | -2 | **13** | false |
| P101/W01 | 2026-03-03 | 13 | 0 | 30 | 0 | **-17** | **true** |
| P102/W02 | 2026-03-01 | 0 | 10 | 0 | 0 | 10 | false |
| P102/W02 | 2026-03-02 | 10 | 0 | 0 | 0 | 10 | false |
| P102/W02 | 2026-03-03 | 10 | 0 | 4 | 0 | 6 | false |

P102/W02 on 03-02 is the no-activity day: a spine row with zero movements that carries the balance forward.
`dbt build --vars '{fixture_state: after_batch1}'`: 62/62 pass (48 data tests incl. exact comparison to `fixture/expected/`).

## 2. Rerun with identical inputs

The loader and `dbt build --full-refresh` were run again on the same file (and the loader twice more on its own).
`raw_movements` stayed at 12 rows, and counts plus every daily balance matched run 1 exactly (script diffs the two snapshots).

## 3. Late-arriving batch (batch_002_late)

`L001` is a new movement_id (receipt 20 on 2026-03-02, earlier than the already-processed 2026-03-03).
`M004` is re-delivered and is an exact duplicate.

| P101/W01 closing | before | after | why |
|---|---|---|---|
| 2026-03-01 | 15 | 15 | before the late movement: unchanged |
| 2026-03-02 | **13** | **33** | late receipt lands on its own business date (+20) |
| 2026-03-03 | **-17** | **3** | +20 carries forward; negative flag clears |

Counts: raw 14, accepted 7, rejected 5, duplicates 2 (sum 14). P102/W02 is untouched (10, 10, 6).
The late movement changes its own date and every later date for that pair; it never changes earlier dates.

## 4. Why nothing is double counted

1. **Idempotent load.** `raw_row_id = '<file>:<line>'` is the primary key, and loading a file deletes that file's earlier rows and
   re-inserts them in one transaction. Re-loading a file replaces it; it cannot append a second copy.
2. **Full rebuild.** `daily_inventory` is a table recreated from scratch by `dbt build --full-refresh`, and balances are derived
   from `clean_movements`, never added onto a previous run's output. There is no state that can accumulate.
3. **One row per movement_id.** Valid rows are ranked per `movement_id` and only `occurrence_number = 1` reaches `clean_movements`.
   Re-sent rows, even across batches (M004 above), land in `duplicate_movements` instead. Tests enforce
   `unique(clean_movements.movement_id)` and that every raw row falls into exactly one bucket.

## 5. Scale check (generated data in `data/sample/`)

`generator --rows 20000 --seed 42`: raw 20,000 = accepted 18,800 + rejected 621 + duplicates 579. A rerun gave an identical checksum of
all balances; adding the 220-row late batch gave raw 20,220 = 19,000 + 621 + 599. All dbt steps passed each time.
