from contextlib import contextmanager


@contextmanager
def transaction(connection):
    if connection.in_transaction:
        raise RuntimeError('nested archive transaction')
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
