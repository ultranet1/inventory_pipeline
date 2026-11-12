-- Query 2: product/warehouse combinations with negative closing stock
--          over a selected date range.
--
-- One row per product / warehouse / day whose closing_quantity < 0 inside the
-- range, newest problems last. Uses the negative_balance flag that dbt tests
-- prove equals (closing_quantity < 0).
--
-- Select the range with DuckDB variables (inclusive; default = full date range):
--     set variable start_date = date '2026-03-01';
--     set variable end_date   = date '2026-03-03';
--
-- Run:  duckdb data/inventory.duckdb < queries/q2_negative_closing_stock.sql
-- For one row per combination instead (first/last negative day, worst balance),
-- wrap this in: select product_id, warehouse_id, min(inventory_date), max(inventory_date),
--               count(*), min(closing_quantity) from (...) group by 1, 2

select
    product_id,
    warehouse_id,
    inventory_date,
    closing_quantity
from analytics.daily_inventory
where negative_balance
  and inventory_date between coalesce(cast(getvariable('start_date') as date), date '0001-01-01')
                         and coalesce(cast(getvariable('end_date')   as date), date '9999-12-31')
order by product_id, warehouse_id, inventory_date;
