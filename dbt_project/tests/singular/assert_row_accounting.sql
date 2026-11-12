-- Rule: accepted + rejected + duplicates = total raw rows, AND every raw row
-- lands in exactly one bucket (the totals alone could balance by coincidence).
with buckets as (
    select raw_row_id, 'accepted'  as bucket from {{ ref('clean_movements') }}
    union all
    select raw_row_id, 'rejected'  from {{ ref('rejected_movements') }}
    union all
    select raw_row_id, 'duplicate' from {{ ref('duplicate_movements') }}
),
per_row as (
    select r.raw_row_id, count(b.raw_row_id) as n_buckets
    from {{ source('raw', 'raw_movements') }} r
    left join buckets b using (raw_row_id)
    group by r.raw_row_id
),
totals as (
    select
        (select count(*) from {{ source('raw', 'raw_movements') }}) as raw_rows,
        (select count(*) from buckets)                              as bucketed_rows
)
select raw_row_id, n_buckets, cast(null as bigint) as raw_rows, cast(null as bigint) as bucketed_rows
from per_row where n_buckets <> 1
union all
select null, null, raw_rows, bucketed_rows from totals where raw_rows <> bucketed_rows
