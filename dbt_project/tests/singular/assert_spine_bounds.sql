-- Rule: each pair starts on its first valid movement date and every pair runs
-- to the dataset's latest valid movement date.
with expected as (
    select
        product_id, warehouse_id,
        min(business_date) as first_date,
        (select max(business_date) from {{ ref('clean_movements') }}) as last_date
    from {{ ref('clean_movements') }}
    group by 1, 2
),
actual as (
    select product_id, warehouse_id,
           min(inventory_date) as first_date, max(inventory_date) as last_date
    from {{ ref('daily_inventory') }}
    group by 1, 2
)
select coalesce(e.product_id, a.product_id) as product_id,
       coalesce(e.warehouse_id, a.warehouse_id) as warehouse_id,
       e.first_date as expected_first, a.first_date as actual_first,
       e.last_date  as expected_last,  a.last_date  as actual_last
from expected e
full outer join actual a using (product_id, warehouse_id)
where e.first_date is distinct from a.first_date
   or e.last_date  is distinct from a.last_date
