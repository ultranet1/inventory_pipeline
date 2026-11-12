-- Rule: each day's opening = previous day's closing; a pair's first day opens at 0.
with ordered as (
    select
        *,
        lag(closing_quantity) over (
            partition by product_id, warehouse_id order by inventory_date) as prev_closing
    from {{ ref('daily_inventory') }}
)
select product_id, warehouse_id, inventory_date, opening_quantity, prev_closing
from ordered
where opening_quantity <> coalesce(prev_closing, 0)
