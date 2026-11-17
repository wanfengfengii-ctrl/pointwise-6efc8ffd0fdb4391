from reliability.reports.content import decode_report_content, REPORT_BASIS
from reliability.reports.cox_content import decode_cox_content, COX_BASIS
from reliability.archive import queries


class ReportReader:
    def __init__(self, archive):
        self.archive = archive

    def read(self, report_id):
        connection = self.archive.connection
        head = queries.read_report_head(connection, report_id)
        if head['basis'] == COX_BASIS:
            body = queries.read_cox_report_body(connection, report_id)
            payload = decode_cox_content(body)
            if any(payload[key] != value for key, value in head.items()):
                raise ValueError('cox report binding mismatch')
            return dict(payload, report_id=report_id)
        if head['basis'] != REPORT_BASIS:
            raise ValueError('unsupported report basis')
        header, body, strata = queries.read_report_rows(connection, report_id)
        payload = decode_report_content(body).copy()
        if any(payload[key] != value for key, value in header.items()):
            raise ValueError('report binding mismatch')
        if payload['strata'] != strata:
            raise ValueError('report strata mismatch')
        return dict(payload, report_id=report_id)
