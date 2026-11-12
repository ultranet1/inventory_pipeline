{{ config(materialized='view') }}

/*
  One row per product/warehouse per calendar day, from that pair's FIRST valid
  movement date to the dataset's LATEST valid movement date. Gaps (no-activity
  days) therefore exist as rows; days before a pair's first movement do not.
*/
with bounds as (

    select
        product_id,
        warehouse_id,
        min(business_date) as first_date
    from {{ ref('clean_movements') }}
    group by 1, 2

),

dataset as (

    select min(business_date) as min_date, max(business_date) as max_date
    from {{ ref('clean_movements') }}

),

calendar as (

    select cast(d as date) as inventory_date
    from dataset,
         unnest(generate_series(min_date, max_date, interval 1 day)) as t(d)

)

select
    b.product_id,
    b.warehouse_id,
    c.inventory_date
from bounds b
join calendar c
  on c.inventory_date >= b.first_date
