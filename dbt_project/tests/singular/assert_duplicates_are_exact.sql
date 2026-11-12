-- Rule: only EXACT duplicates may be dropped silently. A movement_id re-sent
-- with different content is a data conflict and fails here.
select movement_id, raw_row_id, kept_raw_row_id
from {{ ref('duplicate_movements') }}
where not is_exact_duplicate
