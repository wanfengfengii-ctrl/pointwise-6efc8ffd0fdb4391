from fractions import Fraction as F
from reliability.archive import queries
from reliability.archive.transactions import transaction
from reliability.reports.content import (
    ReportContent, encode_report_content,
)
from test_daily import ReliabilityCase, device, segment


class TestCorrections(ReliabilityCase):
    def test_frozen_before_after(self):
        cid = self.accept('old', {'A': device([segment(0, 2, 1, True)], 'old', 'b1')})
        first = self.publisher.publish(cid)
        old = self.reader.read(first)
        new_cid = self.accept('corrected', {
            'A': device([segment(0, 2, 3, True)], 'new', 'b2')})
        second = self.publisher.publish(new_cid)
        self.assertEqual(self.reader.read(first), old)
        frozen = self.cohorts.load_snapshot(cid).summary()
        self.assertEqual((frozen['members'][0]['batch_id'],
                          frozen['members'][0]['stratum']), ('b1', 'old'))
        self.assertEqual(self.analysis.describe(cid).strata[0]['load_exposure'], F(2))
        self.assertEqual(self.reader.read(second)['strata'][0]['load_exposure'], F(6))
        difference = self.comparator.compare(first, second)['strata']
        self.assertEqual([r['stratum'] for r in difference], ['new', 'old'])
        self.assertEqual(difference[0]['load_exposure'], F(6))
        self.assertEqual(difference[1]['load_exposure'], F(-2))

    def test_layer_union(self):
        a = self.accept('a', {'A': device([segment(0, 2, 1, True)], 'alpha')})
        b = self.accept('b', {'A': device([segment(0, 2, 3)], 'beta')})
        left, right = self.publisher.publish(a), self.publisher.publish(b)
        expected = [
            dict(stratum='alpha', person_time=F(-2), failures=-1, load_exposure=F(-2)),
            dict(stratum='beta', person_time=F(2), failures=0, load_exposure=F(6))]
        self.assertEqual(self.comparator.compare(left, right)['strata'], expected)
        reverse = self.comparator.compare(right, left)['strata']
        for row, opposite in zip(expected, reverse):
            for field in ('person_time', 'failures', 'load_exposure'):
                self.assertEqual(row[field], -opposite[field])
        self.assertNotIn('rate', reverse[0])

    def test_compare_contract(self):
        cid = self.accept('a', {'A': device([segment(0, 1, 1)])})
        rid = self.publisher.publish(cid)
        value = self.reader.read(rid)
        value.pop('report_id')
        value['basis'] = 'archived-external-basis'
        content = ReportContent(value)
        with transaction(self.archive.connection):
            other = queries.insert_report_rows(
                self.archive.connection,
                {key: value[key] for key in ('cohort_id', 'revision', 'basis')},
                encode_report_content(content), value['strata'])
        with self.assertRaises(ValueError):
            self.comparator.compare(rid, other)
        for left, right in ((rid, 999), (999, rid)):
            with self.assertRaises(KeyError):
                self.comparator.compare(left, right)
