-- Rule: closing = opening + received - shipped + adjustment. Returns violating rows.
select *
from {{ ref('daily_inventory') }}
where closing_quantity <> opening_quantity + received_quantity - shipped_quantity + adjustment_quantity
