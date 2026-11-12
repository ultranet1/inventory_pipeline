/*
  Accepted movements: exactly one row per movement_id.
  signed_quantity: receipt +q, shipment -q, adjustment as given (already signed).
*/
select
    movement_id,
    product_id,
    warehouse_id,
    movement_type,
    quantity,
    case movement_type
        when 'receipt'    then  quantity
        when 'shipment'   then -quantity
        when 'adjustment' then  quantity
    end                                   as signed_quantity,
    event_ts_business                     as event_timestamp,
    cast(event_ts_business as date)       as business_date,
    raw_row_id,
    source_file
from {{ ref('stg_valid_movements_ranked') }}
where occurrence_number = 1
