from dataclasses import dataclass
from collections.abc import Mapping
from reliability.records.intervals import (
    normalise_intervals, interval_payload, interval_from_payload,
)


@dataclass(frozen=True)
class DeviceRevision:
    device_id: str
    batch_id: str
    stratum: str
    intervals: tuple


def identifier(value):
    if type(value) is not str or not value:
        raise ValueError('identifier must be a nonempty string')
    return value


def normalise_devices(values):
    if not isinstance(values, Mapping):
        raise ValueError('devices must be a mapping')
    result = {}
    for device_id, item in values.items():
        identifier(device_id)
        if not isinstance(item, Mapping) or set(item) != {'batch_id', 'stratum', 'intervals'}:
            raise ValueError('device fields required: batch_id, stratum, intervals')
        result[device_id] = DeviceRevision(
            device_id, identifier(item['batch_id']), identifier(item['stratum']),
            normalise_intervals(item['intervals']))
    return {key: result[key] for key in sorted(result)}


def device_payload(device):
    return {'device_id': device.device_id, 'batch_id': device.batch_id,
            'stratum': device.stratum,
            'intervals': [interval_payload(x) for x in device.intervals]}


def device_from_payload(payload):
    return DeviceRevision(identifier(payload['device_id']),
                          identifier(payload['batch_id']),
                          identifier(payload['stratum']),
                          tuple(interval_from_payload(x) for x in payload['intervals']))
