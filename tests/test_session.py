from agent.session import SessionState, resolve_return_reference


def test_resolve_return_reference_fills_in_from_last_single_line_sale():
    session = SessionState()
    session.record_sale(
        order_id="O-1016",
        lines=[{"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 1}],
    )

    resolved = resolve_return_reference(
        session, order_id=None, product_name=None, color=None, size=None
    )

    assert resolved == {
        "order_id": "O-1016",
        "product_name": "Canvas Tote",
        "color": None,
        "size": None,
        "inferred": True,
    }


def test_resolve_return_reference_refuses_to_guess_after_multi_line_sale():
    session = SessionState()
    session.record_sale(
        order_id="O-1016",
        lines=[
            {"product_name": "Classic Tee", "color": "Blue", "size": "Medium", "quantity": 2},
            {"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 1},
        ],
    )

    resolved = resolve_return_reference(
        session, order_id=None, product_name=None, color=None, size=None
    )

    assert resolved is None


def test_resolve_return_reference_never_overrides_explicit_values():
    session = SessionState()
    session.record_sale(
        order_id="O-1001",
        lines=[{"product_name": "Classic Tee", "color": "Blue", "size": "Medium", "quantity": 1}],
    )

    # Explicitly returning a DIFFERENT, older order — must not get pulled
    # toward the most recent sale's order/product just because it exists.
    resolved = resolve_return_reference(
        session, order_id="O-1006", product_name="Canvas Tote", color=None, size=None
    )

    assert resolved == {
        "order_id": "O-1006",
        "product_name": "Canvas Tote",
        "color": None,
        "size": None,
        "inferred": False,
    }
