from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def round_half_up(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)
