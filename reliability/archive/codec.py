import json
import math
from fractions import Fraction


def _pack(value):
    if value is None:
        return ['none']
    if type(value) is bool:
        return ['bool', value]
    if type(value) is int:
        return ['int', value]
    if type(value) is float:
        return ['float', value]
    if isinstance(value, Fraction):
        return ['fraction', value.numerator, value.denominator]
    if type(value) is str:
        return ['str', value]
    if type(value) in (list, tuple):
        return ['tuple' if type(value) is tuple else 'list',
                [_pack(item) for item in value]]
    if type(value) is dict and all(type(k) is str for k in value):
        return ['dict', [[k, _pack(value[k])] for k in sorted(value)]]
    raise ValueError('unsupported archive value')


def _unpack(node):
    if type(node) is not list or not node:
        raise ValueError('invalid typed value')
    tag = node[0]
    if tag == 'none' and len(node) == 1:
        return None
    if tag in ('bool', 'int', 'str') and len(node) == 2:
        expected = {'bool': bool, 'int': int, 'str': str}[tag]
        if type(node[1]) is expected:
            return node[1]
    if tag == 'float' and len(node) == 2:
        if type(node[1]) is float and math.isfinite(node[1]):
            return node[1]
    if tag == 'fraction' and len(node) == 3:
        n, d = node[1:]
        if type(n) is int and type(d) is int and d > 0:
            value = Fraction(n, d)
            if (value.numerator, value.denominator) == (n, d):
                return value
    if tag in ('list', 'tuple') and len(node) == 2 and type(node[1]) is list:
        items = [_unpack(item) for item in node[1]]
        return tuple(items) if tag == 'tuple' else items
    if tag == 'dict' and len(node) == 2 and type(node[1]) is list:
        result = {}
        for pair in node[1]:
            if (type(pair) is not list or len(pair) != 2
                    or type(pair[0]) is not str or pair[0] in result):
                raise ValueError('invalid dictionary')
            result[pair[0]] = _unpack(pair[1])
        return result
    raise ValueError('invalid typed value')


def encode_value(value):
    return json.dumps(_pack(value), ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def decode_value(text):
    try:
        return _unpack(json.loads(text))
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid archive encoding') from exc


def canonical_bytes(value):
    return encode_value(value).encode('utf-8')
