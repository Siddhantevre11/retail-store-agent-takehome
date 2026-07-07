import sqlite3
from pathlib import Path

import pytest

from db.loader import bootstrap_db

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture
def db_conn():
    conn = bootstrap_db(DATA_DIR)
    yield conn
    conn.close()


class FlakyConnProxy:
    """Delegates to a real sqlite3.Connection, injecting a failure on the
    Nth matching statement — sqlite3.Connection.execute is a read-only slot
    on a C-level type and can't be patched directly, so this simulates a
    real mid-transaction failure (disk full, connection drop) at the DB
    boundary while still exercising the real connection's actual
    commit/rollback behavior for everything that already went through.
    """

    def __init__(self, real_conn, fail_sql_prefix, fail_on_nth):
        self._real = real_conn
        self._fail_sql_prefix = fail_sql_prefix
        self._fail_on_nth = fail_on_nth
        self._matching_call_count = 0

    def execute(self, sql, *args, **kwargs):
        if sql.strip().startswith(self._fail_sql_prefix):
            self._matching_call_count += 1
            if self._matching_call_count == self._fail_on_nth:
                raise sqlite3.OperationalError("simulated mid-write failure")
        return self._real.execute(sql, *args, **kwargs)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc_info):
        return self._real.__exit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._real, name)
