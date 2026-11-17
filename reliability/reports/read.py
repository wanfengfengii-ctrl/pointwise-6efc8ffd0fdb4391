from reliability.reports.content import decode_report_content
from reliability.archive import queries


class ReportReader:
    def __init__(self, archive):
        self.archive = archive

    def read(self, report_id):
        header, body, strata = queries.read_report_rows(self.archive.connection, report_id)
        payload = decode_report_content(body).copy()
        if any(payload[key] != value for key, value in header.items()):
            raise ValueError('report binding mismatch')
        if payload['strata'] != strata:
            raise ValueError('report strata mismatch')
        return dict(payload, report_id=report_id)
