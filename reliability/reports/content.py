from dataclasses import dataclass
from fractions import Fraction
from reliability.archive.codec import encode_value, decode_value

REPORT_BASIS = 'descriptive-hours-v1'


@dataclass(frozen=True)
class ReportContent:
    payload: dict

    def copy(self):
        return decode_value(encode_value(self.payload))


def _validate(payload):
    if type(payload) is not dict or set(payload) != {
            'format_version', 'basis', 'cohort_id', 'revision', 'members', 'strata'}:
        raise ValueError('invalid report fields')
    if type(payload['format_version']) is not int or payload['format_version'] != 1:
        raise ValueError('unsupported report format')
    for name in ('cohort_id', 'revision'):
        if type(payload[name]) is not int or payload[name] < 0:
            raise ValueError('invalid report binding')
    if type(payload['basis']) is not str or not payload['basis']:
        raise ValueError('invalid report basis')
    if type(payload['members']) is not list or type(payload['strata']) is not list:
        raise ValueError('invalid report collections')
    names = []
    for row in payload['strata']:
        if type(row) is not dict or set(row) != {
                'stratum', 'person_time', 'load_exposure', 'failures', 'rate'}:
            raise ValueError('invalid report stratum')
        if type(row['stratum']) is not str or not row['stratum']:
            raise ValueError('invalid stratum identity')
        names.append(row['stratum'])
        if (not isinstance(row['person_time'], Fraction)
                or not isinstance(row['load_exposure'], Fraction)
                or type(row['failures']) is not int
                or row['person_time'] < 0 or row['failures'] < 0):
            raise ValueError('invalid exact totals')
        rate = row['rate']
        if row['person_time'] == 0:
            if row['failures'] or rate is not None:
                raise ValueError('invalid zero-time semantics')
        elif not isinstance(rate, Fraction) or rate != row['failures'] / row['person_time']:
            raise ValueError('inconsistent stored rate')
    if names != sorted(set(names)):
        raise ValueError('strata must be unique and sorted')


def content_from_result(result):
    payload = {'format_version': 1, 'basis': REPORT_BASIS,
               'cohort_id': result.cohort_id, 'revision': result.revision,
               'members': result.members, 'strata': result.strata}
    return decode_report_content(encode_value(payload))


def encode_report_content(content):
    payload = content.copy()
    _validate(payload)
    return encode_value(payload)


def decode_report_content(text):
    payload = decode_value(text)
    _validate(payload)
    return ReportContent(payload)
