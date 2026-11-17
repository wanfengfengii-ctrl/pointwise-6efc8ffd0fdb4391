"""Public input fixtures and hand-computed expectations; no V2 implementation."""
from copy import deepcopy
from fractions import Fraction as F
import json


def _segment(start, stop, x, failed=False):
    return dict(start=F(start), stop=F(stop), load=F(1),
                failed=failed, x=[F(v) for v in x])


def _device(batch, stratum, x, failed):
    return dict(batch_id=batch, stratum=stratum,
                intervals=[_segment(0, 1 if failed else 2, x, failed)])


def tied_case():
    return {
        "a0": _device("h", "alpha", [0], True),
        "a1": _device("g", "alpha", [1], True),
        "a2": _device("h", "alpha", [0], False),
        "a3": _device("h", "alpha", [0], False),
        "b0": _device("h", "beta", [0], True),
        "b1": _device("g", "beta", [1], True),
        "b2": _device("g", "beta", [1], False),
        "b3": _device("g", "beta", [1], False),
    }


def split_tied_case():
    values = tied_case()
    values["a2"]["intervals"] = [
        _segment(0, 1, [0]), _segment(1, 2, [0])]
    return values


def vector_case():
    values = {}
    for prefix, stratum in (("a", "alpha"), ("b", "beta")):
        for suffix, batch, x, failed in (
                ("0", "g", [1, 0], True),
                ("1", "h", [-1, 0], True),
                ("2", "g", [0, 1], False),
                ("3", "h", [0, -1], False)):
            values[prefix + suffix] = _device(batch, stratum, x, failed)
    return values


def boundary_case():
    return {
        "A": dict(batch_id="g", stratum="s",
                  intervals=[_segment(0, 2, [1], True)]),
        "B": dict(batch_id="g", stratum="s",
                  intervals=[_segment(2, 4, [2])]),
        "C": dict(batch_id="h", stratum="s",
                  intervals=[_segment(0, 2, [3])]),
    }


def correction():
    values = deepcopy(tied_case())
    values["a1"]["batch_id"] = "later-batch"
    values["a1"]["intervals"][0]["x"] = [F(1, 2)]
    return {"a1": values["a1"]}


TIED_EXPECTED = {
    "status": "ok", "beta": [F(0)],
    "log_likelihood": "-2*log(12)",
    "information": [[F(47, 72)]],
    "batch_scores": [
        {"batch_id": "g", "score": [F(25, 72)]},
        {"batch_id": "h", "score": [F(-25, 72)]}],
    "covariance": [[F(1250, 2209)]],
}

VECTOR_EXPECTED = {
    "status": "ok", "beta": [F(0), F(0)],
    "log_likelihood": "-2*log(12)",
    "information": [[F(5, 3), F(0)], [F(0), F(7, 3)]],
    "batch_scores": [
        {"batch_id": "g", "score": [F(7, 6), F(-7, 6)]},
        {"batch_id": "h", "score": [F(-7, 6), F(7, 6)]}],
    "covariance": [[F(49, 50), F(-7, 10)], [F(-7, 10), F(1, 2)]],
}


def _display(value):
    if isinstance(value, F):
        return [value.numerator, value.denominator]
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    print(json.dumps({
        "tied": {"input": tied_case(), "expected": TIED_EXPECTED},
        "vector": {"input": vector_case(), "expected": VECTOR_EXPECTED},
        "boundary_compile_only": {
            "input": boundary_case(),
            "expected_event": {"stratum": "s", "time": F(2),
                               "risk_ids": ["A", "C"], "deaths": ["A"]}},
        "split_input": split_tied_case(),
        "later_replacement": correction(),
    }, default=_display, ensure_ascii=False, sort_keys=True))
