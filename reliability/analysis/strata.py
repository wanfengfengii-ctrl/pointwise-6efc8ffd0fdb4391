from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class StratumTotals:
    stratum: str
    person_time: Fraction
    load_exposure: Fraction
    failures: int


def align_strata(prepared, exposure, failures):
    expected = set(prepared.strata)
    if set(exposure) != expected or set(failures) != expected:
        raise ValueError('descriptive stratum mismatch')
    return tuple(StratumTotals(key, exposure[key].person_time,
                               exposure[key].load_exposure, failures[key])
                 for key in prepared.strata)
