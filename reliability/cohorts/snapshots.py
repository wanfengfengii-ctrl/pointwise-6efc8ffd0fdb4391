from dataclasses import dataclass
from reliability.records.revisions import RecordService
from reliability.cohorts.selection import select_revision_devices
from reliability.cohorts.members import (
    freeze_member, member_payload, member_from_payload, member_summary,
)
from reliability.cohorts.risk import build_risk_plan
from reliability.archive.codec import encode_value, decode_value
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

    def compile_risk(self, cohort_id):
        snapshot = self.load_snapshot(cohort_id)
        projection = build_risk_plan(snapshot)
        body = encode_value(projection)
        with transaction(self.archive.connection):
            plan_id = queries.insert_risk_plan_rows(
                self.archive.connection, cohort_id, snapshot.revision, body)
        return decode_value(queries.read_risk_plan_row(
            self.archive.connection, plan_id)['payload']) | {'plan_id': plan_id}

    def load_risk(self, plan_id):
        row = queries.read_risk_plan_row(self.archive.connection, plan_id)
        projection = decode_value(row['payload'])
        if projection['cohort_id'] != row['cohort_id'] \
                or projection['revision'] != row['revision']:
            raise ValueError('risk plan binding mismatch')
        return projection | {'plan_id': plan_id}
