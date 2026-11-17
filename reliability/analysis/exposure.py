from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class ExposureTotals:
    person_time: Fraction
    load_exposure: Fraction


def accumulate_exposure(prepared):
    times = {key: Fraction(0) for key in prepared.strata}
    loads = {key: Fraction(0) for key in prepared.strata}
    for member in prepared.members:
        for interval in member.intervals:
            duration = interval.stop - interval.start
            times[member.stratum] += duration
            loads[member.stratum] += duration * interval.load
    return {key: ExposureTotals(times[key], loads[key]) for key in prepared.strata}
