{#- Exact check of rejected rows + reasons against fixture/expected/rejections.csv. -#}
{% if var('fixture_state') == 'none' %}
select 1 as skipped where false
{% else %}
select 'missing_from_model' as problem, * from (
    select movement_id, rejection_reason from {{ ref('rejections') }}
    except select movement_id, rejection_reason from {{ ref('rejected_movements') }}
)
union all
select 'unexpected_in_model', * from (
    select movement_id, rejection_reason from {{ ref('rejected_movements') }}
    except select movement_id, rejection_reason from {{ ref('rejections') }}
)
{% endif %}
