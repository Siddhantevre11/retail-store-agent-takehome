class SessionState:
    def __init__(self):
        self.last_order_id = None
        self.last_single_line_ref = None

    def record_sale(self, order_id, lines):
        self.last_order_id = order_id
        if len(lines) == 1:
            line = lines[0]
            self.last_single_line_ref = {
                "order_id": order_id,
                "product_name": line["product_name"],
                "color": line.get("color"),
                "size": line.get("size"),
            }
        else:
            self.last_single_line_ref = None


def resolve_return_reference(session, order_id, product_name, color, size):
    """Fill in a missing order_id/product_name from the last single-line
    sale — never overrides a value that was actually supplied, and never
    infers from a multi-line sale (last_single_line_ref is None then).

    Returns the resolved args (with inferred: bool), or None if something's
    missing with no unambiguous candidate to fall back on — the caller
    should ask for clarification rather than guess.
    """
    if order_id is not None and product_name is not None:
        return {
            "order_id": order_id,
            "product_name": product_name,
            "color": color,
            "size": size,
            "inferred": False,
        }

    ref = session.last_single_line_ref
    if ref is None:
        return None

    return {
        "order_id": order_id if order_id is not None else ref["order_id"],
        "product_name": product_name if product_name is not None else ref["product_name"],
        "color": color if color is not None else ref["color"],
        "size": size if size is not None else ref["size"],
        "inferred": True,
    }
