{#- Accepted / rejected / duplicate / raw / daily row counts vs fixture/expected/counts.csv. -#}
{% if var('fixture_state') == 'none' %}
select 1 as skipped where false
{% else %}
select e.state, e.raw_rows, a.raw_rows as actual_raw, e.accepted, a.accepted as actual_accepted,
       e.rejected, a.rejected as actual_rejected, e.duplicates, a.duplicates as actual_duplicates,
       e.daily_rows, a.daily_rows as actual_daily_rows
from {{ ref('counts') }} e
cross join {{ ref('movement_accounting') }} a
where e.state = '{{ var("fixture_state") }}'
  and (e.raw_rows <> a.raw_rows or e.accepted <> a.accepted or e.rejected <> a.rejected
       or e.duplicates <> a.duplicates or e.daily_rows <> a.daily_rows)
{% endif %}
