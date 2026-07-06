from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence


@dataclass(frozen=True)
class SupplierOption:
    supplier_id: str
    unit_cost: Decimal
    lead_time_days: int


def select_supplier(options: Sequence[SupplierOption]) -> Optional[SupplierOption]:
    """Rule 4: cheapest unit_cost among suppliers with lead_time_days <= 10."""
    eligible = [o for o in options if o.lead_time_days <= 10]
    if not eligible:
        return None
    return min(eligible, key=lambda o: o.unit_cost)


def days_of_cover(on_hand_qty: int, monthly_units: int) -> Optional[Decimal]:
    """Rule 7: on_hand / (monthly_units / 30). None (undefined/infinite) if
    nothing sold — can't run out of stock you aren't selling."""
    if monthly_units == 0:
        return None
    exact = Decimal(on_hand_qty) / (Decimal(monthly_units) / Decimal(30))
    return exact.quantize(Decimal("0.01"))
