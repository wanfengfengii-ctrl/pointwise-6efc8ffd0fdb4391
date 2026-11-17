SCHEMA_VERSION = 1

_TABLES = {
    'metadata', 'revisions', 'device_versions', 'requests', 'cohorts',
    'cohort_members', 'reports', 'report_bodies', 'report_strata',
}

_DDL = (
    'CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    'CREATE TABLE revisions (id INTEGER PRIMARY KEY AUTOINCREMENT)',
    '''CREATE TABLE device_versions (
        revision_id INTEGER NOT NULL REFERENCES revisions(id),
        device_id TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(revision_id, device_id))''',
    '''CREATE INDEX device_history
        ON device_versions(device_id, revision_id)''',
    '''CREATE TABLE requests (
        request_id TEXT PRIMARY KEY, canonical BLOB NOT NULL,
        revision_id INTEGER NOT NULL UNIQUE REFERENCES revisions(id))''',
    '''CREATE TABLE cohorts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        revision_id INTEGER NOT NULL REFERENCES revisions(id))''',
    '''CREATE TABLE cohort_members (
        cohort_id INTEGER NOT NULL REFERENCES cohorts(id),
        device_id TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(cohort_id, device_id))''',
    '''CREATE TABLE reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cohort_id INTEGER NOT NULL REFERENCES cohorts(id),
        revision_id INTEGER NOT NULL REFERENCES revisions(id),
        basis TEXT NOT NULL)''',
    '''CREATE TABLE report_bodies (
        report_id INTEGER PRIMARY KEY REFERENCES reports(id),
        payload TEXT NOT NULL)''',
    '''CREATE TABLE report_strata (
        report_id INTEGER NOT NULL REFERENCES reports(id),
        stratum TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(report_id, stratum))''',
)


def verify_schema(connection):
    names = {r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not _TABLES <= names:
        raise ValueError('incomplete archive schema')
    row = connection.execute(
        "SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if row is None or row[0] != str(SCHEMA_VERSION):
        raise ValueError('unsupported archive schema version')


def initialize_schema(connection):
    names = {r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if names:
        verify_schema(connection)
        return
    connection.execute('BEGIN IMMEDIATE')
    try:
        for statement in _DDL:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO metadata VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),))
        connection.execute('INSERT INTO revisions(id) VALUES (0)')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    verify_schema(connection)
