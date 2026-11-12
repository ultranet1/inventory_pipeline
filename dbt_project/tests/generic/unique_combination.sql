{% test unique_combination(model, columns) %}
{#- Fails for every combination of `columns` that appears more than once.
    Local replacement for dbt_utils.unique_combination_of_columns (no package install needed). -#}
select {{ columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
