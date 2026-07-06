from tools.restocking import get_stockout_report


def test_get_stockout_report_flags_only_tote_on_seed_data(db_conn):
    report = get_stockout_report(db_conn)

    skus = {row["sku"] for row in report}
    assert skus == {"TOTE"}
