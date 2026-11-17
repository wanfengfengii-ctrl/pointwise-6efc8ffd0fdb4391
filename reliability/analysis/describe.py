from dataclasses import dataclass
from reliability.cohorts.snapshots import CohortService
from reliability.cohorts.members import member_summary
from reliability.cohorts.compile import compile_descriptive
from reliability.analysis.exposure import accumulate_exposure
from reliability.analysis.failures import count_failures
from reliability.analysis.strata import align_strata
from reliability.analysis.rates import calculate_rates


@dataclass
class DescriptiveResult:
    cohort_id: int
    revision: int
    members: list
    strata: list


class DescriptionService:
    def __init__(self, archive):
        self.cohorts = CohortService(archive)

    def describe(self, cohort_id):
        prepared = compile_descriptive(self.cohorts.load_snapshot(cohort_id))
        totals = align_strata(prepared, accumulate_exposure(prepared), count_failures(prepared))
        rates = calculate_rates(totals)
        rows = [{'stratum': row.stratum, 'person_time': row.person_time,
                 'load_exposure': row.load_exposure, 'failures': row.failures,
                 'rate': rates[row.stratum]} for row in totals]
        return DescriptiveResult(prepared.cohort_id, prepared.revision,
                                 [member_summary(x) for x in prepared.members], rows)
