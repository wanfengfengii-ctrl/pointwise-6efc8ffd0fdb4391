import unittest
from fractions import Fraction as F
from reliability.archive.store import Archive
from reliability.records.revisions import RecordService
from reliability.cohorts.snapshots import CohortService
from reliability.analysis.describe import DescriptionService
from reliability.reports.publish import ReportPublisher
from reliability.reports.read import ReportReader
from reliability.reports.compare import ReportComparator


def segment(start, stop, load, failed=False):
    return dict(start=start, stop=stop, load=load, failed=failed)


def device(intervals, stratum='alpha', batch='lot1'):
    return dict(batch_id=batch, stratum=stratum, intervals=intervals)


class ReliabilityCase(unittest.TestCase):
    def setUp(self):
        self.path = getattr(self, 'path', ':memory:')
        self.connect()

    def connect(self):
        self.archive = Archive.open(self.path)
        self.addCleanup(self.archive.close)
        self.records = RecordService(self.archive)
        self.cohorts = CohortService(self.archive)
        self.analysis = DescriptionService(self.archive)
        self.publisher = ReportPublisher(self.archive)
        self.reader = ReportReader(self.archive)
        self.comparator = ReportComparator(self.archive)

    def freeze(self, revision, ids):
        return self.cohorts.freeze(revision, ids)['cohort_id']

    def accept(self, request_id, values):
        receipt = self.records.apply(request_id, values)
        return self.freeze(receipt.revision, values)

    def counts(self):
        return tuple(self.archive.connection.execute(
            'SELECT count(*) FROM ' + table).fetchone()[0]
            for table in ('revisions', 'device_versions', 'requests', 'cohorts',
                          'cohort_members', 'reports', 'report_bodies', 'report_strata'))


class TestDaily(ReliabilityCase):
    def test_exact_exposure(self):
        cid = self.accept('daily', {'A': device([
            segment(0, 2, 3), segment(3, 4, 5, True)])})
        expected = [dict(stratum='alpha', person_time=F(3), load_exposure=F(11),
                         failures=1, rate=F(1, 3))]
        result = self.analysis.describe(cid)
        self.assertEqual(result.strata, expected)
        report = self.reader.read(self.publisher.publish(cid))
        self.assertEqual(report['strata'], expected)
        self.assertEqual((report['cohort_id'], report['revision']), (cid, 1))
        self.assertEqual(report['members'][0]['batch_id'], 'lot1')

    def test_rational_exact(self):
        cid = self.accept('fractions', {'A': device([
            segment(0, F(1, 3), F(1, 10)),
            segment(F(1, 3), 1, F(1, 5), True)])})
        row = self.analysis.describe(cid).strata[0]
        self.assertEqual(row, dict(stratum='alpha', person_time=F(1),
                                   load_exposure=F(1, 6), failures=1, rate=F(1)))
        self.assertIsInstance(row['load_exposure'], F)
        self.assertEqual(self.reader.read(self.publisher.publish(cid))['strata'], [row])

    def test_strata_and_device_failures(self):
        cid = self.accept('layers', {
            'B': device([segment(0, 2, 2)], 'beta'),
            'A': device([segment(0, 2, 3), segment(3, 4, 5, True)])})
        rows = self.analysis.describe(cid).strata
        self.assertEqual([r['stratum'] for r in rows], ['alpha', 'beta'])
        self.assertEqual([(r['person_time'], r['load_exposure'], r['failures'], r['rate'])
                          for r in rows], [(F(3), F(11), 1, F(1, 3)),
                                            (F(2), F(4), 0, F(0))])
        cid2 = self.accept('two-failures', {
            name: device([segment(0, 1, 1, True)]) for name in ('A', 'B')})
        row = self.reader.read(self.publisher.publish(cid2))['strata'][0]
        self.assertEqual((row['person_time'], row['load_exposure'],
                          row['failures'], row['rate']), (F(2), F(2), 2, F(1)))

    def test_split_invariance(self):
        a = self.accept('whole', {'A': device([
            segment(0, 2, 3), segment(3, 4, 5, True)])})
        b = self.accept('split', {'A': device([
            segment(3, 4, 5, True), segment(1, 2, 3), segment(0, 1, 3)])})
        self.assertEqual(self.analysis.describe(a).strata, self.analysis.describe(b).strata)
        self.assertEqual(self.reader.read(self.publisher.publish(a))['strata'],
                         self.reader.read(self.publisher.publish(b))['strata'])

    def test_empty_and_no_failures(self):
        empty = self.freeze(0, [])
        self.assertEqual(self.analysis.describe(empty).strata, [])
        self.assertEqual(self.reader.read(self.publisher.publish(empty))['strata'], [])
        cid = self.accept('zero-events', {
            'A': device([segment(0, 2, 2)]),
            'Z': device([], 'zero')})
        rows = self.reader.read(self.publisher.publish(cid))['strata']
        self.assertEqual(rows[0]['rate'], F(0))
        self.assertIsInstance(rows[0]['rate'], F)
        self.assertEqual(rows[1], dict(stratum='zero', person_time=F(0),
                                       load_exposure=F(0), failures=0, rate=None))
        self.assertIsInstance(rows[1]['person_time'], F)
