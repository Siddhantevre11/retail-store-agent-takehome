def next_sequential_id(conn, table, id_column, prefix, start):
    """Generate the next id in a table's "PREFIX-NNNN" sequence."""
    rows = conn.execute(f"SELECT {id_column} FROM {table}").fetchall()
    max_n = start
    for row in rows:
        try:
            max_n = max(max_n, int(row[id_column].split("-")[1]))
        except (IndexError, ValueError):
            pass
    return f"{prefix}-{max_n + 1}"
