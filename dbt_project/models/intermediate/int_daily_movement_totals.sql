{{ config(materialized='view') }}

-- Activity per product / warehouse / day. Receipts and shipments are positive
-- magnitudes; adjustments keep their sign.
select
    product_id,
    warehouse_id,
    business_date,
    sum(case when movement_type = 'receipt'    then quantity else 0 end) as received_quantity,
    sum(case when movement_type = 'shipment'   then quantity else 0 end) as shipped_quantity,
    sum(case when movement_type = 'adjustment' then quantity else 0 end) as adjustment_quantity
from {{ ref('clean_movements') }}
group by 1, 2, 3
