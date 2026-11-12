-- Rule: negative_balance is true exactly when closing_quantity < 0.
select product_id, warehouse_id, inventory_date, closing_quantity, negative_balance
from {{ ref('daily_inventory') }}
where negative_balance <> (closing_quantity < 0)
