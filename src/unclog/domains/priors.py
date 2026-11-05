"""Default priors per domain (brief §4.1, §4.3; decision 004).

RACE starts higher than back-end, but priors are deliberately small next to evidence weights in
``heat.py`` so they only break ties: a measured back-end signal always outranks a RACE guess.
Tune per industry later (Industry Knowledge Agent); record changes in docs/decisions/.
"""

from __future__ import annotations

from ..schemas.diagnosis import DomainName

RACE_PRIOR = 0.15
BACKEND_PRIOR = 0.04
OTHER_PRIOR = 0.02

#: Search/display order: RACE one letter at a time, then back-end (brief §9.2).
ORDER: tuple[DomainName, ...] = (
    DomainName.race_r,
    DomainName.race_a,
    DomainName.race_c,
    DomainName.race_e,
    DomainName.fulfillment,
    DomainName.ops,
    DomainName.support,
    DomainName.finance,
    DomainName.hr,
    DomainName.procurement,
    DomainName.product,
    DomainName.it,
    DomainName.legal,
    DomainName.mgmt,
    DomainName.other,
)


def default_prior(name: DomainName) -> float:
    if name is DomainName.other:
        return OTHER_PRIOR
    return RACE_PRIOR if name.is_race else BACKEND_PRIOR
