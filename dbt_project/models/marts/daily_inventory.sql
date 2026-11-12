/*
  Daily balance per product / warehouse. Grain: product_id + warehouse_id + inventory_date.

    closing = opening + received - shipped + adjustment
    opening = previous day's closing (0 on a pair's first day)

  The running closing is computed as a cumulative sum, and opening is taken
  from the previous row with lag(); the final closing column is then recomputed
  from the formula so tests can independently prove the two agree.
*/
with joined as (

    select
        s.product_id,
        s.warehouse_id,
        s.inventory_date,
        coalesce(t.received_quantity,   0) as received_quantity,
        coalesce(t.shipped_quantity,    0) as shipped_quantity,
        coalesce(t.adjustment_quantity, 0) as adjustment_quantity
    from {{ ref('int_date_spine') }} s
    left join {{ ref('int_daily_movement_totals') }} t
      on  t.product_id    = s.product_id
      and t.warehouse_id  = s.warehouse_id
      and t.business_date = s.inventory_date

),

running as (

    select
        *,
        sum(received_quantity - shipped_quantity + adjustment_quantity) over (
            partition by product_id, warehouse_id
            order by inventory_date
            rows between unbounded preceding and current row
        ) as running_closing
    from joined

),

with_opening as (

    select
        *,
        coalesce(
            lag(running_closing) over (
                partition by product_id, warehouse_id order by inventory_date),
            0
        ) as opening_quantity
    from running

)

select
    product_id,
    warehouse_id,
    inventory_date,
    cast(opening_quantity as bigint)                                                     as opening_quantity,
    cast(received_quantity as bigint)                                                    as received_quantity,
    cast(shipped_quantity as bigint)                                                     as shipped_quantity,
    cast(adjustment_quantity as bigint)                                                  as adjustment_quantity,
    cast(opening_quantity + received_quantity - shipped_quantity + adjustment_quantity as bigint) as closing_quantity,
    (opening_quantity + received_quantity - shipped_quantity + adjustment_quantity) < 0  as negative_balance
from with_opening
