-- Reconciliation of every raw row into exactly one bucket. A one-row summary
-- that the README, tests and demo script all read.
-- A view, not a table: it must count raw_movements as it is NOW. As a table it
-- froze the counts at build time, so a raw row added after the build went
-- unnoticed by assert_fixture_counts (found by scripts/test_the_tests.py).
{{ config(materialized='view') }}
select
    (select count(*) from {{ source('raw', 'raw_movements') }}) as raw_rows,
    (select count(*) from {{ ref('clean_movements') }})         as accepted,
    (select count(*) from {{ ref('rejected_movements') }})      as rejected,
    (select count(*) from {{ ref('duplicate_movements') }})     as duplicates,
    (select count(*) from {{ ref('daily_inventory') }})         as daily_rows
