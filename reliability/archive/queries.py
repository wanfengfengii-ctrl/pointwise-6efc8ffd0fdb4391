from reliability.archive.codec import encode_value, decode_value


def _require_write(connection):
    if not connection.in_transaction:
        raise RuntimeError('write requires archive transaction')


def read_request_row(connection, request_id):
    row = connection.execute(
        'SELECT canonical, revision_id FROM requests WHERE request_id=?',
        (request_id,)).fetchone()
    if row is None:
        return None
    return {'canonical': bytes(row[0]), 'revision': row[1]}


def latest_revision(connection):
    return connection.execute('SELECT max(id) FROM revisions').fetchone()[0]


def read_revision_rows(connection, revision):
    if type(revision) is not int or connection.execute(
            'SELECT 1 FROM revisions WHERE id=?', (revision,)).fetchone() is None:
        raise KeyError(revision)
    rows = connection.execute(
        '''SELECT d.device_id, d.payload FROM device_versions d
           WHERE d.revision_id = (
             SELECT max(h.revision_id) FROM device_versions h
             WHERE h.device_id=d.device_id AND h.revision_id<=?)
           ORDER BY d.device_id''', (revision,)).fetchall()
    return {device_id: decode_value(payload) for device_id, payload in rows}


def commit_revision_rows(connection, request_id, canonical, devices):
    _require_write(connection)
    revision = connection.execute('INSERT INTO revisions DEFAULT VALUES').lastrowid
    for device_id, payload in devices.items():
        connection.execute(
            'INSERT INTO device_versions VALUES (?, ?, ?)',
            (revision, device_id, encode_value(payload)))
    connection.execute('INSERT INTO requests VALUES (?, ?, ?)',
                       (request_id, canonical, revision))
    return revision


def insert_snapshot_rows(connection, revision, members):
    _require_write(connection)
    cohort_id = connection.execute(
        'INSERT INTO cohorts(revision_id) VALUES (?)', (revision,)).lastrowid
    for device_id, payload in members.items():
        connection.execute('INSERT INTO cohort_members VALUES (?, ?, ?)',
                           (cohort_id, device_id, encode_value(payload)))
    return cohort_id


def read_snapshot_rows(connection, cohort_id):
    if type(cohort_id) is not int:
        raise KeyError(cohort_id)
    head = connection.execute(
        'SELECT revision_id FROM cohorts WHERE id=?', (cohort_id,)).fetchone()
    if head is None:
        raise KeyError(cohort_id)
    members = connection.execute(
        '''SELECT device_id, payload FROM cohort_members
           WHERE cohort_id=? ORDER BY device_id''', (cohort_id,)).fetchall()
    return head[0], {k: decode_value(v) for k, v in members}


def insert_report_rows(connection, header, body, strata):
    _require_write(connection)
    report_id = connection.execute(
        'INSERT INTO reports(cohort_id, revision_id, basis) VALUES (?, ?, ?)',
        (header['cohort_id'], header['revision'], header['basis'])).lastrowid
    connection.execute('INSERT INTO report_bodies VALUES (?, ?)', (report_id, body))
    for row in strata:
        connection.execute('INSERT INTO report_strata VALUES (?, ?, ?)',
                           (report_id, row['stratum'], encode_value(row)))
    return report_id


def read_report_rows(connection, report_id):
    if type(report_id) is not int:
        raise KeyError(report_id)
    head = connection.execute(
        'SELECT cohort_id, revision_id, basis FROM reports WHERE id=?',
        (report_id,)).fetchone()
    if head is None:
        raise KeyError(report_id)
    body = connection.execute(
        'SELECT payload FROM report_bodies WHERE report_id=?', (report_id,)).fetchone()
    if body is None:
        raise ValueError('incomplete report body')
    rows = connection.execute(
        '''SELECT stratum, payload FROM report_strata
           WHERE report_id=? ORDER BY stratum''', (report_id,)).fetchall()
    strata = []
    for name, payload in rows:
        row = decode_value(payload)
        if row['stratum'] != name:
            raise ValueError('inconsistent stored stratum')
        strata.append(row)
    return ({'cohort_id': head[0], 'revision': head[1], 'basis': head[2]},
            body[0], strata)
