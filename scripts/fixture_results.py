#!/usr/bin/env python3
"""Save the ACTUAL fixture results next to the expected ones and compare them.

Runs the fixture through three states and exports what the pipeline produced:

  fixture/actual/after_batch1/   first run on batch_001.csv
  fixture/actual/rerun/          same input loaded and built again (must equal after_batch1)
  fixture/actual/after_late/     batch_001.csv + batch_002_late.csv

Each folder holds counts.csv, rejections.csv, duplicates.csv and daily_inventory.csv in the
same format as fixture/expected/, and fixture/actual/COMPARISON.md records the result of
comparing every file with its expected version.

    python scripts/fixture_results.py

Uses its own database (data/fixture_results.duckdb). Exits non-zero on any difference.
"""
import csv
import os
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
EXP, ACT = ROOT / "fixture" / "expected", ROOT / "fixture" / "actual"
DB = ROOT / "data" / "fixture_results.duckdb"
B1, B2 = "fixture/batch_001.csv", "fixture/batch_002_late.csv"

QUERIES = {
    "counts": "select '{state}' as state, raw_rows, accepted, rejected, duplicates, daily_rows "
              "from analytics.movement_accounting",
    "rejections": "select movement_id, rejection_reason from analytics.rejected_movements "
                  "order by source_file, source_row_number",
    "duplicates": "select '{state}' as state, movement_id, raw_row_id, kept_raw_row_id, is_exact_duplicate "
                  "from analytics.duplicate_movements order by source_file, source_row_number",
    "daily_inventory": "select * from analytics.daily_inventory order by product_id, warehouse_id, inventory_date",
}


def fmt(v):
    return str(v).lower() if isinstance(v, bool) else str(v)


def build(state, files, reset):
    cmd = ["scripts/run_pipeline.sh", *(["--reset"] if reset else []), "--state", state, *files]
    r = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, INVENTORY_DB=str(DB)), capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout[-3000:] + r.stderr[-2000:])
    return [l.split("Done. ")[-1] for l in r.stdout.splitlines() if "Done. PASS" in l][-1]


def export(folder, state):
    folder.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    out = {}
    for name, sql in QUERIES.items():
        cur = con.execute(sql.format(state=state))
        rows = [[c[0] for c in cur.description]] + [[fmt(v) for v in r] for r in cur.fetchall()]
        with open(folder / f"{name}.csv", "w", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)
        out[name] = rows
    con.close()
    return out


def expected(name, state):
    """Expected rows for one file and state, in the same shape as the export."""
    path = EXP / (f"daily_inventory_{state}.csv" if name == "daily_inventory" else f"{name}.csv")
    rows = list(csv.reader(open(path)))
    if "state" in rows[0]:
        rows = [rows[0]] + [r for r in rows[1:] if r[0] == state]
    return rows


def main():
    report, failures = [], 0
    runs = [("after_batch1", "after_batch1", [B1], True),
            ("rerun", "after_batch1", [B1], False),
            ("after_late", "after_late", [B1, B2], False)]
    actual = {}
    for folder, state, files, reset in runs:
        summary = build(state, files, reset)
        actual[folder] = export(ACT / folder, state)
        print(f"\n== {folder}: {' + '.join(Path(f).name for f in files)}  (dbt: {summary})")
        report.append(f"\n## {folder}\n\nInput: {', '.join(f'`{f}`' for f in files)}"
                      f"{' (loaded again into the same database)' if folder == 'rerun' else ''}. dbt: `{summary}`.\n")
        report.append("| file | expected | actual | rows | result |\n|---|---|---|---|---|")
        for name in QUERIES:
            exp, act = expected(name, state), actual[folder][name]
            # rejections.csv has no state column; counts/duplicates carry the state of the expectations
            ok = exp == act
            failures += not ok
            exp_file = f"daily_inventory_{state}.csv" if name == "daily_inventory" else f"{name}.csv" + (
                f" (state = {state})" if "state" in exp[0] else "")
            report.append(f"| {name} | `expected/{exp_file}` | `actual/{folder}/{name}.csv` | {len(act) - 1} | "
                          f"{'identical' if ok else '**DIFFERENT**'} |")
            print(f"  {'PASS' if ok else 'FAIL'}  {name:16} {len(act) - 1} rows  vs expected/{exp_file}")
    same = actual["rerun"] == actual["after_batch1"]
    failures += not same
    print(f"\n  {'PASS' if same else 'FAIL'}  rerun: every actual file identical to the first run")
    report.append(f"\nRerun check: every file in `actual/rerun/` is "
                  f"{'identical to' if same else '**different from**'} `actual/after_batch1/`.")

    b = [r for r in actual["after_batch1"]["daily_inventory"][1:] if r[:2] == ["P101", "W01"]]
    l = [r for r in actual["after_late"]["daily_inventory"][1:] if r[:2] == ["P101", "W01"]]
    lines = ["\n## Late-arriving data: P101/W01 before and after\n",
             "| date | closing before | closing after | change |", "|---|---|---|---|"]
    for x, y in zip(b, l):
        d = int(y[7]) - int(x[7])
        lines.append(f"| {x[2]} | {x[7]} | {y[7]} | {'+' if d > 0 else ''}{d if d else 'unchanged'} |")
    report += lines

    head = ["# Fixture: expected vs actual results",
            "", "Generated by `python scripts/fixture_results.py`. Expected files: `fixture/expected/`; actual files: "
            "`fixture/actual/<run>/`, exported from the pipeline's tables after each run.",
            "", "Coverage: rejected rows (`rejections.csv`), duplicates (`duplicates.csv`), missing activity dates "
            "(P102/W02 on 2026-03-02 in `daily_inventory.csv`), daily balances (`daily_inventory.csv`), "
            "reruns (`rerun/`), late-arriving data (`after_late/`). Row counts: `counts.csv`."]
    total = f"\n**Result: {'all files identical to expected' if not failures else f'{failures} difference(s)'}.**"
    (ACT / "COMPARISON.md").write_text("\n".join(head + report) + "\n" + total + "\n")
    print(f"\nwrote {(ACT / 'COMPARISON.md').relative_to(ROOT)}")
    print("ALL IDENTICAL" if not failures else f"{failures} DIFFERENCE(S)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
