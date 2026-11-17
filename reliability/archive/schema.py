SCHEMA_VERSION = 1

_TABLES = {
    'metadata', 'revisions', 'device_versions', 'requests', 'cohorts',
    'cohort_members', 'reports', 'report_bodies', 'report_strata',
    'risk_plans', 'cox_report_bodies',
}

_INDEX_NAMES = {'device_history'}

_DDL = (
    ('metadata',
     'CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)'),
    ('revisions',
     'CREATE TABLE revisions (id INTEGER PRIMARY KEY AUTOINCREMENT)'),
    ('device_versions', '''
        CREATE TABLE device_versions (
            revision_id INTEGER NOT NULL REFERENCES revisions(id),
            device_id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(revision_id, device_id))'''),
    ('device_history', '''
        CREATE INDEX device_history
            ON device_versions(device_id, revision_id)'''),
    ('requests', '''
        CREATE TABLE requests (
            request_id TEXT PRIMARY KEY, canonical BLOB NOT NULL,
            revision_id INTEGER NOT NULL UNIQUE REFERENCES revisions(id))'''),
    ('cohorts', '''
        CREATE TABLE cohorts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL REFERENCES revisions(id))'''),
    ('cohort_members', '''
        CREATE TABLE cohort_members (
            cohort_id INTEGER NOT NULL REFERENCES cohorts(id),
            device_id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(cohort_id, device_id))'''),
    ('reports', '''
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cohort_id INTEGER NOT NULL REFERENCES cohorts(id),
            revision_id INTEGER NOT NULL REFERENCES revisions(id),
            basis TEXT NOT NULL)'''),
    ('report_bodies', '''
        CREATE TABLE report_bodies (
            report_id INTEGER PRIMARY KEY REFERENCES reports(id),
            payload TEXT NOT NULL)'''),
    ('report_strata', '''
        CREATE TABLE report_strata (
            report_id INTEGER NOT NULL REFERENCES reports(id),
            stratum TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(report_id, stratum))'''),
    ('risk_plans', '''
        CREATE TABLE risk_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cohort_id INTEGER NOT NULL REFERENCES cohorts(id),
            revision_id INTEGER NOT NULL REFERENCES revisions(id),
            payload TEXT NOT NULL)'''),
    ('cox_report_bodies', '''
        CREATE TABLE cox_report_bodies (
            report_id INTEGER PRIMARY KEY REFERENCES reports(id),
            payload TEXT NOT NULL)'''),
)


def _stored_tables(connection):
    return {r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _check_version(connection):
    row = connection.execute(
        "SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if row is None or row[0] != str(SCHEMA_VERSION):
        raise ValueError('unsupported archive schema version')


def verify_schema(connection):
    names = _stored_tables(connection)
    if not _TABLES <= names:
        raise ValueError('incomplete archive schema')
    _check_version(connection)


def initialize_schema(connection):
    names = _stored_tables(connection)
    if names:
        _check_version(connection)
        if any(name not in names and name not in _INDEX_NAMES
               for name, _ in _DDL):
            connection.execute('BEGIN IMMEDIATE')
            try:
                existing_tables = _stored_tables(connection)
                existing_indexes = {r[0] for r in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
                for name, statement in _DDL:
                    present = (name in existing_indexes
                               if name in _INDEX_NAMES else name in existing_tables)
                    if not present:
                        connection.execute(statement)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        verify_schema(connection)
        return
    connection.execute('BEGIN IMMEDIATE')
    try:
        for name, statement in _DDL:
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
