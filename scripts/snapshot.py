#!/usr/bin/env python3
"""Print accounting counts and daily_inventory rows (optionally filtered) for demos/verification."""
import argparse, os, duckdb

p = argparse.ArgumentParser()
p.add_argument("--db", default=os.environ.get("INVENTORY_DB", "data/inventory.duckdb"))
p.add_argument("--pair", help="e.g. P101/W01 to show only that product/warehouse")
p.add_argument("--counts-only", action="store_true")
p.add_argument("--rejections", action="store_true", help="list rejected rows and duplicates, then exit")
a = p.parse_args()
con = duckdb.connect(a.db, read_only=True)
raw, acc, rej, dup, rows = con.execute(
    "select raw_rows, accepted, rejected, duplicates, daily_rows from analytics.movement_accounting").fetchone()
print(f"counts: raw={raw} accepted={acc} rejected={rej} duplicates={dup} (sum={acc+rej+dup}) daily_rows={rows}")
if a.rejections:
    for r in con.execute("select movement_id, rejection_reason, raw_row_id from analytics.rejected_movements order by source_file, source_row_number").fetchall():
        print(f"rejected   {r[0] or '(null)':8}{r[1]:24}{r[2]}")
    for r in con.execute("select movement_id, is_exact_duplicate, raw_row_id, kept_raw_row_id from analytics.duplicate_movements order by source_file, source_row_number").fetchall():
        print(f"duplicate  {r[0]:8}{'exact' if r[1] else 'CONFLICT':24}{r[2]}  (kept {r[3]})")
    raise SystemExit(0)
if a.counts_only:
    raise SystemExit(0)
q = "select product_id, warehouse_id, inventory_date, opening_quantity o, received_quantity r, shipped_quantity s, adjustment_quantity a, closing_quantity c, negative_balance neg from analytics.daily_inventory"
args = []
if a.pair:
    q += " where product_id = ? and warehouse_id = ?"; args = a.pair.split("/")
q += " order by 1, 2, 3"
print(f"{'product':8}{'wh':5}{'date':12}{'open':>7}{'recv':>7}{'ship':>7}{'adj':>6}{'close':>8}  neg")
for r in con.execute(q, args).fetchall():
    print(f"{r[0]:8}{r[1]:5}{str(r[2]):12}{r[3]:>7} {r[4]:>6} {r[5]:>6} {r[6]:>5} {r[7]:>7}  {r[8]}")
