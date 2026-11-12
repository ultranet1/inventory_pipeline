# Loom recording script (target: about 12 minutes; the brief allows 5 to 15)

Covers the 7 required points in order. Each section lists **what is on screen**, **commands**, and **talking points**.
Talking points are prompts to say in your own words, not lines to read. No slides are needed: everything is shown
in the editor, the terminal and the dbt lineage graph.

| The brief asks the video to... | Where |
|---|---|
| Show dbt model dependencies | Point 3: the lineage graph from `dbt docs` |
| Show main transformations | Points 2 and 3: validation, dedup, date spine and balance SQL |
| Show correctness checks | Points 4, 5 and 6: rerun, late batch, dbt tests, `fixture/actual/COMPARISON.md` |
| Show reporting query results | Point 6: `queries/results/` (saved) and the verify script |
| Use saved results where helpful | `fixture/actual/COMPARISON.md`, `queries/results/`, `docs/evidence/` |
| Connect decisions to observed results | The **Connect** lines in each point |
| Recognize the limits of the solution | The **Tradeoff** lines, the test gaps in point 6, and point 7 |
| Keep production extensions brief | Point 7 is under a minute |

## Before recording (not on camera)

```bash
cd inventory_pipeline && source .venv/bin/activate
rm -f data/*.duckdb data/*.duckdb.wal

# lineage graph for point 3: build once, then serve it in a SECOND terminal and leave it running
scripts/run_pipeline.sh --reset --state after_batch1 fixture/batch_001.csv > /dev/null
(cd dbt_project && dbt docs generate > /dev/null)
cd dbt_project && dbt docs serve --port 8080      # in the second terminal; open http://localhost:8080 in a browser tab
```

Back in the first terminal: `rm -f data/inventory.duckdb data/inventory.duckdb.wal && clear` so the recording starts
from an empty database.

Open in the editor, as tabs in this order: `fixture/batch_001.csv`, `fixture/expected/daily_inventory_after_batch1.csv`,
`dbt_project/models/staging/stg_movements_validated.sql`, `stg_valid_movements_ranked.sql`, `duplicate_movements.sql`,
`int_date_spine.sql`, `daily_inventory.sql`, `fixture/batch_002_late.csv`, `fixture/actual/COMPARISON.md`,
`queries/q1_daily_stock_by_warehouse.sql`, `queries/q2_negative_closing_stock.sql`, `queries/results/` (both `_after_batch1` files), `README.md`.
Make the terminal font large and close notifications.

---

## 0. Intro (0:00 to 0:30)

**Screen:** README top (the model diagram).

- What it is: dbt Core + DuckDB, local, no credentials. Files go to raw, then validation, then clean, rejected and duplicate models, then a daily balance per product and warehouse.
- Say how the video is ordered: the 7 points from the brief.

## 1. Input fixture, movement rules, expected balances (0:30 to 1:45)

**Screen:** `fixture/batch_001.csv`, then `fixture/expected/daily_inventory_after_batch1.csv`.

- The first five rows are the brief's example: M001 receipt 20, M002 shipment 5 sent twice, M003 adjustment -2, M004 shipment 30, M005 with no product.
- Point at the extra rows and why each exists: P102/W02 gives a no-activity day on 03-02; M008 to M011 each hit one validation rule.
- Movement rules: receipt adds, shipment subtracts, both positive in the file; an adjustment carries its own sign and cannot be 0.
- Expected result: P101/W01 closes **15, 13, -17**, flagged negative on 03-03. These expected files are dbt seeds, so the tests compare against the same file.

## 2. Validation, rejection reasons, duplicates (1:45 to 4:00)

**Screen:** `stg_movements_validated.sql` (the comment block and the `case`), then `stg_valid_movements_ranked.sql`, then `duplicate_movements.sql`.

- Staging keeps every raw row and only labels it. The first failing rule wins, so each bad row has exactly one reason. Walk the order: missing fields, timestamp, type, integer, positive, nonzero adjustment.
- One detail worth saying: a regex check runs before the cast because DuckDB's `try_cast` turns `2.5` into 3.
- Duplicates: valid rows are numbered per movement_id with `row_number()`, first delivery wins. Row 1 goes to clean_movements; the rest go to duplicate_movements.
- If a movement_id comes back with *different* content, it is not dropped quietly: `is_exact_duplicate` is false and a test fails.
- **Tradeoffs:** first-failing-rule gives one clear reason per row, but a row with two defects only shows the first. Invalid rows are not deduplicated, so a bad row sent twice is two rejections (one per source row). Failing on conflicting re-sends is strict on purpose.

**Command:**
```bash
scripts/run_pipeline.sh --reset --state after_batch1 fixture/batch_001.csv | tail -3
python scripts/snapshot.py --counts-only
python scripts/snapshot.py --rejections
```
- Read the counts out loud: **12 raw = 6 accepted + 5 rejected + 1 duplicate**. Every row is accounted for.
- **Connect:** the `--rejections` output shows each reason next to its source line (`batch_001.csv:9` is M008), and the duplicate line shows which copy was kept. Because M002 is kept once, P101/W01 closes 03-01 at 15, not 10. Because M008 (shipment of -3) is rejected, it never touches P102/W02.

## 3. Model dependencies, missing dates, balance calculation (4:00 to 6:15)

**Screen:** the dbt docs lineage graph (browser tab from the setup; click the lineage icon, bottom right, on `daily_inventory`), then `int_date_spine.sql`, then `daily_inventory.sql`.

- Dependency path: raw → validated → ranked → clean / rejected / duplicates → spine + daily totals → daily_inventory. Every arrow is a `ref()` or `source()`, so dbt decides the build order.
- Materializations: staging and intermediate are views, the marts are tables. **Tradeoff:** views are cheap and always current but recomputed when read; tables are fast and stable for tests.
- Business dates: timestamps are read as UTC and the date is taken in UTC; both are settings. **Tradeoff:** no daylight-saving issues, but one timezone for all warehouses.
- Missing dates: `generate_series` from the earliest to the latest accepted date, joined to each pair from its first movement. Left join the totals, so a quiet day is a row of zeros.
- Balance: running sum of (received - shipped + adjustment); opening is `lag` of that, 0 on the first day; closing is written from the formula and the flag is `closing < 0`.
- **Tradeoff:** the spine runs to the last movement date in the data, not to today.

**Command:**
```bash
python scripts/snapshot.py
```
- Point at P102/W02 on 03-02: no movements, opening 10, closing 10. Point at P101/W01: 15, 13, **-17 True**.
- **Connect:** the 03-02 row for P102/W02 exists only because of the date spine; without it, the next day's opening would have nothing to read from. -17 is kept and flagged rather than rejected, because the brief's own example expects it.

## 4. Rerun on identical inputs (6:15 to 7:15)

**Command:**
```bash
scripts/run_pipeline.sh --state after_batch1 fixture/batch_001.csv | tail -1
python scripts/snapshot.py
```
- Same counts (12 raw, not 24) and same balances.
- Why, in three parts: the loader replaces a file's rows by file name (key is file + line), dbt rebuilds everything from raw with `--full-refresh`, and clean_movements is unique on movement_id.
- Mention `scripts/demo_phase5.sh` does this automatically and diffs the two snapshots.
- Show `fixture/actual/COMPARISON.md`: the saved actual results for the first run, the rerun and the late batch, each identical to `fixture/expected/`.

## 5. Late batch: historical and later balances (7:15 to 8:45)

**Screen:** `fixture/batch_002_late.csv`.

- L001 is a new receipt of 20 dated 03-02, which is earlier than 03-03, already processed. M004 is sent again.

**Command:**
```bash
scripts/run_pipeline.sh --state after_late fixture/batch_001.csv fixture/batch_002_late.csv | tail -1
python scripts/snapshot.py --pair P101/W01
python scripts/snapshot.py --counts-only
```
- Before and after for P101/W01: **03-01 stays 15** (before the late date), **03-02 goes 13 → 33** (its own date), **03-03 goes -17 → 3** (carried forward), and the negative flag clears.
- M004 is now a duplicate: 14 raw = 7 + 5 + 2. P102/W02 does not change.
- It works because the history is rebuilt and the running sum carries the change forward. Earlier days cannot change.
- **Tradeoff of the full rebuild:** simple and always correct, but every run reprocesses all history, and old balances are overwritten with no record of what they were before.

## 6. Tests and reporting queries (8:45 to 11:00)

**Command:**
```bash
cd dbt_project && dbt test --vars '{fixture_state: after_late}' | tail -3 && cd ..
python scripts/verify_queries.py | grep -E "PASS|FAIL|===" | head -20
```
**Screen:** README section 9 (the test table), then `queries/q1_daily_stock_by_warehouse.sql` with `queries/results/daily_stock_by_warehouse_after_batch1.csv`, then `queries/q2_negative_closing_stock.sql` with `queries/results/negative_closing_after_batch1.csv`.

- Group the tests by the rule they check: the balance formula, opening = previous closing, flag = closing < 0, no date gaps, unique daily grain, every raw row in exactly one bucket, and exact match with the expected files.
- The strongest one: `assert_closing_matches_clean_movements` recomputes closing straight from clean movements without the window logic.
- Tests that cannot fail prove nothing: `scripts/test_the_tests.py` corrupts the data 13 ways and all 13 are caught (show `docs/evidence/test_the_tests.txt`). It found a real gap that I then fixed.
- How exact results are checked: the expected CSV files in `fixture/expected/` are loaded as dbt seeds, and singular tests compare the models to them row by row.
- Gaps that remain: no dbt test for a non-UTC timezone, no volume or anomaly checks, and the exact-result tests only run when a fixture state is passed.
- Queries: Q1 is daily stock by warehouse; Q2 is negative closing days in a date range. Show the saved results: W01 closes 15, 13, -17 and W02 10, 10, 6; Q2 returns one row (P101/W01, 03-03, -17) after batch 1 and none after the late batch. Both match `fixture/expected/`.
- **Business rules the queries verify:** Q1 keeps closing = opening + received - shipped + adjustment at warehouse level, and its totals equal the cumulative signed movements per warehouse. Q2 returns exactly the days whose balance, recomputed from clean movements, is below 0, and its date filter is checked (03-01 to 03-02 returns 0 rows, 03-03 alone returns 1).

## 7. One limitation and the next improvement (11:00 to 12:00)

**Screen:** README section 10.

- Each run rebuilds the entire history: spine of pairs × days plus a window over all of it. Cost grows with total history, not with the new batch.
- Next step: incremental models. Find the pairs a batch touches and their earliest affected date, recompute only those from that date forward, starting from the previous day's stored closing. Keep a periodic full refresh and use the existing tests to check they agree.
- Keep this part short: one limitation, one improvement, no other production topics.
- Close: where the repo and the README are.

---

**After recording:**
1. Check the length is between 5 and 15 minutes.
2. In Loom, set sharing to "Anyone with the link can view".
3. Paste the link into the table at the top of `README.md` (replace `<LOOM LINK — add before submitting>`) and push.
4. Stop `dbt docs serve` in the second terminal (Ctrl+C).
