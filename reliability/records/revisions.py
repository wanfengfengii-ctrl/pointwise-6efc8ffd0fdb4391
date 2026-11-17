from dataclasses import dataclass
from reliability.records.devices import normalise_devices, device_payload, device_from_payload
from reliability.records.validation import validate_replacement_batch
from reliability.records.requests import canonical_request, check_replay
from reliability.archive import queries
from reliability.archive.transactions import transaction


@dataclass
class ApplyReceipt:
    request_id: str
    revision: int
    device_ids: list


class RecordService:
    def __init__(self, archive):
        self.archive = archive

    @property
    def revision(self):
        return queries.latest_revision(self.archive.connection)

    def apply(self, request_id, device_intervals):
        devices = normalise_devices(device_intervals)
        validate_replacement_batch(devices)
        identity = canonical_request(request_id, devices)
        connection = self.archive.connection
        with transaction(connection):
            replay = check_replay(identity, queries.read_request_row(connection, request_id))
            if replay is None:
                revision = queries.commit_revision_rows(
                    connection, request_id, identity.canonical,
                    {k: device_payload(v) for k, v in devices.items()})
            else:
                revision = replay
        return ApplyReceipt(request_id, revision, list(devices))

    def get_revision(self, revision):
        return {k: device_from_payload(v) for k, v in
                queries.read_revision_rows(self.archive.connection, revision).items()}
