import sqlite3
from pathlib import Path
from reliability.archive.schema import initialize_schema


class Archive:
    def __init__(self, path):
        target = str(path) if isinstance(path, (str, Path)) else None
        if target is None or not target:
            raise ValueError('archive path must be nonempty')
        self._connection = sqlite3.connect(target, isolation_level=None)
        try:
            self._connection.execute('PRAGMA foreign_keys=ON')
            self._connection.execute('PRAGMA busy_timeout=5000')
            initialize_schema(self._connection)
        except BaseException:
            self._connection.close()
            self._connection = None
            raise

    @classmethod
    def open(cls, path=':memory:'):
        return cls(path)

    @property
    def connection(self):
        if self._connection is None:
            raise RuntimeError('archive is closed')
        return self._connection

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        self.connection
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
