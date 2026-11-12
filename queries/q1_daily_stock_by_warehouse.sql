-- Query 1: daily stock totals by warehouse.
--
-- One row per warehouse per day: the sum over all products in that warehouse of
-- the daily_inventory columns, so the balance identity still holds at warehouse level:
--     closing_quantity = opening_quantity + received - shipped + adjustment
--
-- Reads only analytics.daily_inventory (the tested mart), so the numbers here are
-- the same balances the dbt business-rule tests already verify. A product whose
-- spine has not started yet (no movement so far) contributes 0, which is its
-- true stock, so leaving it out of the sum is correct.
--
-- Optional date filter (DuckDB variables; defaults to the full date range):
--     set variable start_date = date '2026-03-01';
--     set variable end_date   = date '2026-03-31';
--
-- Run:  duckdb data/inventory.duckdb < queries/q1_daily_stock_by_warehouse.sql

select
    warehouse_id,
    inventory_date,
    sum(opening_quantity)       as opening_quantity,
    sum(received_quantity)      as received_quantity,
    sum(shipped_quantity)       as shipped_quantity,
    sum(adjustment_quantity)    as adjustment_quantity,
    sum(closing_quantity)       as closing_quantity,
    count(*)                    as product_count      -- products with a balance row that day
from analytics.daily_inventory
where inventory_date between coalesce(cast(getvariable('start_date') as date), date '0001-01-01')
                         and coalesce(cast(getvariable('end_date')   as date), date '9999-12-31')
group by warehouse_id, inventory_date
order by warehouse_id, inventory_date;
