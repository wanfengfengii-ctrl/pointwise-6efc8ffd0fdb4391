from reliability.analysis.describe import DescriptionService
from reliability.reports.build import build_report
from reliability.reports.content import encode_report_content
from reliability.archive import queries
from reliability.archive.transactions import transaction


class ReportPublisher:
    def __init__(self, archive):
        self.archive = archive
        self.description = DescriptionService(archive)

    def publish(self, cohort_id):
        content = build_report(self.description.describe(cohort_id))
        payload = content.copy()
        header = {key: payload[key] for key in ('cohort_id', 'revision', 'basis')}
        body = encode_report_content(content)
        with transaction(self.archive.connection):
            report_id = queries.insert_report_rows(
                self.archive.connection, header, body, payload['strata'])
        return report_id
