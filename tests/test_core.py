from datetime import date
from decimal import Decimal

from core.pricing import PromoWindow, effective_unit_price, prorate_unit_price


def test_prorate_unit_price_applies_order_discount_half_up():
    # O-1006: a $60.00 hoodie with a 10% order discount is paid at $54.00.
    assert prorate_unit_price(Decimal("60.00"), Decimal("10")) == Decimal("54.00")


def test_effective_unit_price_applies_promo_active_on_sale_date():
    # PR-001: 20% off Classic Tee, 2026-05-01..2026-05-07.
    spring_tee_sale = PromoWindow(
        value_pct=Decimal("20"), start_date=date(2026, 5, 1), end_date=date(2026, 5, 7)
    )

    price = effective_unit_price(
        list_price=Decimal("25.00"),
        promotions=[spring_tee_sale],
        sale_date=date(2026, 5, 3),
    )

    assert price == Decimal("20.00")


def test_effective_unit_price_ignores_promo_outside_its_window():
    spring_tee_sale = PromoWindow(
        value_pct=Decimal("20"), start_date=date(2026, 5, 1), end_date=date(2026, 5, 7)
    )

    price = effective_unit_price(
        list_price=Decimal("25.00"),
        promotions=[spring_tee_sale],
        sale_date=date(2026, 6, 19),
    )

    assert price == Decimal("25.00")
