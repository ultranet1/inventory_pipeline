#!/usr/bin/env python3
"""Deterministic generator for synthetic warehouse inventory movement files.

Produces two CSV files in --out-dir:
  batch_001.csv        the main batch (exact duplicates + invalid rows included)
  batch_002_late.csv   a late-arriving batch: NEW movement_ids whose business
                       dates are earlier than dates already in batch 1, plus a
                       few exact re-deliveries of batch-1 rows.

Same --seed and parameters always produce byte-identical files.

Example:
  python generator/generate_movements.py --rows 20000 --seed 42 --out-dir data/sample
"""
import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

FIELDS = ["movement_id", "product_id", "warehouse_id", "movement_type", "quantity", "event_timestamp"]
WAREHOUSES = ["W01", "W02"]  # two fictional warehouses
TS_FMT = "%Y-%m-%d %H:%M:%S"


def make_valid_row(rng, movement_id, products, start, days):
    mtype = rng.choices(["receipt", "shipment", "adjustment"], weights=[40, 50, 10])[0]
    if mtype == "adjustment":
        qty = rng.choice([-1, 1]) * rng.randint(1, 5)
    elif mtype == "receipt":
        qty = rng.randint(5, 50)
    else:
        qty = rng.randint(1, 30)
    ts = start + timedelta(days=rng.randrange(days), seconds=rng.randrange(86400))
    return {
        "movement_id": movement_id,
        "product_id": rng.choice(products),
        "warehouse_id": rng.choice(WAREHOUSES),
        "movement_type": mtype,
        "quantity": str(qty),
        "event_timestamp": ts.strftime(TS_FMT),
    }


def corrupt(rng, row):
    """Turn a valid row into an invalid one (one defect per row)."""
    row = dict(row)
    kind = rng.choice([
        "null_product", "null_warehouse", "null_quantity", "bad_timestamp",
        "bad_type", "negative_receipt_or_shipment", "zero_adjustment", "fractional_qty",
    ])
    if kind == "null_product":
        row["product_id"] = ""
    elif kind == "null_warehouse":
        row["warehouse_id"] = ""
    elif kind == "null_quantity":
        row["quantity"] = ""
    elif kind == "bad_timestamp":
        row["event_timestamp"] = rng.choice(["not-a-date", "2026-13-45 99:00:00", "yesterday"])
    elif kind == "bad_type":
        row["movement_type"] = rng.choice(["transfer", "RETURNED", "sale"])
    elif kind == "negative_receipt_or_shipment":
        row["movement_type"] = rng.choice(["receipt", "shipment"])
        row["quantity"] = str(-rng.randint(1, 10))
    elif kind == "zero_adjustment":
        row["movement_type"] = "adjustment"
        row["quantity"] = "0"
    elif kind == "fractional_qty":
        row["quantity"] = "2.5"
    return row


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=int, default=20000, help="approx. rows in the main batch (incl. dups/invalid)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--products", type=int, default=50)
    p.add_argument("--days", type=int, default=60, help="span of event dates in the main batch")
    p.add_argument("--start-date", default="2026-01-01")
    p.add_argument("--duplicate-rate", type=float, default=0.03)
    p.add_argument("--invalid-rate", type=float, default=0.03)
    p.add_argument("--late-rate", type=float, default=0.01, help="late batch size as a fraction of --rows")
    p.add_argument("--out-dir", default="data/sample")
    a = p.parse_args()

    rng = random.Random(a.seed)  # fixed seed => deterministic output
    products = [f"P{100 + i}" for i in range(a.products)]
    start = datetime.strptime(a.start_date, "%Y-%m-%d")

    n_dup = int(a.rows * a.duplicate_rate)
    n_invalid = int(a.rows * a.invalid_rate)
    n_base = a.rows - n_dup  # unique movement_ids in batch 1 (valid + invalid)

    base = []
    for i in range(1, n_base + 1):
        row = make_valid_row(rng, f"M{i:07d}", products, start, a.days)
        base.append(row)
    for idx in rng.sample(range(n_base), n_invalid):
        base[idx] = corrupt(rng, base[idx])

    # Exact duplicates: re-emit identical copies of random rows (valid or invalid).
    # Copies of valid rows are the "exact duplicates" the pipeline must collapse.
    dups = [dict(base[i]) for i in rng.sample(range(n_base), n_dup)]
    batch1 = base + dups
    rng.shuffle(batch1)

    # Late batch: new ids, earlier dates than the latest date already processed.
    n_late = max(1, int(a.rows * a.late_rate))
    late_days = max(1, a.days // 2)  # strictly inside the already-processed window
    late = [make_valid_row(rng, f"L{i:07d}", products, start, late_days) for i in range(1, n_late + 1)]
    # a few exact re-deliveries of rows already in batch 1 (must not double count)
    valid_base = [r for r in base if r["movement_id"].startswith("M")]
    late += [dict(r) for r in rng.sample(valid_base, min(len(valid_base), max(1, n_late // 10)))]
    rng.shuffle(late)

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "batch_001.csv", batch1)
    write_csv(out / "batch_002_late.csv", late)
    print(f"wrote {len(batch1)} rows to {out/'batch_001.csv'} and {len(late)} rows to {out/'batch_002_late.csv'}")


if __name__ == "__main__":
    main()
