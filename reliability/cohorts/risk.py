"""Fixed Efron risk-set compilation for the stratified Cox increment."""

MAX_DEVICES = 80
MAX_INTERVALS = 160
MAX_STRATA = 4


def _require_limits(members):
    if len(members) > MAX_DEVICES:
        raise ValueError('risk plan allows at most 80 devices')
    if sum(len(member.intervals) for member in members) > MAX_INTERVALS:
        raise ValueError('risk plan allows at most 160 intervals')
    if len({member.stratum for member in members}) > MAX_STRATA:
        raise ValueError('risk plan allows at most 4 strata')


def _common_dimension(members):
    dimensions = set()
    for member in members:
        for interval in member.intervals:
            if interval.x is None:
                raise ValueError('risk plan requires x on every non-empty interval')
            dimensions.add(len(interval.x))
    if not dimensions:
        return 0
    if len(dimensions) > 1:
        raise ValueError('all risk plan covariates must share one dimension')
    return dimensions.pop()


def _event_moments(members):
    """Map (stratum, time) to risk and death members using exact (start, stop]."""
    moments = {}
    for member in members:
        for interval in member.intervals:
            if interval.failed:
                moments.setdefault((member.stratum, interval.stop), set())
    for key in moments:
        stratum, time = key
        risk, deaths = [], []
        for member in members:
            if member.stratum != stratum:
                continue
            covering = None
            for interval in member.intervals:
                if interval.start < time <= interval.stop:
                    if covering is not None:
                        raise ValueError('overlapping risk membership')
                    covering = interval
            if covering is None:
                continue
            risk.append({'device_id': member.device_id,
                         'batch_id': member.batch_id,
                         'x': list(covering.x)})
            if covering.failed and covering.stop == time:
                deaths.append(member.device_id)
        deaths.sort()
        risk.sort(key=lambda row: row['device_id'])
        moments[key] = (risk, deaths)
    return moments


def build_risk_plan(snapshot):
    members = tuple(snapshot.members)
    _require_limits(members)
    p = _common_dimension(members)
    moments = _event_moments(members)
    events = []
    for stratum, time in sorted(moments):
        risk, deaths = moments[(stratum, time)]
        risk_ids = {row['device_id'] for row in risk}
        if not deaths or any(death not in risk_ids for death in deaths):
            raise ValueError('deaths must belong to the risk set')
        events.append({'stratum': stratum, 'time': time,
                       'risk': risk, 'deaths': deaths})
    return {
        'cohort_id': snapshot.cohort_id,
        'revision': snapshot.revision,
        'p': p,
        'members': [
            {'device_id': member.device_id, 'batch_id': member.batch_id,
             'stratum': member.stratum,
             'intervals': [
                 {'start': interval.start, 'stop': interval.stop,
                  'load': interval.load, 'failed': interval.failed,
                  **({'x': list(interval.x)} if interval.x is not None else {})}
                 for interval in member.intervals]}
            for member in members],
        'events': events,
    }
