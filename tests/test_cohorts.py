from fractions import Fraction as F
from test_daily import ReliabilityCase, device, segment


class TestCohorts(ReliabilityCase):
    def test_unknown_selection(self):
        self.records.apply('known', {'A': device([segment(0, 2, 1)])})
        before = self.counts()
        with self.assertRaises(KeyError):
            self.freeze(1, ['A', 'missing'])
        self.assertEqual(self.counts(), before)

    def test_revision_asof(self):
        r1 = self.records.apply('old', {'A': device([segment(0, 2, 1)], 'old', 'b1')})
        r2 = self.records.apply('new', {'A': device([segment(0, 2, 3)], 'new', 'b2'),
                                      'B': device([], 'empty')})
        a = self.cohorts.freeze(r1.revision, ['A', 'A'])
        b = self.cohorts.freeze(r2.revision, ['B', 'A'])
        self.assertEqual(len(a['members']), 1)
        self.assertEqual([m['device_id'] for m in b['members']], ['A', 'B'])
        self.assertEqual((a['members'][0]['stratum'], a['members'][0]['batch_id']),
                         ('old', 'b1'))
        self.assertEqual((b['members'][0]['stratum'], b['members'][0]['batch_id']),
                         ('new', 'b2'))
        self.assertEqual(self.analysis.describe(a['cohort_id']).strata[0]['load_exposure'], F(2))
        self.assertEqual(self.analysis.describe(b['cohort_id']).strata[1]['load_exposure'], F(6))
        with self.assertRaises(KeyError):
            self.freeze(r1.revision, ['B'])

    def test_lookup_errors(self):
        before = self.counts()
        for operation in (lambda: self.freeze(99, []),
                          lambda: self.freeze(0, ['absent']),
                          lambda: self.analysis.describe(99)):
            with self.assertRaises(KeyError):
                operation()
            self.assertEqual(self.counts(), before)
        cid = self.freeze(0, [])
        self.assertEqual(self.cohorts.load_snapshot(cid).members, ())

    def test_snapshot_storage_rollback(self):
        import sqlite3
        self.records.apply('source', {'A': device([segment(0, 1, 1)])})
        before = self.counts()
        self.archive.connection.execute("""
            CREATE TRIGGER fail_snapshot AFTER INSERT ON cohort_members
            BEGIN SELECT RAISE(ABORT, 'storage:snapshot'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.freeze(1, ['A'])
        self.assertEqual(self.counts(), before)
        self.archive.connection.execute('DROP TRIGGER fail_snapshot')
        cid = self.freeze(1, ['A'])
        self.assertEqual(len(self.cohorts.load_snapshot(cid).members), 1)
