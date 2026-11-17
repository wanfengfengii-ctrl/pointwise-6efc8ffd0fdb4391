import math
from reliability.cohorts.snapshots import CohortService
from reliability.reports.cox_content import (
    content_from_fit, encode_cox_content,
)
from reliability.analysis import cox_engine
from reliability.archive import queries
from reliability.archive.transactions import transaction


class CoxService:
    def __init__(self, archive):
        self.archive = archive
        self.cohorts = CohortService(archive)

    def fit_cox(self, plan_id):
        plan = self.cohorts.load_risk(plan_id)
        batch_ids = sorted({member['batch_id'] for member in plan['members']})
        if not plan['events']:
            content = content_from_fit(
                plan, 'no_events', None, 0.0, None, [], None)
        else:
            events = cox_engine.prepare_events(plan)
            beta, log_likelihood, information = cox_engine.fit_beta(
                events, plan['p'])
            score_vectors = cox_engine.batch_scores(
                events, beta, batch_ids)
            matrix = cox_engine.covariance(information, score_vectors)
            batch_scores = [{'batch_id': batch, 'score': list(score)}
                            for batch, score in zip(batch_ids, score_vectors)]
            content = content_from_fit(
                plan, 'ok', beta, log_likelihood, information,
                batch_scores, matrix)
        if not math.isfinite(content['log_likelihood']):
            raise ValueError('non-finite cox result')
        header = {key: content[key]
                  for key in ('cohort_id', 'revision', 'basis')}
        body = encode_cox_content(content)
        with transaction(self.archive.connection):
            report_id = queries.insert_cox_report_rows(
                self.archive.connection, header, body)
        return report_id
