import sqlite3
import tempfile
from pathlib import Path
from fractions import Fraction as F
from reliability.archive.store import Archive
from reliability.archive.schema import initialize_schema
from test_daily import ReliabilityCase, device, segment


class TestPersistence(ReliabilityCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'archive.sqlite3'
        super().setUp()

    def reopen(self):
        self.archive.close()
        self.connect()

    def test_reopen_and_aliases(self):
        values = {'A': device([segment(0, 2, 1, True)], 'old', 'b1')}
        receipt = self.records.apply('old', values)
        revision = receipt.revision
        receipt.revision = 888
        receipt.device_ids.append('fake')
        values['A']['intervals'][0]['load'] = 999
        summary = self.cohorts.freeze(revision, ['A'])
        cid = summary['cohort_id']
        summary['members'][0]['batch_id'] = 'fake'
        summary['members'][0]['intervals'][0]['load'] = 999
        result = self.analysis.describe(cid)
        result.strata[0]['load_exposure'] = F(999)
        result.members.clear()
        rid = self.publisher.publish(cid)
        saved = self.reader.read(rid)
        altered = self.reader.read(rid)
        altered['strata'][0]['load_exposure'] = F(999)
        altered['members'].clear()
        self.records.apply('new', {'A': device([segment(0, 2, 3)], 'new', 'b2')})
        self.reopen()
        self.assertEqual(self.reader.read(rid), saved)
        self.assertEqual(self.analysis.describe(cid).strata[0]['load_exposure'], F(2))
        self.assertEqual(self.cohorts.load_snapshot(cid).members[0].batch_id, 'b1')
        self.assertEqual(self.records.get_revision(revision)['A'].intervals[0].load, F(1))
        replay = self.records.apply('old', {'A': device([segment(0, 2, 1, True)], 'old', 'b1')})
        self.assertEqual((replay.revision, replay.device_ids), (revision, ['A']))

    def test_rational_roundtrip(self):
        cid = self.accept('rational', {'A': device([
            segment(0, F(1, 3), F(1, 10)),
            segment(F(1, 3), 1, F(1, 5), True)])})
        rid = self.publisher.publish(cid)
        self.reopen()
        forbidden = {'device_versions', 'cohorts', 'cohort_members'}
        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table in forbidden:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.archive.connection.set_authorizer(authorize)
        try:
            saved = self.reader.read(rid)
            self.assertEqual(saved['strata'][0]['load_exposure'], F(1, 6))
            self.assertIsInstance(saved['strata'][0]['load_exposure'], F)
            self.assertEqual((saved['cohort_id'], saved['revision']), (cid, 1))
        finally:
            self.archive.connection.set_authorizer(None)

    def test_initialize_twice(self):
        from run import demo
        self.assertEqual(self.records.revision, 0)
        initialize_schema(self.archive.connection)
        self.assertEqual(self.records.get_revision(0), {})
        self.archive.close()
        demo(self.path)
        self.connect()
        custom = self.records.apply('user-correction', {
            'A': device([segment(0, 5, 7)], 'user', 'user-batch')})
        before = self.records.get_revision(custom.revision)
        self.archive.close()
        demo(self.path)
        self.connect()
        self.assertEqual(self.records.revision, custom.revision)
        self.assertEqual(self.records.get_revision(custom.revision), before)
        with self.assertRaises(ValueError):
            self.records.apply('demo:daily', {'A': device([segment(0, 1, 1)])})
        initialize_schema(self.archive.connection)
        self.reopen()
        self.assertEqual(self.records.get_revision(custom.revision), before)
        self.assertGreater(self.counts()[5], 0)

    def test_unsupported_schema(self):
        self.archive.connection.execute(
            "UPDATE metadata SET value='99' WHERE key='schema_version'")
        self.archive.close()
        with self.assertRaises(ValueError):
            Archive.open(self.path)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute(
                "SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], '99')
        finally:
            connection.close()
