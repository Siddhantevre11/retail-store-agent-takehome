CREATE TABLE products (
    sku TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL DEFAULT '',
    retail_price TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    joined_date TEXT NOT NULL
);

CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    supplier_name TEXT NOT NULL
);

CREATE TABLE supplier_catalog (
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
    product_id TEXT NOT NULL,
    unit_cost TEXT NOT NULL,
    lead_time_days INTEGER NOT NULL,
    PRIMARY KEY (supplier_id, product_id)
);

CREATE TABLE inventory (
    sku TEXT PRIMARY KEY REFERENCES products(sku),
    on_hand_qty INTEGER NOT NULL,
    reorder_point INTEGER NOT NULL,
    reorder_qty INTEGER NOT NULL
);

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    order_date TEXT NOT NULL,
    customer_id TEXT REFERENCES customers(customer_id),
    order_discount_pct TEXT NOT NULL DEFAULT '0',
    payment_method TEXT NOT NULL
);

CREATE TABLE order_lines (
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    line_no INTEGER NOT NULL,
    sku TEXT NOT NULL REFERENCES products(sku),
    quantity INTEGER NOT NULL,
    unit_price TEXT NOT NULL,
    PRIMARY KEY (order_id, line_no)
);

CREATE TABLE returns (
    return_id TEXT PRIMARY KEY,
    return_date TEXT NOT NULL,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    sku TEXT NOT NULL REFERENCES products(sku),
    quantity INTEGER NOT NULL,
    condition TEXT NOT NULL,
    refund_amount TEXT NOT NULL
);

CREATE TABLE promotions (
    promo_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    type TEXT NOT NULL,
    value TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL
);

-- Invented (not in source CSVs) — see CONTEXT.md "Purchase Order".
-- purchase_order_lines is keyed on sku, not product_id: the reorder_point/
-- reorder_qty signal that drives restocking lives on inventory, keyed by sku.
CREATE TABLE purchase_orders (
    po_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE purchase_order_lines (
    po_id TEXT NOT NULL REFERENCES purchase_orders(po_id),
    line_no INTEGER NOT NULL,
    sku TEXT NOT NULL REFERENCES products(sku),
    quantity_ordered INTEGER NOT NULL,
    quantity_received INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (po_id, line_no)
);
