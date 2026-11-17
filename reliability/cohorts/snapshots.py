from dataclasses import dataclass
from reliability.records.revisions import RecordService
from reliability.cohorts.selection import select_revision_devices
from reliability.cohorts.members import (
    freeze_member, member_payload, member_from_payload, member_summary,
)
from reliability.archive import queries
from reliability.archive.transactions import transaction


@dataclass(frozen=True)
class CohortSnapshot:
    cohort_id: int
    revision: int
    members: tuple

    def summary(self):
        return {'cohort_id': self.cohort_id, 'revision': self.revision,
                'members': [member_summary(member) for member in self.members]}


class CohortService:
    def __init__(self, archive):
        self.archive = archive

    def freeze(self, revision, device_ids):
        devices = select_revision_devices(RecordService(self.archive), revision, device_ids)
        members = tuple(freeze_member(device) for device in devices)
        with transaction(self.archive.connection):
            cohort_id = queries.insert_snapshot_rows(
                self.archive.connection, revision,
                {member.device_id: member_payload(member) for member in members})
        return CohortSnapshot(cohort_id, revision, members).summary()

    def load_snapshot(self, cohort_id):
        revision, payloads = queries.read_snapshot_rows(self.archive.connection, cohort_id)
        members = tuple(member_from_payload(payload) for payload in payloads.values())
        return CohortSnapshot(cohort_id, revision, members)
