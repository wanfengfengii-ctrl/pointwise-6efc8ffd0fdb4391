import unittest
import random
from decimal import Decimal
from fractions import Fraction as F
from reliability.archive.store import Archive
from reliability.records.revisions import RecordService
from reliability.cohorts.snapshots import CohortService
from reliability.analysis.cox import CoxService
from reliability.reports.read import ReportReader
from audit import cox_audit
import cox_examples as ce

TOL = 1e-10


def _seg(start, stop, x, failed=False):
    return dict(start=F(start), stop=F(stop), load=F(1),
                failed=failed, x=[F(v) for v in x])


def _dev(batch, stratum, intervals):
    return dict(batch_id=batch, stratum=stratum, intervals=intervals)


class TestCoxAudit(unittest.TestCase):
    def setUp(self):
        self.archive = Archive.open(':memory:')
        self.records = RecordService(self.archive)
        self.cohorts = CohortService(self.archive)
        self.cox = CoxService(self.archive)
        self.reader = ReportReader(self.archive)

    def _publish(self, request_id, values):
        receipt = self.records.apply(request_id, values)
        cid = self.cohorts.freeze(receipt.revision, values)['cohort_id']
        plan = self.cohorts.compile_risk(cid)
        report = self.reader.read(self.cox.fit_cox(plan['plan_id']))
        members = plan['members']
        return report, members

    def _assert_matches_audit(self, report, members):
        oracle = cox_audit.audit(members)
        self.assertEqual(oracle['status'], 'ok')
        self.assertEqual(report['status'], 'ok')
        for j, value in enumerate(oracle['beta']):
            self.assertLess(abs(report['beta'][j] - float(value)), TOL)
        self.assertLess(abs(report['log_likelihood']
                            - float(oracle['log_likelihood'])), TOL)
        for j in range(oracle['p']):
            for k in range(oracle['p']):
                self.assertLess(abs(report['information'][j][k]
                                    - float(oracle['information'][j][k])), TOL)
                self.assertLess(abs(report['covariance'][j][k]
                                    - float(oracle['covariance'][j][k])), TOL)
        for row, oracle_row in zip(report['batch_scores'],
                                   oracle['batch_scores']):
            self.assertEqual(row['batch_id'], oracle_row['batch_id'])
            for j, value in enumerate(oracle_row['score']):
                self.assertLess(abs(row['score'][j] - float(value)), TOL)

    def test_tied_matches_independent_oracle(self):
        report, members = self._publish('audit-tied', ce.tied_case())
        self._assert_matches_audit(report, members)
        # exact hand values from COX.md, re-derived by the audit itself
        self.assertLess(abs(report['beta'][0]), 1e-12)
        self.assertLess(abs(report['information'][0][0] - float(F(47, 72))), TOL)
        self.assertLess(abs(report['covariance'][0][0]
                            - float(F(1250, 2209))), TOL)

    def test_two_dimension_information_matches_oracle(self):
        report, members = self._publish('audit-vector', ce.vector_case())
        self._assert_matches_audit(report, members)
        self.assertLess(abs(report['information'][0][0] - float(F(5, 3))), TOL)
        self.assertLess(abs(report['information'][1][1] - float(F(7, 3))), TOL)

    def test_nonzero_beta_matches_oracle(self):
        values = {
            'd1': _dev('g', 'alpha', [_seg(0, 1, [1, 0], True)]),
            'd2': _dev('g', 'alpha', [_seg(0, 1, [1, 2], True)]),
            'c1': _dev('h', 'alpha', [_seg(0, 1, [0, -1])]),
            'c2': _dev('h', 'beta', [_seg(0, 1, [-2, 1], True)]),
            'c3': _dev('h', 'beta', [_seg(0, 1, [2, -2])]),
            'c4': _dev('g', 'beta', [_seg(0, 1, [1, 0])]),
        }
        report, members = self._publish('audit-nonzero', values)
        self.assertTrue(any(abs(b) > 1e-3 for b in report['beta']))
        self._assert_matches_audit(report, members)

    def test_audit_rebuilds_risk_sets_including_endpoints(self):
        values = ce.boundary_case()
        receipt = self.records.apply('audit-boundary', values)
        cid = self.cohorts.freeze(receipt.revision, values)['cohort_id']
        plan = self.cohorts.compile_risk(cid)
        events = cox_audit.build_events(plan['members'])
        self.assertEqual([r['device_id'] for r in events[0]['risk']],
                         ['A', 'C'])
        self.assertEqual(events[0]['deaths'], ['A'])
        projected = [{'device_id': r['device_id'], 'batch_id': r['batch_id'],
                      'x': [F(*r['x'][0].as_integer_ratio())]}
                     for r in events[0]['risk']]
        self.assertEqual(plan['events'][0]['risk'], projected)

    def test_audit_uses_decimal_not_production_floats(self):
        report, members = self._publish('audit-decimal', ce.tied_case())
        oracle = cox_audit.audit(members)
        self.assertIsInstance(oracle['beta'][0], Decimal)
        self.assertIsInstance(oracle['information'][0][0], Decimal)
        self.assertIsInstance(report['beta'][0], float)

    def test_split_segment_matches_oracle_and_original(self):
        whole_report, whole_members = self._publish('audit-whole', ce.tied_case())
        split_report, split_members = self._publish('audit-split',
                                                     ce.split_tied_case())
        self._assert_matches_audit(split_report, split_members)
        self.assertEqual(split_report['beta'], whole_report['beta'])
        self.assertEqual(split_report['information'], whole_report['information'])
        self.assertEqual(split_report['batch_scores'], whole_report['batch_scores'])
        self.assertEqual(split_report['covariance'], whole_report['covariance'])
        # the audit independently rebuilds identical event risk sets
        self.assertEqual(cox_audit.build_events(whole_members),
                         cox_audit.build_events(split_members))

    def test_cross_stratum_batch_accumulates_in_one_score(self):
        report, members = self._publish('audit-cross', ce.tied_case())
        oracle = cox_audit.audit(members)
        # batch g appears in both strata; the audit holds one merged score
        self.assertEqual([row['batch_id'] for row in oracle['batch_scores']],
                         ['g', 'h'])
        # the two per-stratum contributions sum to the reported cluster score
        events = cox_audit.build_events(members)
        beta = oracle['beta']
        alpha = cox_audit.batch_scores([events[0]], beta, ['g', 'h'])
        beta_event = cox_audit.batch_scores([events[1]], beta, ['g', 'h'])
        merged = cox_audit.batch_scores(events, beta, ['g', 'h'])
        for g in range(2):
            self.assertLess(abs(float(alpha[g][0] + beta_event[g][0]
                                      - merged[g][0])), 1e-40)
        self._assert_matches_audit(report, members)

    def test_full_limits_stress_within_numeric_guarantee(self):
        random.seed(42)
        values = {}
        for d in range(80):
            intervals = []
            time = F(0)
            for k in range(2):
                x = [F(random.randint(-3, 3), random.randint(1, 4))
                     for _ in range(2)]
                stop = time + F(random.randint(1, 3), 2)
                intervals.append(_seg(time, stop, x,
                                      failed=(k == 1 and d % 5 == 0)))
                time = stop
            values['dev%02d' % d] = _dev(
                ['lotA', 'lotB', 'lotC'][d % 3],
                ['s0', 's1', 's2', 's3'][d % 4], intervals)
        receipt = self.records.apply('audit-stress', values)
        cid = self.cohorts.freeze(receipt.revision, values)['cohort_id']
        plan = self.cohorts.compile_risk(cid)
        self.assertEqual(len(plan['members']), 80)
        self.assertEqual(sum(len(m['intervals']) for m in plan['members']), 160)
        report = self.reader.read(self.cox.fit_cox(plan['plan_id']))
        oracle = cox_audit.audit(plan['members'])
        worst = 0.0
        for j in range(2):
            worst = max(worst, abs(report['beta'][j] - float(oracle['beta'][j])))
            worst = max(worst, abs(report['log_likelihood']
                                   - float(oracle['log_likelihood'])))
            for k in range(2):
                worst = max(worst, abs(report['information'][j][k]
                                       - float(oracle['information'][j][k])))
                worst = max(worst, abs(report['covariance'][j][k]
                                       - float(oracle['covariance'][j][k])))
        for row, oracle_row in zip(report['batch_scores'],
                                   oracle['batch_scores']):
            for j in range(2):
                worst = max(worst, abs(row['score'][j]
                                       - float(oracle_row['score'][j])))
        self.assertLessEqual(worst, 1e-7)

    def test_no_events_audit(self):
        values = {'Q': _dev('g', 'alpha', [])}
        report, members = self._publish('audit-quiet', values)
        oracle = cox_audit.audit(members)
        self.assertEqual(oracle['status'], 'no_events')
        self.assertEqual(report['status'], 'no_events')
        self.assertIsNone(report['beta'])


if __name__ == '__main__':
    unittest.main()
