"""Independent re-accounting of the stratified Efron Cox contract.

This module deliberately imports nothing from ``reliability``.  It rebuilds
risk sets directly from the archived member intervals and evaluates the
contract formulas with :class:`decimal.Decimal` high-precision arithmetic,
including an independent Newton solver and independent linear algebra.
Production outputs are only compared against these numbers; the production
objective is never used as its own oracle.
"""
from decimal import Decimal, getcontext

getcontext().prec = 60

_D = Decimal
_ZERO = _D(0)
_ONE = _D(1)
_TWO = _D(2)


def _exp(value):
    return value.exp()


def _log(value):
    return value.ln()


def _fraction_to_decimal(value):
    return _D(value.numerator) / _D(value.denominator)


def build_events(members):
    """Risk sets from exact (start, stop] intervals, independently of plans."""
    death_times = {}
    for member in members:
        for interval in member['intervals']:
            if interval['failed']:
                death_times.setdefault(
                    (member['stratum'], interval['stop']), set())
    events = []
    for stratum, time in sorted(death_times):
        risk, deaths = [], []
        for member in members:
            if member['stratum'] != stratum:
                continue
            cover = None
            for interval in member['intervals']:
                if interval['start'] < time <= interval['stop']:
                    if cover is not None:
                        raise ValueError('overlapping audit membership')
                    cover = interval
            if cover is None:
                continue
            risk.append({'device_id': member['device_id'],
                         'batch_id': member['batch_id'],
                         'x': tuple(_fraction_to_decimal(v) for v in cover['x'])})
            if cover['failed'] and cover['stop'] == time:
                deaths.append(member['device_id'])
        risk.sort(key=lambda row: row['device_id'])
        deaths.sort()
        events.append({'stratum': stratum, 'time': time,
                       'risk': risk, 'deaths': deaths})
    return events


def _solve(matrix, vector):
    n = len(vector)
    a = [list(row) for row in matrix]
    b = list(vector)
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(a[row][column]))
        if abs(a[pivot][column]) == 0:
            raise ValueError('singular audit matrix')
        if pivot != column:
            a[column], a[pivot] = a[pivot], a[column]
            b[column], b[pivot] = b[pivot], b[column]
        pivot_value = a[column][column]
        for row in range(column + 1, n):
            factor = a[row][column] / pivot_value
            for k in range(column, n):
                a[row][k] -= factor * a[column][k]
            b[row] -= factor * b[column]
    out = [_ZERO] * n
    for row in range(n - 1, -1, -1):
        out[row] = (b[row] - sum(a[row][k] * out[k]
                                 for k in range(row + 1, n))) / a[row][row]
    return out


def _inverse(matrix):
    n = len(matrix)
    columns = [_solve(matrix, [_ONE if j == k else _ZERO for k in range(n)])
               for j in range(n)]
    return [[columns[j][i] for j in range(n)] for i in range(n)]


def _event_objective(event, beta):
    xs = [row['x'] for row in event['risk']]
    p = len(beta)
    eta = [sum(a * b for a, b in zip(row, beta)) for row in xs]
    shift = max(eta)
    weight = [_exp(value - shift) for value in eta]
    death_pos = [next(i for i, row in enumerate(event['risk'])
                      if row['device_id'] == device)
                 for device in event['deaths']]
    m = len(death_pos)
    s0 = sum(weight)
    s1 = [sum(weight[i] * xs[i][j] for i in range(len(xs))) for j in range(p)]
    s2 = [[sum(weight[i] * xs[i][j] * xs[i][k] for i in range(len(xs)))
           for k in range(p)] for j in range(p)]
    d0 = sum(weight[i] for i in death_pos)
    d1 = [sum(weight[i] * xs[i][j] for i in death_pos) for j in range(p)]
    d2 = [[sum(weight[i] * xs[i][j] * xs[i][k] for i in death_pos)
           for k in range(p)] for j in range(p)]
    ll = sum(eta[i] for i in death_pos) - _D(m) * shift
    grad = [_ZERO] * p
    info = [[_ZERO] * p for _ in range(p)]
    for l in range(m):
        a0 = s0 - _D(l) / _D(m) * d0
        a1 = [s1[j] - _D(l) / _D(m) * d1[j] for j in range(p)]
        a2 = [[s2[j][k] - _D(l) / _D(m) * d2[j][k] for k in range(p)]
              for j in range(p)]
        ll -= _log(a0)
        mean = [value / a0 for value in a1]
        for j in range(p):
            grad[j] -= a1[j] / a0
            for k in range(p):
                info[j][k] += a2[j][k] / a0 - mean[j] * mean[k]
    for i in death_pos:
        for j in range(p):
            grad[j] += xs[i][j]
    return ll, grad, info, weight, death_pos


def fit(events, p):
    beta = [_ZERO] * p
    for _ in range(100):
        ll = _ZERO
        grad = [_ZERO] * p
        info = [[_ZERO] * p for _ in range(p)]
        for event in events:
            part, g, h, _, _ = _event_objective(event, beta)
            ll += part
            grad = [a + b for a, b in zip(grad, g)]
            info = [[a + b for a, b in zip(ri, rh)]
                    for ri, rh in zip(info, h)]
        if max((abs(v) for v in grad), default=_ZERO) < _D('1e-40'):
            return beta, ll, info
        direction = _solve(info, grad)
        beta = [a + b for a, b in zip(beta, direction)]
    raise ValueError('audit solver did not converge')


def batch_scores(events, beta, batch_ids):
    p = len(beta)
    totals = {batch: [_ZERO] * p for batch in batch_ids}
    for event in events:
        _, _, _, weight, death_pos = _event_objective(event, beta)
        xs = [row['x'] for row in event['risk']]
        owners = [row['batch_id'] for row in event['risk']]
        m = len(death_pos)
        s0 = sum(weight)
        s1 = [sum(weight[i] * xs[i][j] for i in range(len(xs)))
              for j in range(p)]
        d0 = sum(weight[i] for i in death_pos)
        d1 = [sum(weight[i] * xs[i][j] for i in death_pos) for j in range(p)]
        per_l = []
        for l in range(m):
            a0 = s0 - _D(l) / _D(m) * d0
            a1 = [s1[j] - _D(l) / _D(m) * d1[j] for j in range(p)]
            per_l.append((a0, [v / a0 for v in a1]))
        for batch in set(owners):
            members = [i for i, owner in enumerate(owners) if owner == batch]
            b0 = sum(weight[i] for i in members)
            b1 = [sum(weight[i] * xs[i][j] for i in members) for j in range(p)]
            deaths = [i for i in death_pos if owners[i] == batch]
            c0 = sum(weight[i] for i in deaths)
            c1 = [sum(weight[i] * xs[i][j] for i in deaths) for j in range(p)]
            score = totals[batch]
            for j in range(p):
                score[j] += c1[j]
            for l, (a0, q) in enumerate(per_l):
                alpha0 = b0 - _D(l) / _D(m) * c0
                for j in range(p):
                    alpha1 = b1[j] - _D(l) / _D(m) * c1[j]
                    score[j] -= (c0 / _D(m)) * q[j]
                    score[j] -= (d0 / _D(m)) * (
                        alpha1 / a0 - q[j] * alpha0 / a0)
    return [totals[batch] for batch in batch_ids]


def audit(members):
    """Full independent fit from archived member dictionaries."""
    events = build_events(members)
    if not events:
        return {'status': 'no_events', 'p': _shared_dimension(members)}
    p = len(events[0]['risk'][0]['x'])
    beta, ll, info = fit(events, p)
    batch_ids = sorted({member['batch_id'] for member in members})
    scores = batch_scores(events, beta, batch_ids)
    inverse = _inverse(info)
    meat = [[sum(scores[g][j] * scores[g][k] for g in range(len(batch_ids)))
             for k in range(p)] for j in range(p)]
    middle = [[sum(inverse[i][j] * meat[j][k] for j in range(p))
               for k in range(p)] for i in range(p)]
    covariance = [[sum(middle[i][j] * inverse[k][j] for j in range(p))
                   for k in range(p)] for i in range(p)]
    return {'status': 'ok', 'p': p, 'beta': beta, 'log_likelihood': ll,
            'information': info,
            'batch_scores': [{'batch_id': b, 'score': scores[i]}
                             for i, b in enumerate(batch_ids)],
            'covariance': covariance, 'events': events}


def _shared_dimension(members):
    dimensions = {len(interval['x']) for member in members
                  for interval in member['intervals']}
    return next(iter(dimensions)) if dimensions else 0
