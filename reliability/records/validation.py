def validate_device_timeline(device):
    previous_stop = None
    failure_seen = False
    for interval in device.intervals:
        if interval.start >= interval.stop:
            raise ValueError('interval must have positive length')
        if previous_stop is not None and interval.start < previous_stop:
            raise ValueError('overlapping device intervals')
        if failure_seen:
            raise ValueError('records after terminal failure')
        failure_seen = interval.failed
        previous_stop = interval.stop


def validate_replacement_batch(devices):
    for device_id, device in devices.items():
        if device_id != device.device_id:
            raise ValueError('device identity mismatch')
        validate_device_timeline(device)
