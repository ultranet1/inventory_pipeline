-- Independent recomputation: closing = sum of signed_quantity of every accepted
-- movement on or before that day. Uses clean_movements only, NOT the window
-- logic in daily_inventory, so it catches errors in the spine/join/window.
select
    d.product_id, d.warehouse_id, d.inventory_date,
    d.closing_quantity,
    coalesce(sum(c.signed_quantity), 0) as expected_closing
from {{ ref('daily_inventory') }} d
left join {{ ref('clean_movements') }} c
  on  c.product_id = d.product_id
  and c.warehouse_id = d.warehouse_id
  and c.business_date <= d.inventory_date
group by d.product_id, d.warehouse_id, d.inventory_date, d.closing_quantity
having d.closing_quantity <> coalesce(sum(c.signed_quantity), 0)
