def format_result_table(columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "(no rows)"

    try:
        from tabulate import tabulate

        return tabulate(rows, headers=columns, tablefmt="psql")
    except ImportError:
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join("" if value is None else str(value) for value in row))
        return "\n".join(lines)
