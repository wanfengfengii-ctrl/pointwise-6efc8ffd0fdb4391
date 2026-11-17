import sqlite3
import tempfile
from pathlib import Path
from fractions import Fraction as F
from test_daily import ReliabilityCase, device, segment


class TestPublish(ReliabilityCase):
    def install_failure(self, stage):
        if stage == 'head':
            self.archive.connection.execute("""
                CREATE TRIGGER fail_report AFTER INSERT ON reports
                BEGIN SELECT RAISE(ABORT, 'storage:head'); END""")
        else:
            self.archive.connection.execute("""
                CREATE TRIGGER fail_report AFTER INSERT ON report_strata
                WHEN NEW.stratum='alpha'
                BEGIN SELECT RAISE(ABORT, 'storage:first-layer'); END""")

    def seed(self):
        cid = self.accept('layers', {
            'A': device([segment(0, 2, 1, True)], 'alpha', 'b1'),
            'B': device([segment(0, 3, 2)], 'beta', 'b1')})
        rid = self.publisher.publish(cid)
        return cid, rid

    def test_atomic_publication(self):
        cid, rid = self.seed()
        saved = self.reader.read(rid)
        before = self.counts()
        for stage, message in (('head', 'storage:head'),
                               ('layer', 'storage:first-layer')):
            self.install_failure(stage)
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                self.publisher.publish(cid)
            self.assertEqual(str(caught.exception), message)
            self.assertFalse(self.archive.connection.in_transaction)
            self.assertEqual(self.counts(), before)
            self.assertEqual(self.reader.read(rid), saved)
            self.archive.connection.execute('DROP TRIGGER fail_report')
        complete = self.reader.read(self.publisher.publish(cid))
        self.assertEqual(complete['strata'], saved['strata'])
        self.assertEqual(len(complete['strata']), 2)

    def test_failure_then_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            for stage in ('head', 'layer'):
                self.archive.close()
                self.path = Path(directory) / (stage + '.sqlite3')
                self.connect()
                cid, rid = self.seed()
                saved = self.reader.read(rid)
                before = self.counts()
                self.install_failure(stage)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.publisher.publish(cid)
                self.assertEqual(self.counts(), before)
                self.archive.close()
                self.connect()
                self.assertEqual(self.reader.read(rid), saved)
                self.assertEqual(self.counts(), before)
                self.archive.connection.execute('DROP TRIGGER fail_report')
                retry = self.reader.read(self.publisher.publish(cid))
                self.assertEqual(retry['strata'], saved['strata'])
                self.assertEqual(retry['members'], saved['members'])
                self.archive.close()

    def test_retry_fixed_cohort(self):
        cid, old = self.seed()
        self.install_failure('head')
        with self.assertRaises(sqlite3.IntegrityError):
            self.publisher.publish(cid)
        self.records.apply('later', {
            'A': device([segment(0, 2, 9)], 'changed', 'new-batch')})
        self.archive.connection.execute('DROP TRIGGER fail_report')
        retried = self.reader.read(self.publisher.publish(cid))
        self.assertEqual(retried['strata'], self.reader.read(old)['strata'])
        self.assertEqual(retried['members'][0]['batch_id'], 'b1')
        self.assertEqual(retried['strata'][0]['load_exposure'], F(2))
        before = self.counts()
        for operation in (lambda: self.publisher.publish(999),
                          lambda: self.reader.read(999)):
            with self.assertRaises(KeyError):
                operation()
            self.assertEqual(self.counts(), before)
