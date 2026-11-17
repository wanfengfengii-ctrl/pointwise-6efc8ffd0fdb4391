from reliability.records.devices import identifier


def select_revision_devices(records, revision, device_ids):
    devices = records.get_revision(revision)
    if isinstance(device_ids, (str, bytes)):
        raise ValueError('selection must be an iterable of IDs')
    try:
        selected = sorted({identifier(key) for key in device_ids})
    except TypeError as exc:
        raise ValueError('selection must be an iterable of IDs') from exc
    for key in selected:
        if key not in devices:
            raise KeyError(key)
    return tuple(devices[key] for key in selected)
