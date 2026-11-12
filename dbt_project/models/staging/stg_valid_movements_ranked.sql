{{ config(materialized='view') }}

/*
  Valid rows only, numbered within each movement_id.
  occurrence_number = 1 is the row that is kept; anything > 1 is a duplicate delivery.
  Order is (source_file, source_row_number), i.e. first delivery wins. Files are
  named batch_NNN_*.csv so that file-name order equals delivery order.
*/
select
    *,
    row_number() over (
        partition by movement_id
        order by source_file, source_row_number
    ) as occurrence_number
from {{ ref('stg_movements_validated') }}
where is_valid
