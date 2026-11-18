"""The committed figure, ``docs/figures/at-a-glance.svg``, is drawn from the committed tables.

``maxplus-bench figure`` writes it from ``benchmarks/results/corpus.md`` and
``edge_to_edge.md``. The bytes are not compared, since the glyphs depend on the
matplotlib build. What is compared are the labels matplotlib writes into the SVG as
comments, and the points of a fresh drawing against values read off the tables by hand.
"""

import re
from pathlib import Path

import numpy as np
import pytest

from maxplus_solvers.experiments import plotting, report
from maxplus_solvers.experiments.cli import main
from support import corpus

RESULTS = corpus.ROOT / "benchmarks" / "results"
FIGURE = corpus.ROOT / "docs" / "figures" / "at-a-glance.svg"
CONSTRUCTIONS = sorted({f.removesuffix("-flat") for f in corpus.fixture_ids(kind="corpus")})


def read(name: str) -> list[dict[str, str]]:
    return report.parse_markdown((RESULTS / name).read_text(encoding="utf-8"))


def labels_in(svg: str) -> set[str]:
    return set(re.findall(r"<!-- (.*?) -->", svg))


def test_the_committed_figure_names_every_construction_and_series() -> None:
    labels = labels_in(FIGURE.read_text(encoding="utf-8"))
    pieces = {row["Fixture"].strip("`"): row["Pieces"] for row in read("corpus.md")}
    assert {f"{c} ({pieces[c]})" for c in CONSTRUCTIONS} <= labels
    assert {label for label, *_ in plotting.GLANCE_SERIES} <= labels


def test_the_committed_figure_is_what_the_command_draws_now(tmp_path: Path) -> None:
    out = tmp_path / "glance.svg"
    assert main(["figure", "--results", str(RESULTS), "--out", str(out)]) == 0
    assert labels_in(out.read_text(encoding="utf-8")) == labels_in(
        FIGURE.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    ("series", "construction", "nodes"),
    [
        # Read off benchmarks/results/corpus.md and edge_to_edge.md by hand.
        ("flat, assuming nothing", "new1", 1_064_878),
        ("relief, assuming nothing", "new1", 68),
        ("flat, assuming edge to edge", "new1", 49),
        ("relief, assuming nothing", "plt1", 21_973),
        ("relief, assuming edge to edge", "plt1", 749),
        ("relief, assuming edge to edge", "new1", 49),
        ("flat, stopped at the node limit (a lower bound)", "cor1", 1_500_000),
        ("flat, assuming edge to edge", "cor1", 44_539),
    ],
)
def test_the_figure_places_points_from_the_tables(
    series: str, construction: str, nodes: int
) -> None:
    (axes,) = plotting.regimes_at_a_glance(read("corpus.md"), read("edge_to_edge.md")).axes
    ticks = [label.get_text().split(" ")[0] for label in axes.get_yticklabels()]
    collection = next(c for c in axes.collections if c.get_label() == series)
    points = {ticks[round(y)]: x for x, y in np.asarray(collection.get_offsets(), dtype=float)}
    assert points[construction] == pytest.approx(nodes, abs=1e-9)
