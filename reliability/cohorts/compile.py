from dataclasses import dataclass
from reliability.cohorts.members import member_payload, member_from_payload


@dataclass(frozen=True)
class DescriptiveInput:
    cohort_id: int
    revision: int
    members: tuple
    strata: tuple


def compile_descriptive(snapshot):
    members = tuple(member_from_payload(member_payload(member)) for member in snapshot.members)
    if len({member.device_id for member in members}) != len(members):
        raise ValueError('duplicate frozen device')
    return DescriptiveInput(snapshot.cohort_id, snapshot.revision, members,
                            tuple(sorted({member.stratum for member in members})))
