{#- Exact expected-result check. Only active when run with
    --vars '{fixture_state: after_batch1}' or '{fixture_state: after_late}'.
    With the default ('none') it returns no rows, so large generated data is unaffected. -#}
{% set state = var('fixture_state') %}
{% if state == 'after_batch1' %}{% set expected = ref('daily_inventory_after_batch1') %}
{% elif state == 'after_late' %}{% set expected = ref('daily_inventory_after_late') %}
{% else %}{% set expected = none %}{% endif %}

{% if expected is none %}
select 1 as skipped where false
{% else %}
{% set cols = 'product_id, warehouse_id, inventory_date, opening_quantity, received_quantity, shipped_quantity, adjustment_quantity, closing_quantity, negative_balance' %}
select 'missing_from_model' as problem, * from (
    select {{ cols }} from {{ expected }}
    except select {{ cols }} from {{ ref('daily_inventory') }}
)
union all
select 'unexpected_in_model' as problem, * from (
    select {{ cols }} from {{ ref('daily_inventory') }}
    except select {{ cols }} from {{ expected }}
)
{% endif %}
