from pathlib import Path

import pytest

from db.loader import bootstrap_db

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture
def db_conn():
    conn = bootstrap_db(DATA_DIR)
    yield conn
    conn.close()
