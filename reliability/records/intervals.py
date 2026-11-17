from dataclasses import dataclass
from collections.abc import Mapping
from fractions import Fraction


@dataclass(frozen=True)
class Interval:
    start: Fraction
    stop: Fraction
    load: Fraction
    failed: bool


def exact(value):
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    raise ValueError('time and load must be integers or Fraction')


def normalise_intervals(values):
    if type(values) not in (list, tuple):
        raise ValueError('intervals must be a list or tuple')
    result = []
    for item in values:
        if not isinstance(item, Mapping) or set(item) != {'start', 'stop', 'load', 'failed'}:
            raise ValueError('interval fields required: start, stop, load, failed')
        if type(item['failed']) is not bool:
            raise ValueError('failed must be bool')
        result.append(Interval(exact(item['start']), exact(item['stop']),
                               exact(item['load']), item['failed']))
    return tuple(sorted(result, key=lambda x: (x.start, x.stop, x.load, x.failed)))


def interval_payload(interval):
    return {'start': interval.start, 'stop': interval.stop,
            'load': interval.load, 'failed': interval.failed}


def interval_from_payload(payload):
    return normalise_intervals([payload])[0]
