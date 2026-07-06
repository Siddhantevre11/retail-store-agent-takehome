from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from core.money import round_half_up


def prorate_unit_price(unit_price: Decimal, order_discount_pct: Decimal) -> Decimal:
    """Rule 2: unit price actually paid after a whole-order discount."""
    factor = (Decimal(100) - order_discount_pct) / Decimal(100)
    return round_half_up(unit_price * factor)


@dataclass(frozen=True)
class PromoWindow:
    value_pct: Decimal
    start_date: date
    end_date: date


def effective_unit_price(
    list_price: Decimal, promotions: Sequence[PromoWindow], sale_date: date
) -> Decimal:
    """Rule 5: lowest price among promotions active (inclusive) on sale_date."""
    prices = [list_price]
    for promo in promotions:
        if promo.start_date <= sale_date <= promo.end_date:
            factor = (Decimal(100) - promo.value_pct) / Decimal(100)
            prices.append(round_half_up(list_price * factor))
    return min(prices)
