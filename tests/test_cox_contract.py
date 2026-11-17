import copy
import sqlite3
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path
from reliability.archive.store import Archive
from reliability.records.revisions import RecordService
from reliability.cohorts.snapshots import CohortService
from reliability.analysis.cox import CoxService
from reliability.reports.read import ReportReader
from reliability.reports.compare import ReportComparator
from reliability.reports.cox_content import COX_BASIS
import cox_examples as ce


def seg(start, stop, x=None, failed=False):
    row = dict(start=F(start), stop=F(stop), load=F(1), failed=failed)
    if x is not None:
        row['x'] = [F(v) for v in x]
    return row


def dev(batch, stratum, intervals):
    return dict(batch_id=batch, stratum=stratum, intervals=intervals)


class CoxCase:
    def setUp(self):
        self.path = getattr(self, 'path', ':memory:')
        self.archive = Archive.open(self.path)
        self.addCleanup(self.archive.close)
        self.records = RecordService(self.archive)
        self.cohorts = CohortService(self.archive)
        self.cox = CoxService(self.archive)
        self.reader = ReportReader(self.archive)
        self.comparator = ReportComparator(self.archive)

    def accept(self, request_id, values):
        receipt = self.records.apply(request_id, values)
        cid = self.cohorts.freeze(receipt.revision, values)['cohort_id']
        return self.cohorts.compile_risk(cid)

    def reopen(self):
        self.archive.close()
        self.archive = Archive.open(self.path)
        self.records = RecordService(self.archive)
        self.cohorts = CohortService(self.archive)
        self.cox = CoxService(self.archive)
        self.reader = ReportReader(self.archive)
        self.comparator = ReportComparator(self.archive)


class TestCoxIntake(CoxCase, unittest.TestCase):
    def test_x_validation_and_identity(self):
        good = {'A': dev('g', 'alpha', [seg(0, 1, [1], True)])}
        receipt = self.records.apply('ok', good)
        stored = self.records.get_revision(receipt.revision)['A']
        self.assertEqual(stored.intervals[0].x, (F(1),))
        # replay with tuple and equal fraction is the same request
        again = copy.deepcopy(good)
        again['A']['intervals'][0]['x'] = [(F(2, 2))]
        self.assertEqual(self.records.apply('ok', again).revision, receipt.revision)
        # changing only x conflicts
        changed = copy.deepcopy(good)
        changed['A']['intervals'][0]['x'] = [2]
        with self.assertRaises(ValueError):
            self.records.apply('ok', changed)
        for index, bad_x in enumerate(([], [1, 2, 3], [0.5], [True], [None])):
            row = dict(start=F(0), stop=F(1), load=F(1), failed=False, x=bad_x)
            with self.assertRaises((ValueError, TypeError)):
                self.records.apply('bad-%d' % index,
                                   {'A': dev('g', 'alpha', [row])})
        # a non-array x is rejected at normalisation
        bad_row = dict(start=F(0), stop=F(1), load=F(1), failed=False, x='x')
        with self.assertRaises(ValueError):
            self.records.apply('bad-string',
                               {'A': dev('g', 'alpha', [bad_row])})

    def test_unknown_interval_field_rejected(self):
        row = seg(0, 1, [1])
        row['extra'] = 2
        with self.assertRaises(ValueError):
            self.records.apply('extra', {'A': dev('g', 'alpha', [row])})

    def test_decode_submission_x(self):
        from run import decode_submission
        submission = {
            'request_id': 'json', 'device_intervals': {
                'A': {'batch_id': 'g', 'stratum': 'alpha', 'intervals': [
                    {'start': 0, 'stop': 1, 'load': 1, 'failed': True,
                     'x': [[1, 2], 3]}]}}}
        _, decoded = decode_submission(submission)
        self.assertEqual(decoded['A']['intervals'][0]['x'], [F(1, 2), F(3)])

    def test_legacy_request_without_x_replays_unchanged(self):
        legacy = {'A': dict(batch_id='g', stratum='alpha',
                            intervals=[dict(start=F(0), stop=F(1),
                                            load=F(1), failed=False)])}
        receipt = self.records.apply('legacy', legacy)
        self.assertIsNone(
            self.records.get_revision(receipt.revision)['A'].intervals[0].x)
        self.assertEqual(self.records.apply('legacy', legacy).revision,
                         receipt.revision)


class TestCoxCompile(CoxCase, unittest.TestCase):
    def test_projection_and_boundary(self):
        values = ce.boundary_case()
        plan = self.accept('boundary', values)
        self.assertEqual(plan['p'], 1)
        event = plan['events'][0]
        self.assertEqual(event['stratum'], 's')
        self.assertEqual(event['time'], F(2))
        self.assertEqual([r['device_id'] for r in event['risk']], ['A', 'C'])
        self.assertEqual(event['deaths'], ['A'])
        self.assertEqual([m['device_id'] for m in plan['members']], ['A', 'B', 'C'])

    def test_ties_kept_as_one_event_and_sorted(self):
        plan = self.accept('tied', ce.tied_case())
        self.assertEqual(len(plan['events']), 2)
        self.assertEqual([(e['stratum'], e['time']) for e in plan['events']],
                         [('alpha', F(1)), ('beta', F(1))])
        self.assertEqual(plan['events'][0]['deaths'], ['a0', 'a1'])

    def test_split_does_not_change_event_membership(self):
        first = self.accept('whole', ce.tied_case())
        second = self.accept('split', ce.split_tied_case())
        self.assertEqual(first['events'], second['events'])

    def test_exact_boundary_adjacent_and_gap_membership(self):
        values = {
            'A': dev('g', 's', [seg(0, 1, [1]), seg(1, 3, [2], True)]),
            'B': dev('h', 's', [seg(0, 1, [3], True)]),
            'C': dev('g', 's', [seg(0, 1, [5]), seg(4, 5, [6])]),
        }
        plan = self.accept('boundaries', values)
        at_one, at_three = plan['events']
        self.assertEqual(at_one['time'], F(1))
        self.assertEqual({r['device_id']: r['x'] for r in at_one['risk']},
                         {'A': [F(1)], 'B': [F(3)], 'C': [F(5)]})
        self.assertEqual(at_one['deaths'], ['B'])
        self.assertEqual(at_three['time'], F(3))
        self.assertEqual([r['device_id'] for r in at_three['risk']], ['A'])
        self.assertEqual(at_three['risk'][0]['x'], [F(2)])
        self.assertEqual(at_three['deaths'], ['A'])

    def test_dimension_and_missing_x_limits(self):
        mixed = {
            'A': dev('g', 'alpha', [seg(0, 1, [1])]),
            'B': dev('g', 'alpha', [seg(0, 1, [1, 2])])}
        receipt = self.records.apply('mixed', mixed)
        cid = self.cohorts.freeze(receipt.revision, mixed)['cohort_id']
        with self.assertRaises(ValueError):
            self.cohorts.compile_risk(cid)
        missing = {'A': dev('g', 'alpha', [
            dict(start=F(0), stop=F(1), load=F(1), failed=False)])}
        receipt = self.records.apply('nox', missing)
        cid = self.cohorts.freeze(receipt.revision, missing)['cohort_id']
        with self.assertRaises(ValueError):
            self.cohorts.compile_risk(cid)

    def test_count_limits(self):
        too_many_devices = {
            'd%02d' % i: dev('g', 'alpha', [seg(0, 1, [1])])
            for i in range(81)}
        receipt = self.records.apply('many', too_many_devices)
        cid = self.cohorts.freeze(receipt.revision, too_many_devices)['cohort_id']
        with self.assertRaises(ValueError):
            self.cohorts.compile_risk(cid)
        many_intervals = {'A': dev('g', 'alpha',
                                   [seg(i, i + 1, [1]) for i in range(161)])}
        receipt = self.records.apply('segments', many_intervals)
        cid = self.cohorts.freeze(receipt.revision, many_intervals)['cohort_id']
        with self.assertRaises(ValueError):
            self.cohorts.compile_risk(cid)
        strata = {'d%d' % i: dev('g', 's%d' % i, [seg(0, 1, [1])])
                  for i in range(5)}
        receipt = self.records.apply('strata', strata)
        cid = self.cohorts.freeze(receipt.revision, strata)['cohort_id']
        with self.assertRaises(ValueError):
            self.cohorts.compile_risk(cid)

    def test_empty_and_no_covariate_dimension(self):
        values = {'Q': dev('g', 'alpha', [])}
        plan = self.accept('empty', values)
        self.assertEqual(plan['p'], 0)
        self.assertEqual(plan['events'], [])
        loaded = self.cohorts.load_risk(plan['plan_id'])
        self.assertEqual(loaded, plan)

    def test_returned_copy_is_isolated(self):
        plan = self.accept('tied', ce.tied_case())
        plan['events'][0]['deaths'].append('tampered')
        plan['members'][0]['batch_id'] = 'fake'
        fresh = self.cohorts.load_risk(plan['plan_id'])
        self.assertEqual(fresh['events'][0]['deaths'], ['a0', 'a1'])
        self.assertNotEqual(fresh['members'][0]['batch_id'], 'fake')

    def test_unknown_objects(self):
        with self.assertRaises(KeyError):
            self.cohorts.compile_risk(999)
        with self.assertRaises(KeyError):
            self.cohorts.load_risk(999)
        with self.assertRaises(KeyError):
            self.cox.fit_cox(999)


class TestCoxFit(CoxCase, unittest.TestCase):
    def test_tied_exact_values(self):
        plan = self.accept('tied', ce.tied_case())
        report = self.reader.read(self.cox.fit_cox(plan['plan_id']))
        self.assertEqual(report['basis'], COX_BASIS)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['p'], 1)
        self.assertLess(abs(report['beta'][0]), 1e-12)
        self.assertLess(abs(report['information'][0][0] - float(F(47, 72))), 1e-10)
        self.assertEqual([r['batch_id'] for r in report['batch_scores']],
                         ['g', 'h'])
        self.assertLess(abs(report['batch_scores'][0]['score'][0]
                            - float(F(25, 72))), 1e-10)
        self.assertLess(abs(report['batch_scores'][1]['score'][0]
                            + float(F(25, 72))), 1e-10)
        self.assertLess(abs(report['covariance'][0][0]
                            - float(F(1250, 2209))), 1e-10)

    def test_vector_exact_values(self):
        plan = self.accept('vector', ce.vector_case())
        report = self.reader.read(self.cox.fit_cox(plan['plan_id']))
        self.assertEqual(report['p'], 2)
        self.assertLess(abs(report['information'][0][0] - float(F(5, 3))), 1e-10)
        self.assertLess(abs(report['information'][1][1] - float(F(7, 3))), 1e-10)
        self.assertLess(abs(report['covariance'][0][1] - float(F(-7, 10))), 1e-10)

    def test_no_events_report(self):
        plan = self.accept('quiet', {'Q': dev('g', 'alpha', [])})
        report = self.reader.read(self.cox.fit_cox(plan['plan_id']))
        self.assertEqual(report['status'], 'no_events')
        self.assertIsNone(report['beta'])
        self.assertIsNone(report['information'])
        self.assertIsNone(report['covariance'])
        self.assertEqual(report['batch_scores'], [])
        self.assertEqual(report['log_likelihood'], 0.0)
        self.assertIsInstance(report['log_likelihood'], float)

    def test_refit_publishes_new_report_and_reads_without_source(self):
        plan = self.accept('tied', ce.tied_case())
        first = self.cox.fit_cox(plan['plan_id'])
        second = self.cox.fit_cox(plan['plan_id'])
        self.assertNotEqual(first, second)
        forbidden = {'device_versions', 'cohorts', 'cohort_members',
                     'risk_plans'}
        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table in forbidden:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.archive.connection.set_authorizer(authorize)
        try:
            saved = self.reader.read(first)
        finally:
            self.archive.connection.set_authorizer(None)
        self.assertEqual(saved['plan_id'], plan['plan_id'])

    def test_comparator_rejects_cox(self):
        plan = self.accept('tied', ce.tied_case())
        cox_id = self.cox.fit_cox(plan['plan_id'])
        receipt = self.records.apply('desc', ce.tied_case())
        cid = self.cohorts.freeze(receipt.revision, ce.tied_case())['cohort_id']
        from reliability.reports.publish import ReportPublisher
        desc_id = ReportPublisher(self.archive).publish(cid)
        with self.assertRaises(ValueError):
            self.comparator.compare(cox_id, desc_id)
        with self.assertRaises(ValueError):
            self.comparator.compare(cox_id, cox_id)


class TestCoxLifecycle(CoxCase, unittest.TestCase):
    def _file_case(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'cox.sqlite3'
        self.archive.close()
        self.archive = Archive.open(self.path)
        self.records = RecordService(self.archive)
        self.cohorts = CohortService(self.archive)
        self.cox = CoxService(self.archive)
        self.reader = ReportReader(self.archive)

    def test_correction_and_reopen_keep_old_plan_and_report(self):
        self._file_case()
        plan = self.accept('tied', ce.tied_case())
        report_id = self.cox.fit_cox(plan['plan_id'])
        original = self.reader.read(report_id)
        self.records.apply('correction', ce.correction())
        self.reopen()
        # old plan and report are intact and readable without recomputation
        self.assertEqual(self.cohorts.load_risk(plan['plan_id']), plan)
        self.assertEqual(self.reader.read(report_id), original)
        # a fresh plan on the corrected head gives different coefficients
        corrected_values = dict(ce.tied_case(), **ce.correction())
        receipt = self.records.apply('corrected-head', corrected_values)
        cid = self.cohorts.freeze(receipt.revision, corrected_values)['cohort_id']
        new_plan = self.cohorts.compile_risk(cid)
        new_report = self.reader.read(self.cox.fit_cox(new_plan['plan_id']))
        self.assertNotEqual(new_plan['plan_id'], plan['plan_id'])
        self.assertNotEqual(new_report['batch_scores'], original['batch_scores'])
        # refitting the OLD plan reproduces the original numbers exactly
        refit = self.reader.read(self.cox.fit_cox(plan['plan_id']))
        self.assertEqual(refit['beta'], original['beta'])
        self.assertEqual(refit['covariance'], original['covariance'])

    def test_publish_failure_rolls_back_and_retries(self):
        plan = self.accept('tied', ce.tied_case())
        before = self.archive.connection.execute(
            'SELECT count(*) FROM reports').fetchone()[0]
        self.archive.connection.execute("""
            CREATE TRIGGER fail_cox AFTER INSERT ON reports
            BEGIN SELECT RAISE(ABORT, 'storage:cox-head'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.cox.fit_cox(plan['plan_id'])
        self.assertFalse(self.archive.connection.in_transaction)
        self.assertEqual(self.archive.connection.execute(
            'SELECT count(*) FROM reports').fetchone()[0], before)
        self.archive.connection.execute('DROP TRIGGER fail_cox')
        report_id = self.cox.fit_cox(plan['plan_id'])
        report = self.reader.read(report_id)
        self.assertEqual(report['status'], 'ok')
