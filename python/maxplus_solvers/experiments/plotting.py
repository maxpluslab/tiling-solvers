"""Figures from benchmark records. Needs matplotlib, the ``analysis`` extra.

Each function takes records as :func:`benchmark.read` returns them and gives
back a matplotlib figure; nothing is shown or saved unless asked. The figures
are drawn off-screen, so they can be made on a machine without a display.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

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


def save(figure: Figure, path: Path) -> None:
    """Write a figure to a file; the suffix chooses the format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
