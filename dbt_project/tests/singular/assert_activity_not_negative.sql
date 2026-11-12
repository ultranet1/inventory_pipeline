-- Rule: received/shipped are positive magnitudes; only adjustments are signed.
select *
from {{ ref('daily_inventory') }}
where received_quantity < 0 or shipped_quantity < 0
