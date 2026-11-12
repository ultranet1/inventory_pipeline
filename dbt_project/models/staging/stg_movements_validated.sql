{{ config(materialized='view') }}

/*
  Validation layer: ONE row per raw row, nothing dropped.
  rejection_reason is NULL for valid rows. Rules are applied in a fixed order
  and the FIRST failing rule wins, so each bad row gets exactly one reason:

    1. missing_<field>         movement_id, product_id, warehouse_id, movement_type,
                               quantity, event_timestamp (checked in that order)
    2. invalid_timestamp       must match YYYY-MM-DD HH:MM:SS (T separator allowed)
                               AND be a real calendar time
    3. invalid_movement_type   must be exactly receipt | shipment | adjustment
    4. non_integer_quantity    must look like an integer (optional sign, digits only)
    5. non_positive_quantity   receipt/shipment quantity must be > 0
    6. zero_adjustment         adjustment quantity must be <> 0 (may be negative)

  Regex guards run BEFORE casting because DuckDB's try_cast is too lenient:
  try_cast('2.5' as bigint) rounds to 3 and try_cast('infinity' as timestamp) succeeds.
*/

with raw as (

    select
        raw_row_id,
        source_file,
        source_row_number,
        nullif(trim(movement_id), '')     as movement_id,
        nullif(trim(product_id), '')      as product_id,
        nullif(trim(warehouse_id), '')    as warehouse_id,
        nullif(trim(movement_type), '')   as movement_type,
        nullif(trim(quantity), '')        as quantity_raw,
        nullif(trim(event_timestamp), '') as event_timestamp_raw
    from {{ source('raw', 'raw_movements') }}

),

parsed as (

    select
        *,
        case
            when regexp_matches(event_timestamp_raw,
                 '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}$')
            then try_cast(event_timestamp_raw as timestamp)
        end as event_ts_local,
        case
            when regexp_matches(quantity_raw, '^[+-]?[0-9]+$')
            then try_cast(quantity_raw as bigint)
        end as quantity_int
    from raw

),

validated as (

    select
        *,
        case
            when movement_id          is null then 'missing_movement_id'
            when product_id           is null then 'missing_product_id'
            when warehouse_id         is null then 'missing_warehouse_id'
            when movement_type        is null then 'missing_movement_type'
            when quantity_raw         is null then 'missing_quantity'
            when event_timestamp_raw  is null then 'missing_event_timestamp'
            when event_ts_local       is null then 'invalid_timestamp'
            when movement_type not in ('receipt', 'shipment', 'adjustment')
                                              then 'invalid_movement_type'
            when quantity_int         is null then 'non_integer_quantity'
            when movement_type in ('receipt', 'shipment') and quantity_int <= 0
                                              then 'non_positive_quantity'
            when movement_type = 'adjustment' and quantity_int = 0
                                              then 'zero_adjustment'
        end as rejection_reason
    from parsed

)

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
    quantity_int                                         as quantity,
    -- naive source timestamp is read as source_timezone, then converted to the
    -- business timezone before taking the date (needs DuckDB's ICU, bundled).
    cast(
        timezone('{{ var("business_timezone") }}',
                 timezone('{{ var("source_timezone") }}', event_ts_local))
        as timestamp)                                    as event_ts_business,
    rejection_reason,
    rejection_reason is null                             as is_valid
from validated
