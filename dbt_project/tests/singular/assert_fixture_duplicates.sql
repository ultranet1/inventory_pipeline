{#- Exact check of WHICH rows were removed as duplicates, and which row was kept,
    against fixture/expected/duplicates.csv for the selected fixture state. -#}
{% if var('fixture_state') == 'none' %}
select 1 as skipped where false
{% else %}
with expected as (
    select movement_id, raw_row_id, kept_raw_row_id, is_exact_duplicate
    from {{ ref('duplicates') }}
    where state = '{{ var("fixture_state") }}'
),
actual as (
    select movement_id, raw_row_id, kept_raw_row_id, is_exact_duplicate
    from {{ ref('duplicate_movements') }}
)
select 'missing_from_model' as problem, * from (select * from expected except select * from actual)
union all
select 'unexpected_in_model', * from (select * from actual except select * from expected)
{% endif %}
