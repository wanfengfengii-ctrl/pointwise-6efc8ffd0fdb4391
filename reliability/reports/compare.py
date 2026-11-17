from fractions import Fraction
from reliability.reports.read import ReportReader


class ReportComparator:
    def __init__(self, archive):
        self.reader = ReportReader(archive)

    def compare(self, left_report_id, right_report_id):
        left = self.reader.read(left_report_id)
        right = self.reader.read(right_report_id)
        if left['basis'] != right['basis']:
            raise ValueError('incompatible descriptive basis')
        lrows = {row['stratum']: row for row in left['strata']}
        rrows = {row['stratum']: row for row in right['strata']}
        zero = {'person_time': Fraction(0), 'load_exposure': Fraction(0), 'failures': 0}
        rows = []
        for key in sorted(set(lrows) | set(rrows)):
            a, b = lrows.get(key, zero), rrows.get(key, zero)
            rows.append(dict(stratum=key, **{
                field: b[field] - a[field]
                for field in ('person_time', 'load_exposure', 'failures')}))
        return {'left_report_id': left_report_id, 'right_report_id': right_report_id,
                'basis': left['basis'], 'strata': rows}
