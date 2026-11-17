"""Stratified Efron partial-likelihood engine with batch-cluster scores.

Plans are exact (Fraction); fitting converts the fixed covariate coordinates
to IEEE-754 float and never re-reads source devices.

Per event with m simultaneous deaths and risk set R, let
    S_k = sum_{i in R}      w_i x_i^[k],   D_k = sum_{i in deaths} w_i x_i^[k],
where x_i^[0] = 1 and w_i = exp(x_i.beta), and A_k(l) = S_k - (l/m) D_k.
The Efron log term is log A_0(l) plus the stability shift.

For a batch g, B_k/C_k restrict S_k/D_k to members of g.  The mixed
derivative d/d w_g of the weighted beta-score (weighted Efron objective
in COX.md) at all w=1 is, with q(l) = A_1(l)/A_0(l),

    C_1 + sum_l [ -(C_0/m) q(l)
                  -(D_0/m)( (B_1-(l/m) C_1)/A_0(l)
                            - q(l) (B_0-(l/m) C_0)/A_0(l) ) ].

This is validated against independent finite differences of the weighted
objective (see audit/cox_audit.py).
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class _Event:
    stratum: object
    time: object
    x: tuple
    batches: tuple
    death_index: tuple


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _matrix_add(left, right, sign=1.0):
    return [[a + sign * b for a, b in zip(lrow, rrow)]
            for lrow, rrow in zip(left, right)]


def _symmetrize(matrix):
    n = len(matrix)
    return [[0.5 * (matrix[i][j] + matrix[j][i]) for j in range(n)]
            for i in range(n)]


def _solve(matrix, vector):
    """Gaussian elimination with partial pivoting; A is positive definite."""
    n = len(vector)
    a = [list(row) for row in matrix]
    b = list(vector)
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(a[row][column]))
        if abs(a[pivot][column]) <= 1e-14:
            raise ValueError('singular information matrix')
        if pivot != column:
            a[column], a[pivot] = a[pivot], a[column]
            b[column], b[pivot] = b[pivot], b[column]
        pivot_value = a[column][column]
        for row in range(column + 1, n):
            factor = a[row][column] / pivot_value
            if factor:
                a[row][column] = 0.0
                for k in range(column + 1, n):
                    a[row][k] -= factor * a[column][k]
                b[row] -= factor * b[column]
    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        remainder = sum(a[row][k] * solution[k] for k in range(row + 1, n))
        solution[row] = (b[row] - remainder) / a[row][row]
    return solution


def prepare_events(plan):
    events = []
    for event in plan['events']:
        x = tuple(tuple(float(component) for component in row['x'])
                  for row in event['risk'])
        batches = tuple(row['batch_id'] for row in event['risk'])
        order = {row['device_id']: position
                 for position, row in enumerate(event['risk'])}
        death_index = tuple(order[device] for device in event['deaths'])
        events.append(_Event(event['stratum'], event['time'], x, batches,
                             death_index))
    return tuple(events)


def _moments(indices, weight, x, p):
    m0 = 0.0
    m1 = [0.0] * p
    m2 = [[0.0] * p for _ in range(p)]
    for i in indices:
        w, row = weight[i], x[i]
        m0 += w
        for j, value in enumerate(row):
            m1[j] += w * value
            for k in range(p):
                m2[j][k] += w * value * row[k]
    return m0, m1, m2


def _quantities(event, beta):
    x, p = event.x, len(beta)
    eta = [_dot(row, beta) for row in x]
    shift = max(eta)
    weight = [math.exp(value - shift) for value in eta]
    s0, s1, s2 = _moments(range(len(x)), weight, x, p)
    d0, d1, d2 = _moments(event.death_index, weight, x, p)
    death_eta = sum(eta[i] for i in event.death_index)
    return (x, p, weight, shift, s0, s1, s2, d0, d1, d2, death_eta)


def evaluate_event(event, beta):
    (x, p, weight, shift, s0, s1, s2, d0, d1, d2,
     death_eta) = _quantities(event, beta)
    m = len(event.death_index)
    log_likelihood = death_eta - m * shift
    gradient = [0.0] * p
    information = [[0.0] * p for _ in range(p)]
    for l in range(m):
        a0 = s0 - (l / m) * d0
        a1 = [s1[j] - (l / m) * d1[j] for j in range(p)]
        a2 = [[s2[j][k] - (l / m) * d2[j][k] for k in range(p)]
              for j in range(p)]
        log_likelihood -= math.log(a0)
        mean = [value / a0 for value in a1]
        for j in range(p):
            gradient[j] -= a1[j] / a0
            for k in range(p):
                information[j][k] += a2[j][k] / a0 - mean[j] * mean[k]
    for i in event.death_index:
        for j, value in enumerate(x[i]):
            gradient[j] += value
    return log_likelihood, gradient, _symmetrize(information)


def objective(events, beta):
    p = len(beta)
    log_likelihood = 0.0
    gradient = [0.0] * p
    information = [[0.0] * p for _ in range(p)]
    for event in events:
        part, grad, info = evaluate_event(event, beta)
        log_likelihood += part
        gradient = [a + b for a, b in zip(gradient, grad)]
        information = _matrix_add(information, info)
    return log_likelihood, gradient, _symmetrize(information)


def fit_beta(events, p):
    beta = [0.0] * p
    best = objective(events, beta)
    if not all(math.isfinite(v) for v in best[1]):
        raise ValueError('non-finite Cox objective')
    for _ in range(64):
        log_likelihood, gradient, information = best
        if max((abs(v) for v in gradient), default=0.0) <= 1e-11:
            break
        direction = _solve(information, gradient)
        trial_beta = [b + d for b, d in zip(beta, direction)]
        trial = objective(events, trial_beta)
        if not all(math.isfinite(v) for v in trial[1]):
            raise ValueError('non-finite Cox objective')
        scale = 1.0
        while trial[0] < log_likelihood - 1e-12 and scale > 1e-4:
            scale *= 0.5
            trial_beta = [b + scale * d for b, d in zip(beta, direction)]
            trial = objective(events, trial_beta)
        beta, best = trial_beta, trial
        if max((abs(scale * d) for d in direction), default=0.0) <= 1e-12:
            break
    else:
        raise ValueError('Cox optimisation did not converge')
    log_likelihood, gradient, information = best
    if max((abs(v) for v in gradient), default=0.0) > 1e-8:
        raise ValueError('Cox optimisation did not converge')
    return beta, log_likelihood, _symmetrize(information)


def event_batch_scores(event, beta, batch_ids):
    """Mixed derivative contributions of one event for every batch."""
    (x, p, weight, shift, s0, s1, s2, d0, d1, d2,
     death_eta) = _quantities(event, beta)
    m = len(event.death_index)
    risk_batches = set(event.batches)

    per_l = []
    for l in range(m):
        a0 = s0 - (l / m) * d0
        a1 = [s1[j] - (l / m) * d1[j] for j in range(p)]
        q = [value / a0 for value in a1]
        per_l.append((a0, a1, q))

    result = {batch: [0.0] * p for batch in batch_ids}
    for batch in risk_batches:
        members = tuple(i for i, owner in enumerate(event.batches)
                        if owner == batch)
        b0, b1, _ = _moments(members, weight, x, p)
        deaths = tuple(i for i in event.death_index
                       if event.batches[i] == batch)
        c0, c1, _ = _moments(deaths, weight, x, p)
        score = result[batch]
        for j in range(p):
            score[j] += c1[j]
        for l, (a0, a1, q) in enumerate(per_l):
            alpha0 = b0 - (l / m) * c0
            for j in range(p):
                alpha1 = b1[j] - (l / m) * c1[j]
                score[j] -= (c0 / m) * q[j]
                score[j] -= (d0 / m) * (alpha1 / a0 - q[j] * alpha0 / a0)
    return [result[batch] for batch in batch_ids]


def batch_scores(events, beta, batch_ids):
    p = len(beta)
    totals = {batch: [0.0] * p for batch in batch_ids}
    for event in events:
        contributions = event_batch_scores(event, beta, batch_ids)
        for batch, contribution in zip(batch_ids, contributions):
            target = totals[batch]
            for j in range(p):
                target[j] += contribution[j]
    return [totals[batch] for batch in batch_ids]


def covariance(information, scores):
    """H^-1 (sum_g U_g U_g^T) H^-1 without any degrees-of-freedom correction."""
    p = len(information)
    meat = [[0.0] * p for _ in range(p)]
    for score in scores:
        for j in range(p):
            for k in range(p):
                meat[j][k] += score[j] * score[k]
    inverse_rows = [_solve(information, [1.0 if j == k else 0.0 for k in range(p)])
                    for j in range(p)]
    middle = [[sum(inverse_rows[i][j] * meat[j][k] for j in range(p))
               for k in range(p)] for i in range(p)]
    # H is symmetric, so H^-1 is symmetric: final product uses H^-1 on both sides.
    return [[sum(middle[i][j] * inverse_rows[k][j] for j in range(p))
             for k in range(p)] for i in range(p)]
