import copy
import tempfile
from pathlib import Path
from fractions import Fraction as F
from test_daily import ReliabilityCase, device, segment


class TestRecords(ReliabilityCase):
    def test_invalid_batch_atomic(self):
        self.records.apply('seed', {'old': device([segment(0, 1, 1)])})
        before = self.counts()
        with self.assertRaises(ValueError):
            self.records.apply('invalid', {
                'good': device([segment(0, 1, 2)]),
                'bad': device([segment(0, 2, 1), segment(1, 3, 1)])})
        self.assertEqual(self.counts(), before)
        self.assertEqual(set(self.records.get_revision(1)), {'old'})
        self.assertEqual(self.records.revision, 1)

    def test_terminal_and_adjacent(self):
        base = {'A': device([segment(0, 1, 1)])}
        self.records.apply('seed', base)
        before = self.counts()
        invalid = [
            [segment(0, 1, 1, True), segment(2, 3, 1)],
            [segment(0, 1, 1, True), segment(1, 2, 1, True)],
            [segment(1, 1, 1)],
            [segment(0, 2, 1), segment(1, 3, 1)],
        ]
        for index, intervals in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    self.records.apply('bad-' + str(index), {
                        'A': device(intervals), 'B': device([segment(0, 1, 1)])})
                self.assertEqual(self.counts(), before)
                self.assertEqual(self.records.get_revision(1)['A'].intervals[0].stop, F(1))
        receipt = self.records.apply('adjacent', {'A': device([
            segment(1, 2, 1, True), segment(0, 1, 1)])})
        self.assertEqual(receipt.revision, 2)

    def test_input_types(self):
        from run import decode_submission
        before = self.counts()
        for value in (True, 0.1, None, '1/3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.records.apply('type', {'A': device([segment(0, 1, value)])})
        for failed in (0, 1, 'yes', None):
            with self.subTest(failed=failed), self.assertRaises(ValueError):
                self.records.apply('flag', {'A': device([segment(0, 1, 1, failed)])})
        with self.assertRaises(ValueError):
            self.records.apply('missing', {'A': {'batch_id': 'x', 'stratum': 'a'}})
        with self.assertRaises(ValueError):
            decode_submission({'request_id': 'q', 'device_intervals': {
                'A': device([segment(0, [1, 0], 1)])}})
        self.assertEqual(self.counts(), before)

    def test_replay_and_conflict(self):
        values = {'A': device([segment(0, 1, 1)])}
        receipt = self.records.apply('request', values)
        before = self.counts()
        self.assertEqual(self.records.apply('request', values), receipt)
        with self.assertRaises(ValueError):
            self.records.apply('request', {'A': device([segment(0, 2, 1)])})
        self.assertEqual(self.counts(), before)

    def test_semantic_replay(self):
        values = {
            'B': device([segment(0, 2, 2)], 'beta', 'b2'),
            'A': device([segment(0, F(1, 3), F(1, 10)),
                         segment(F(1, 3), 1, F(1, 5), True)])}
        receipt = self.records.apply('semantic', values)
        reordered = {'A': copy.deepcopy(values['A']), 'B': copy.deepcopy(values['B'])}
        reordered['A']['intervals'].reverse()
        reordered['A']['intervals'][1]['stop'] = F(2, 6)
        reordered['B']['intervals'][0]['stop'] = F(4, 2)
        self.assertEqual(self.records.apply('semantic', reordered), receipt)
        before = self.counts()
        for field, value in (('load', F(9)), ('failed', False)):
            altered = copy.deepcopy(values)
            altered['A']['intervals'][-1][field] = value
            with self.assertRaises(ValueError):
                self.records.apply('semantic', altered)
        for field in ('batch_id', 'stratum'):
            altered = copy.deepcopy(values)
            altered['A'][field] = 'different'
            with self.assertRaises(ValueError):
                self.records.apply('semantic', altered)
        self.assertEqual(self.counts(), before)

    def test_conflict_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            self.archive.close()
            self.path = Path(directory) / 'records.sqlite3'
            self.connect()
            values = {'A': device([segment(0, 1, F(1, 3))])}
            receipt = self.records.apply('persisted', values)
            self.archive.close()
            self.connect()
            self.assertEqual(self.records.apply('persisted', values), receipt)
            with self.assertRaises(ValueError):
                self.records.apply('persisted', {'A': device([segment(0, 1, 2)])})
            self.assertEqual(self.records.revision, 1)
            self.archive.close()

    def test_intake_storage_rollback(self):
        import sqlite3
        before = self.counts()
        self.archive.connection.execute("""
            CREATE TRIGGER fail_intake AFTER INSERT ON requests
            BEGIN SELECT RAISE(ABORT, 'storage:intake'); END""")
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self.records.apply('interrupted', {'A': device([segment(0, 1, 1)])})
        self.assertEqual(str(caught.exception), 'storage:intake')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.records.revision, 0)
        self.archive.connection.execute('DROP TRIGGER fail_intake')
        self.assertEqual(self.records.apply(
            'interrupted', {'A': device([segment(0, 1, 1)])}).revision, 1)
