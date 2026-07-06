from pathlib import Path

from db.loader import bootstrap_db

DATA_DIR = Path(__file__).parent.parent / "data"


def test_bootstrap_db_loads_seed_data():
    conn = bootstrap_db(DATA_DIR)

    row = conn.execute(
        "SELECT product_name FROM products WHERE sku = ?", ("TEE-BLU-M",)
    ).fetchone()

    assert row["product_name"] == "Classic Tee"
