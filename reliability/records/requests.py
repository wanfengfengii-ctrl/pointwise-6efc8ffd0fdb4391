from dataclasses import dataclass
from reliability.records.devices import device_payload, identifier
from reliability.archive.codec import canonical_bytes


@dataclass(frozen=True)
class RequestIdentity:
    request_id: str
    canonical: bytes


def canonical_request(request_id, devices):
    identifier(request_id)
    payload = {key: device_payload(value) for key, value in devices.items()}
    return RequestIdentity(request_id, canonical_bytes(payload))


def check_replay(identity, stored):
    if stored is None:
        return None
    if identity.canonical != stored['canonical']:
        raise ValueError('request ID conflicts with committed content')
    return stored['revision']
