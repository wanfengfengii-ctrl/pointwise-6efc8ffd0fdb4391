from dataclasses import dataclass
from collections.abc import Mapping
from fractions import Fraction

_BASE_FIELDS = frozenset(('start', 'stop', 'load', 'failed'))


@dataclass(frozen=True)
class Interval:
    start: Fraction
    stop: Fraction
    load: Fraction
    failed: bool
    x: object = None


def exact(value):
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    raise ValueError('time and load must be integers or Fraction')


def normalise_covariate(value):
    if type(value) not in (list, tuple):
        raise ValueError('x must be a list or tuple of covariates')
    if not 1 <= len(value) <= 2:
        raise ValueError('x must contain one or two components')
    components = []
    for component in value:
        if type(component) is bool or not (
                type(component) is int or isinstance(component, Fraction)):
            raise ValueError('x components must be integers or Fraction')
        try:
            components.append(Fraction(component))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError('invalid x component') from exc
    return tuple(components)


def normalise_intervals(values):
    if type(values) not in (list, tuple):
        raise ValueError('intervals must be a list or tuple')
    result = []
    for item in values:
        if not isinstance(item, Mapping):
            raise ValueError('interval must be a mapping')
        fields = set(item)
        if fields == _BASE_FIELDS:
            covariate = None
        elif fields == _BASE_FIELDS | {'x'}:
            covariate = normalise_covariate(item['x'])
        else:
            raise ValueError('interval fields required: start, stop, load, failed and optional x')
        if type(item['failed']) is not bool:
            raise ValueError('failed must be bool')
        result.append(Interval(exact(item['start']), exact(item['stop']),
                               exact(item['load']), item['failed'], covariate))
    return tuple(sorted(result, key=lambda z: (z.start, z.stop, z.load, z.failed)))


def interval_payload(interval):
    row = {'start': interval.start, 'stop': interval.stop,
           'load': interval.load, 'failed': interval.failed}
    if interval.x is not None:
        row['x'] = list(interval.x)
    return row


def interval_from_payload(payload):
    return normalise_intervals([payload])[0]
