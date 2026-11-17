import math
from reliability.archive.codec import encode_value, decode_value

COX_BASIS = 'stratified-efron-batch-v1'

_FIELDS = frozenset((
    'format_version', 'basis', 'plan_id', 'cohort_id', 'revision', 'p',
    'status', 'beta', 'log_likelihood', 'information', 'batch_scores',
    'covariance'))


def _is_finite_matrix(value, p):
    return (type(value) is list and len(value) == p
            and all(type(row) is list and len(row) == p
                    and all(type(cell) is float and math.isfinite(cell)
                            for cell in row) for row in value))


def _validate(payload):
    if type(payload) is not dict or set(payload) != _FIELDS:
        raise ValueError('invalid cox report fields')
    if payload['format_version'] != 1 or payload['basis'] != COX_BASIS:
        raise ValueError('unsupported cox report format')
    for name in ('plan_id', 'cohort_id', 'revision', 'p'):
        if type(payload[name]) is not int or payload[name] < 0:
            raise ValueError('invalid cox report binding')
    if payload['p'] not in (0, 1, 2):
        raise ValueError('invalid cox dimension')
    if type(payload['status']) is not str:
        raise ValueError('invalid cox status')
    p = payload['p']
    if payload['status'] == 'no_events':
        if (payload['beta'] is not None or payload['information'] is not None
                or payload['covariance'] is not None
                or payload['batch_scores'] != []
                or payload['log_likelihood'] != 0.0):
            raise ValueError('invalid no_events cox report')
        return
    if payload['status'] != 'ok' or p == 0:
        raise ValueError('invalid cox status')
    beta, likelihood = payload['beta'], payload['log_likelihood']
    if (type(beta) is not list or len(beta) != p
            or not all(type(v) is float and math.isfinite(v) for v in beta)):
        raise ValueError('invalid cox beta')
    if type(likelihood) is not float or not math.isfinite(likelihood):
        raise ValueError('invalid cox log likelihood')
    if not _is_finite_matrix(payload['information'], p) \
            or not _is_finite_matrix(payload['covariance'], p):
        raise ValueError('invalid cox matrices')
    scores = payload['batch_scores']
    if type(scores) is not list:
        raise ValueError('invalid batch scores')
    names = []
    for row in scores:
        if type(row) is not dict or set(row) != {'batch_id', 'score'}:
            raise ValueError('invalid batch score row')
        if type(row['batch_id']) is not str or not row['batch_id']:
            raise ValueError('invalid batch identity')
        if (type(row['score']) is not list or len(row['score']) != p
                or not all(type(v) is float and math.isfinite(v)
                           for v in row['score'])):
            raise ValueError('invalid batch score vector')
        names.append(row['batch_id'])
    if names != sorted(set(names)):
        raise ValueError('batch scores must be unique and sorted')


def content_from_fit(plan, status, beta, log_likelihood, information,
                     batch_scores, covariance):
    payload = {
        'format_version': 1, 'basis': COX_BASIS,
        'plan_id': plan['plan_id'], 'cohort_id': plan['cohort_id'],
        'revision': plan['revision'], 'p': plan['p'], 'status': status,
        'beta': beta, 'log_likelihood': log_likelihood,
        'information': information, 'batch_scores': batch_scores,
        'covariance': covariance}
    return decode_cox_content(encode_value(payload))


def encode_cox_content(content):
    payload = dict(content)
    _validate(payload)
    return encode_value(payload)


def decode_cox_content(text):
    payload = decode_value(text)
    _validate(payload)
    return payload
