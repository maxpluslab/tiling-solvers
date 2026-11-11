"""Tables from benchmark records.

A table is Markdown, one row per run. With ``times=False`` it holds only what
a deterministic solver reproduces exactly: statuses, solution counts and search
counts. That is the form to commit and to compare; times belong to a machine.
"""

from collections.abc import Mapping, Sequence
from typing import Any

# CP-SAT's own counts depend on the OR-Tools build, so they are reported with the times.
_MACHINE_METRICS = ("sat_branches", "sat_conflicts")


def _count(value: Any) -> str:
    return "" if value is None else f"{value:,}".replace(",", " ")


def _seconds(value: Any) -> str:
    return "" if value is None else f"{value:.3g}"


def _ratio(top: Any, bottom: Any) -> str:
    if not top or not bottom:
        return ""
    return f"{top / bottom:.2f}"


def varied(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """Names of the settings that differ between records: the factors of the experiment.

    Option names, then ``seed`` and ``contactScale`` if they vary.
    """
    every = sorted({name for record in records for name in record["config"]["options"]})
    names = [
        name
        for name in every
        if len({repr(record["config"]["options"].get(name)) for record in records}) > 1
    ]
    if len({record["config"]["seed"] for record in records}) > 1:
        names.append("seed")
    if len({record["contactScale"] for record in records}) > 1:
        names.append("contactScale")
    return names


def _setting(record: Mapping[str, Any], name: str) -> str:
    if name == "seed":
        return str(record["config"]["seed"])
    if name == "contactScale":
        return f"{record['contactScale']:g}"
    value = record["config"]["options"].get(name)
    if value is None:
        return ""
    return str(value).lower() if isinstance(value, bool) else str(value)


def rows(records: Sequence[Mapping[str, Any]], *, times: bool = True) -> list[list[str]]:
    """The table as cells, header first."""
    factors = varied(records)
    header = ["Fixture", "Pieces", "Solver", "Mode", *factors]
    header += ["Status", "Whole search", "Solutions", "Valid", "Nodes", "Backtracks"]
    header += ["Mean dead-end depth", "Candidates per node"]
    if times:
        header += ["SAT conflicts", "First solution, s", "Total, s"]
    table = [header]
    for record in records:
        metrics = record.get("metrics", {})
        row = [
            f"`{record['fixture']}`",
            str(record["pieces"]),
            f"`{record['solver']}`",
            record["mode"],
            *(_setting(record, name) for name in factors),
            record["status"],
        ]
        if record["status"] == "error":
            row += [""] * (len(header) - len(row))
            table.append(row)
            continue
        valid = record.get("validSolutions")
        row += [
            "yes" if record["exhaustive"] else "no",
            _count(record["solutions"]),
            "" if valid is None else _count(valid),
            _count(metrics.get("nodes")),
            _count(metrics.get("backtracks")),
            _ratio(metrics.get("backtrack_depth"), metrics.get("backtracks")),
            _ratio(metrics.get("candidates_generated"), metrics.get("nodes")),
        ]
        if times:
            row += [
                _count(metrics.get(_MACHINE_METRICS[1])),
                _seconds(metrics.get("first_solution_s")),
                _seconds(metrics.get("wall_time_s")),
            ]
        table.append(row)
    return table


def markdown(cells: Sequence[Sequence[str]]) -> str:
    """Cells as a Markdown table, header first."""
    header, *body = cells
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines) + "\n"


def table(records: Sequence[Mapping[str, Any]], *, times: bool = True) -> str:
    """The results table of an experiment, as Markdown."""
    return markdown(rows(records, times=times))


def ranks(values: Sequence[float]) -> list[float]:
    """Ranks from 1, ties sharing the mean of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            out[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman's rank correlation, or ``None`` when either side is constant or too short.

    The Pearson correlation of the ranks, which is the definition that stays
    right with ties.
    """
    if len(xs) != len(ys):
        raise ValueError("two samples of different sizes")
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True)) / (sxx * syy) ** 0.5
