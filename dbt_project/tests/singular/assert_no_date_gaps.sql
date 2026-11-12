-- Rule: per product/warehouse, every date from first to last is present (step of exactly 1 day).
with ordered as (
    select
        product_id, warehouse_id, inventory_date,
        lag(inventory_date) over (
            partition by product_id, warehouse_id order by inventory_date) as prev_date
    from {{ ref('daily_inventory') }}
)
select *
from ordered
where prev_date is not null
  and inventory_date - prev_date <> 1
