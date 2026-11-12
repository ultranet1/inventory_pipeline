/*
  Valid rows removed because their movement_id was already delivered.
  is_exact_duplicate checks the payload matches the kept row, so a movement_id
  re-sent with DIFFERENT content is visible instead of silently discarded.
*/
select
    d.raw_row_id,
    d.source_file,
    d.source_row_number,
    d.movement_id,
    (   d.product_id          = k.product_id
    and d.warehouse_id        = k.warehouse_id
    and d.movement_type       = k.movement_type
    and d.quantity            = k.quantity
    and d.event_ts_business   = k.event_ts_business
    ) as is_exact_duplicate,
    k.raw_row_id as kept_raw_row_id
from {{ ref('stg_valid_movements_ranked') }} d
join {{ ref('stg_valid_movements_ranked') }} k
  on k.movement_id = d.movement_id
 and k.occurrence_number = 1
where d.occurrence_number > 1
