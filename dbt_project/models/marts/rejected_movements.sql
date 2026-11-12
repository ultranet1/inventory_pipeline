-- One row per invalid SOURCE row (not per movement_id), with the reason it failed.
select
    raw_row_id,
    source_file,
    source_row_number,
    movement_id,
    product_id,
    warehouse_id,
    movement_type,
    quantity_raw,
    event_timestamp_raw,
    rejection_reason
from {{ ref('stg_movements_validated') }}
where not is_valid
