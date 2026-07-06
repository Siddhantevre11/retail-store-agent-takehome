from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence


@dataclass(frozen=True)
class MarginLine:
    product_id: str
    net_quantity: int
    unit_price_paid: Decimal
    unit_cost: Decimal


def compute_product_margins(lines: Sequence[MarginLine]) -> dict:
    """Rule 6: revenue minus cost, per product, over already-net quantities.

    net_quantity excludes any good-condition-returned units up front (see
    tools/margin.py), so a returned-and-restocked unit is simply absent from
    both the revenue and cost side here — never counted, never netted after.
    """
    totals = defaultdict(lambda: Decimal("0"))
    for line in lines:
        totals[line.product_id] += line.net_quantity * (line.unit_price_paid - line.unit_cost)
    return dict(totals)
