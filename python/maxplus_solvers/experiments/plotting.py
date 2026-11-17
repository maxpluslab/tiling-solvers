"""Figures from benchmark records. Needs matplotlib, the ``analysis`` extra.

Each function takes records as :func:`benchmark.read` returns them, or for
:func:`regimes_at_a_glance` the rows of committed tables, and gives back a
matplotlib figure; nothing is shown or saved unless asked. The figures
are drawn off-screen, so they can be made on a machine without a display.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from matplotlib import rc_context
from matplotlib.figure import Figure


def _figure(title: str, xlabel: str, ylabel: str) -> tuple[Figure, Any]:
    # A Figure made directly, not through pyplot, has no window and no global state.
    figure = Figure(figsize=(7.0, 4.5), layout="constrained")
    axes = figure.add_subplot()
    axes.set_title(title)
    axes.set_xlabel(xlabel)
    axes.set_ylabel(ylabel)
    return figure, axes


def nodes_by_tolerance(
    records: Sequence[Mapping[str, Any]], *, metric: str = "nodes", whole_only: bool = True
) -> Figure:
    """A search count against the contact tolerance, one line per fixture.

    Footprint puzzles are drawn solid and relief puzzles dashed. Records that
    set solver options are left out, so that a line varies the tolerance and
    nothing else; with ``whole_only``, so are searches that were stopped.
    """
    lines: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for record in records:
        if record["status"] == "error" or record["config"]["options"]:
            continue
        if whole_only and not record["exhaustive"]:
            continue
        tolerance = record["config"]["tolerances"]["contactNoiseMm"]
        value = record["metrics"].get(metric)
        if value:
            lines.setdefault((record["fixture"], record["mode"]), []).append((tolerance, value))
    figure, axes = _figure(
        f"{metric} of the whole search against the contact tolerance",
        "contact tolerance, mm",
        metric,
    )
    for (fixture, mode), points in sorted(lines.items()):
        points.sort()
        axes.plot(
            [x for x, _ in points],
            [y for _, y in points],
            marker="o",
            markersize=3,
            linestyle="-" if mode == "footprint" else "--",
            label=fixture,
        )
    axes.set_xscale("log")
    axes.set_yscale("log")
    if lines:
        axes.legend(fontsize="x-small", ncols=2)
    return figure


def proxy_against_cost(
    table: Mapping[str, Mapping[str, float]], proxy: str, cost: str = "nodes"
) -> Figure:
    """One proxy against one cost, a labelled point per fixture that has both."""
    figure, axes = _figure(f"{cost} against {proxy}", proxy, cost)
    for fixture, row in sorted(table.items()):
        if proxy in row and cost in row:
            axes.scatter([row[proxy]], [row[cost]], s=18, color="tab:blue")
            axes.annotate(fixture, (row[proxy], row[cost]), fontsize="x-small")
    axes.set_yscale("log")
    return figure


GLANCE_SOLVER = "rust.contact_dfs"

# The series of the figure below, in drawing order: label, marker, filled.
GLANCE_SERIES = (
    ("flat, assuming nothing", "o", True),
    ("flat, stopped at the node limit (a lower bound)", ">", False),
    ("relief, assuming nothing", "s", True),
    ("flat, assuming edge to edge", "D", True),
)


def _glance_points(
    corpus_rows: Sequence[Mapping[str, str]], e2e_rows: Sequence[Mapping[str, str]]
) -> tuple[list[tuple[str, int]], dict[str, dict[str, int]]]:
    """Constructions with their piece counts, and nodes by series and construction."""

    def need(row: Mapping[str, str], *columns: str) -> None:
        missing = [c for c in columns if c not in row]
        if missing:
            raise ValueError(f"table row lacks the columns {missing}")

    def nodes(text: str) -> int:
        return int(text.replace(" ", ""))

    solver = f"`{GLANCE_SOLVER}`"
    pieces: dict[str, int] = {}
    series: dict[str, dict[str, int]] = {label: {} for label, _, _ in GLANCE_SERIES}
    for row in corpus_rows:
        need(row, "Fixture", "Pieces", "Solver", "Mode", "Whole search", "Nodes")
        if row["Solver"] != solver:
            continue
        construction = row["Fixture"].strip("`").removesuffix("-flat")
        pieces[construction] = int(row["Pieces"])
        if row["Mode"] == "relief":
            label = GLANCE_SERIES[2][0]
        elif row["Whole search"] == "yes":
            label = GLANCE_SERIES[0][0]
        else:
            label = GLANCE_SERIES[1][0]
        series[label][construction] = nodes(row["Nodes"])
    for row in e2e_rows:
        need(row, "Fixture", "Solver", "Mode", "assumes", "equal_edges", "wall_edges", "Nodes")
        chosen = (row["Solver"], row["Mode"], row["assumes"], row["equal_edges"], row["wall_edges"])
        if chosen == (solver, "footprint", "edge-to-edge", "true", "true"):
            construction = row["Fixture"].strip("`").removesuffix("-flat")
            series[GLANCE_SERIES[3][0]][construction] = nodes(row["Nodes"])
    order = sorted(pieces.items(), key=lambda item: (item[1], item[0]))
    return order, series


def regimes_at_a_glance(
    corpus_rows: Sequence[Mapping[str, str]], e2e_rows: Sequence[Mapping[str, str]]
) -> Figure:
    """Whole-search nodes of each construction, flat, with roofs, and flat assuming edge to edge.

    Takes the rows of the committed tables ``benchmarks/results/corpus.md`` and
    ``edge_to_edge.md`` as :func:`report.parse_markdown` reads them, so it needs no
    search. Only ``rust.contact_dfs`` is drawn, with both edge-to-edge rules on.
    A flat search stopped at the node limit is drawn as an open arrow at the limit:
    the true count is larger.
    """
    order, series = _glance_points(corpus_rows, e2e_rows)
    figure = Figure(figsize=(7.0, 0.32 * len(order) + 1.6), layout="constrained")
    axes = figure.add_subplot()
    axes.set_title("Search effort: roofs, and the edge-to-edge assumption", fontsize="medium")
    axes.set_xlabel(f"search-tree nodes of the whole search ({GLANCE_SOLVER}), log scale")
    rows = {construction: index for index, (construction, _) in enumerate(order)}
    axes.set_yticks(
        range(len(order)), [f"{construction} ({count})" for construction, count in order]
    )
    for construction, index in rows.items():
        values = [points[construction] for points in series.values() if construction in points]
        if values:
            axes.plot([min(values), max(values)], [index, index], color="0.85", zorder=1)
    for (label, marker, filled), color in zip(
        GLANCE_SERIES, ("tab:red", "tab:red", "tab:blue", "tab:green"), strict=True
    ):
        points = series[label]
        if not points:
            continue
        axes.scatter(
            [points[c] for c in points],
            [rows[c] for c in points],
            marker=marker,
            s=36,
            label=label,
            facecolors=color if filled else "none",
            edgecolors=color,
            zorder=2,
        )
    axes.set_xscale("log")
    axes.invert_yaxis()
    axes.set_ylabel("construction (pieces)")
    axes.grid(axis="x", color="0.92")
    axes.legend(fontsize="x-small", loc="upper right")
    return figure


def save(figure: Figure, path: Path) -> None:
    """Write a figure to a file; the suffix chooses the format.

    An SVG carries no date and a fixed id salt, so the same figure is the same file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".svg":
        with rc_context({"svg.hashsalt": "maxplus-solvers"}):
            figure.savefig(path, metadata={"Date": None})
    else:
        figure.savefig(path, dpi=150)
