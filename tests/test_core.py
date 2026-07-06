from datetime import date
from decimal import Decimal

from core.pricing import PromoWindow, effective_unit_price, prorate_unit_price
from core.margin import MarginLine, compute_product_margins
from core.restocking import SupplierOption, days_of_cover, select_supplier


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


def test_select_supplier_picks_cheapest_within_lead_time_for_tote():
    # Northwind 7.00/7d vs Pioneer 6.50/14d — Pioneer is cheaper but too slow.
    options = [
        SupplierOption(supplier_id="SUP-NW", unit_cost=Decimal("7.00"), lead_time_days=7),
        SupplierOption(supplier_id="SUP-PG", unit_cost=Decimal("6.50"), lead_time_days=14),
    ]

    assert select_supplier(options).supplier_id == "SUP-NW"


def test_select_supplier_picks_cheapest_within_lead_time_for_mug():
    # Northwind 5.00/7d vs Pioneer 4.50/10d — Pioneer is cheaper and still eligible.
    options = [
        SupplierOption(supplier_id="SUP-NW", unit_cost=Decimal("5.00"), lead_time_days=7),
        SupplierOption(supplier_id="SUP-PG", unit_cost=Decimal("4.50"), lead_time_days=10),
    ]

    assert select_supplier(options).supplier_id == "SUP-PG"


def test_days_of_cover_for_tote():
    # TOTE: on_hand 4, sold 10 in May -> 4 / (10/30) = 12 days.
    assert days_of_cover(on_hand_qty=4, monthly_units=10) == Decimal("12")


def test_days_of_cover_is_none_when_nothing_sold():
    assert days_of_cover(on_hand_qty=40, monthly_units=0) is None


def test_compute_product_margins_sums_net_revenue_minus_cost_per_product():
    lines = [
        MarginLine(
            product_id="P-MUG", net_quantity=10, unit_price_paid=Decimal("12.00"), unit_cost=Decimal("5.00")
        ),
        MarginLine(
            product_id="P-TOTE", net_quantity=1, unit_price_paid=Decimal("18.00"), unit_cost=Decimal("7.00")
        ),
    ]

    margins = compute_product_margins(lines)

    assert margins == {"P-MUG": Decimal("70.00"), "P-TOTE": Decimal("11.00")}
