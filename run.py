import argparse
import json
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from reliability.archive.store import Archive
from reliability.records.revisions import RecordService
from reliability.cohorts.snapshots import CohortService
from reliability.analysis.describe import DescriptionService
from reliability.reports.publish import ReportPublisher
from reliability.reports.read import ReportReader
from reliability.reports.compare import ReportComparator

ROOT = Path(__file__).resolve().parent


def _json_fraction(value):
    if type(value) is int:
        return value
    if (type(value) is list and len(value) == 2
            and all(type(x) is int for x in value) and value[1] != 0):
        return Fraction(value[0], value[1])
    raise ValueError('JSON number must be integer or [numerator, nonzero denominator]')


def decode_submission(value):
    if type(value) is not dict or set(value) != {'request_id', 'device_intervals'}:
        raise ValueError('invalid submission fields')
    devices = value['device_intervals']
    if type(devices) is not dict:
        raise ValueError('device_intervals must be object')
    result = {}
    for key, member in devices.items():
        if type(member) is not dict or set(member) != {'batch_id', 'stratum', 'intervals'}:
            raise ValueError('invalid device fields')
        if type(member['intervals']) is not list:
            raise ValueError('intervals must be array')
        intervals = []
        for row in member['intervals']:
            if type(row) is not dict or set(row) != {'start', 'stop', 'load', 'failed'}:
                raise ValueError('invalid interval fields')
            intervals.append(dict(
                start=_json_fraction(row['start']), stop=_json_fraction(row['stop']),
                load=_json_fraction(row['load']), failed=row['failed']))
        result[key] = dict(batch_id=member['batch_id'], stratum=member['stratum'],
                           intervals=intervals)
    return value['request_id'], result


def _display(value):
    if isinstance(value, Fraction):
        return [value.numerator, value.denominator]
    raise TypeError(type(value).__name__)


def demo(path):
    if str(path) == ':memory:':
        raise ValueError('demo requires a file-backed archive for reopen')
    with Archive.open(path) as archive:
        records, cohorts = RecordService(archive), CohortService(archive)
        analysis = DescriptionService(archive)
        publisher, reader = ReportPublisher(archive), ReportReader(archive)
        comparator = ReportComparator(archive)
        raw = json.loads((ROOT / 'examples/daily.json').read_text(encoding='utf-8'))
        request_id, values = decode_submission(raw)
        receipt = records.apply(request_id, values)
        old_cid = cohorts.freeze(receipt.revision, values)['cohort_id']
        expected = [
            dict(stratum='alpha', person_time=Fraction(3), load_exposure=Fraction(11),
                 failures=1, rate=Fraction(1, 3)),
            dict(stratum='beta', person_time=Fraction(2), load_exposure=Fraction(4),
                 failures=0, rate=Fraction(0))]
        actual = analysis.describe(old_cid).strata
        assert actual == expected
        old_id = publisher.publish(old_cid)
        downstream = reader.read(old_id)['strata']
        assert downstream == expected
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v1', 'input': raw, 'expected': expected, 'actual': actual,
            'downstream_expected': expected, 'downstream_actual': downstream,
            'code_paths': ['reliability/records/revisions.py',
                           'reliability/cohorts/snapshots.py',
                           'reliability/cohorts/compile.py',
                           'reliability/analysis/exposure.py',
                           'reliability/analysis/failures.py',
                           'reliability/analysis/describe.py',
                           'reliability/reports/publish.py',
                           'reliability/reports/read.py'],
            'oracle': 'Hand sums: alpha time=2+1, exposure=2*3+1*5; beta time=2, exposure=2*2.'
        }, default=_display, ensure_ascii=False, sort_keys=True))
        correction = json.loads(
            (ROOT / 'examples/correction.json').read_text(encoding='utf-8'))
        request_id, changes = decode_submission(correction)
        new_receipt = records.apply(request_id, changes)
        new_cid = cohorts.freeze(new_receipt.revision, values)['cohort_id']
        new_id = publisher.publish(new_cid)
        difference = comparator.compare(old_id, new_id)['strata']
        expected_difference = [
            dict(stratum='alpha', person_time=Fraction(-3), load_exposure=Fraction(-11), failures=-1),
            dict(stratum='beta', person_time=Fraction(0), load_exposure=Fraction(0), failures=0),
            dict(stratum='gamma', person_time=Fraction(2), load_exposure=Fraction(6), failures=0)]
        assert difference == expected_difference
        assert reader.read(old_id)['strata'] == expected
    with Archive.open(path) as archive:
        restored = ReportReader(archive).read(old_id)
        assert restored['strata'] == expected
        assert restored['members'][0]['batch_id'] == 'lot1'
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v6.frozen_source_binding', 'input': correction,
            'expected': expected_difference, 'actual': difference,
            'downstream_expected': expected, 'downstream_actual': restored['strata'],
            'code_paths': ['reliability/records/requests.py',
                           'reliability/cohorts/members.py',
                           'reliability/cohorts/snapshots.py',
                           'reliability/reports/compare.py',
                           'reliability/reports/read.py',
                           'reliability/archive/codec.py',
                           'reliability/archive/queries.py'],
            'oracle': 'Right-minus-left independent layer union; old alpha exposure remains 11 after reopen.'
        }, default=_display, ensure_ascii=False, sort_keys=True))
    return 0


def verify(names):
    sys.path.insert(0, str(ROOT / 'tests'))
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(names) if names
             else loader.discover(str(ROOT / 'tests'), pattern='test_*.py'))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='Northshore reliability archive')
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('verify')
    check.add_argument('names', nargs='*')
    example = commands.add_parser('demo')
    example.add_argument('--db', required=True)
    args = parser.parse_args(argv)
    if args.command == 'verify':
        return verify(args.names)
    return demo(args.db)


if __name__ == '__main__':
    raise SystemExit(main())
