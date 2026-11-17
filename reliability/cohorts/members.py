from dataclasses import dataclass
from reliability.records.devices import device_payload, device_from_payload


@dataclass(frozen=True)
class FrozenMember:
    device_id: str
    batch_id: str
    stratum: str
    intervals: tuple


def freeze_member(device):
    return member_from_payload(device_payload(device))


def member_payload(member):
    return device_payload(member)


def member_from_payload(payload):
    device = device_from_payload(payload)
    return FrozenMember(device.device_id, device.batch_id, device.stratum, device.intervals)


def member_summary(member):
    return {'device_id': member.device_id, 'batch_id': member.batch_id,
            'stratum': member.stratum,
            'intervals': [dict(row) for row in member_payload(member)['intervals']]}
