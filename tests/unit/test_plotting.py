"""Figures from records: what is drawn, read back from the figure. Nothing is shown."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from maxplus_solvers.experiments import plotting


def record_of(fixture: str, mode: str, tolerance: float, nodes: int, **more: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fixture": fixture,
        "mode": mode,
        "status": "solved",
        "exhaustive": True,
        "config": {"options": {}, "tolerances": {"contactNoiseMm": tolerance}},
        "metrics": {"nodes": nodes},
    }
    record.update(more)
    return record


def values(data: Any) -> list[Any]:
    return np.asarray(data, dtype=float).tolist()


RECORDS = [
    record_of("a-flat", "footprint", 1e-2, 500),
    record_of("a-flat", "footprint", 1e-4, 100),
    record_of("a", "relief", 1e-4, 20),
    record_of("a", "relief", 1e-2, 20),
    # Left out: stopped, an error, and a run that set an option.
    record_of("a-flat", "footprint", 1.0, 9_999, exhaustive=False),
    record_of("a-flat", "footprint", 1.0, 0, status="error"),
    record_of(
        "a", "relief", 1e-3, 77, config={"options": {"x": 1}, "tolerances": {"contactNoiseMm": 1}}
    ),
]


def test_a_line_per_fixture_in_order_of_tolerance() -> None:
    figure = plotting.nodes_by_tolerance(RECORDS)
    (axes,) = figure.axes
    lines = {str(line.get_label()): line for line in axes.get_lines()}
    assert sorted(lines) == ["a", "a-flat"]
    assert values(lines["a-flat"].get_xdata()) == [1e-4, 1e-2]
    assert values(lines["a-flat"].get_ydata()) == [100, 500]
    assert values(lines["a"].get_ydata()) == [20, 20]
    # Footprints solid, reliefs dashed; both axes logarithmic.
    assert lines["a-flat"].get_linestyle() == "-" and lines["a"].get_linestyle() == "--"
    assert (axes.get_xscale(), axes.get_yscale()) == ("log", "log")
    assert axes.get_xlabel() == "contact tolerance, mm"


def test_stopped_searches_can_be_drawn_when_asked() -> None:
    figure = plotting.nodes_by_tolerance(RECORDS, whole_only=False)
    lines = {str(line.get_label()): line for line in figure.axes[0].get_lines()}
    assert values(lines["a-flat"].get_ydata()) == [100, 500, 9_999]


def test_no_records_is_an_empty_figure_and_not_an_error() -> None:
    figure = plotting.nodes_by_tolerance([])
    assert figure.axes[0].get_lines() == [] or len(figure.axes[0].get_lines()) == 0
    assert figure.axes[0].get_legend() is None


def test_a_proxy_is_drawn_against_a_cost_for_the_fixtures_that_have_both() -> None:
    table = {
        "a": {"mean_degree": 2.0, "nodes": 10.0},
        "b": {"mean_degree": 5.0, "nodes": 1000.0},
        "c": {"mean_degree": 9.0},
    }
    figure = plotting.proxy_against_cost(table, "mean_degree")
    (axes,) = figure.axes
    points = sorted(tuple(values(collection.get_offsets())[0]) for collection in axes.collections)
    assert points == [(2.0, 10.0), (5.0, 1000.0)]
    assert sorted(text.get_text() for text in axes.texts) == ["a", "b"]
    assert (axes.get_xlabel(), axes.get_ylabel()) == ("mean_degree", "nodes")


# --- the figure at a glance, from rows of the committed tables ----------------------------


def corpus_row(fixture: str, pieces: int, mode: str, whole: str, nodes: str) -> dict[str, str]:
    return {
        "Fixture": f"`{fixture}`",
        "Pieces": str(pieces),
        "Solver": "`rust.contact_dfs`",
        "Mode": mode,
        "Whole search": whole,
        "Nodes": nodes,
    }


def e2e_row(fixture: str, mode: str, equal: str, wall: str, nodes: str) -> dict[str, str]:
    return {
        "Fixture": f"`{fixture}`",
        "Solver": "`rust.contact_dfs`",
        "Mode": mode,
        "assumes": "edge-to-edge",
        "equal_edges": equal,
        "wall_edges": wall,
        "Nodes": nodes,
    }


# Rows in the shape report.parse_markdown gives: one construction whose flat search
# ended, one stopped at the limit, and rows the figure must ignore.
CORPUS_ROWS = [
    corpus_row("a", 4, "relief", "yes", "12"),
    corpus_row("a-flat", 4, "footprint", "yes", "1 234"),
    corpus_row("b", 9, "relief", "yes", "300"),
    corpus_row("b-flat", 9, "footprint", "no", "1 500 000"),
    {**corpus_row("a-flat", 4, "footprint", "yes", "7"), "Solver": "`cp_sat.placements`"},
]
E2E_ROWS = [
    e2e_row("a-flat", "footprint", "true", "true", "20"),
    e2e_row("a-flat", "footprint", "false", "true", "99"),  # one rule off: not drawn
    e2e_row("b-flat", "footprint", "true", "true", "5 000"),
    e2e_row("b", "relief", "true", "true", "77"),
    e2e_row("b", "relief", "true", "false", "88"),  # one rule off: not drawn
]


def test_the_glance_draws_each_construction_in_its_three_regimes() -> None:
    (axes,) = plotting.regimes_at_a_glance(CORPUS_ROWS, E2E_ROWS).axes
    series = {str(c.get_label()): values(c.get_offsets()) for c in axes.collections}
    # Rows go by pieces: a (4 pieces) at y 0, b (9) at y 1. Flat points sit 0.15 below
    # the row (larger y, the axis is inverted), relief 0.15 above. Values from the rows above.
    expected = {
        "flat, assuming nothing": [[1234, 0.15]],
        "flat, stopped at the node limit (a lower bound)": [[1_500_000, 1.15]],
        "flat, assuming edge to edge": [[20, 0.15], [5000, 1.15]],
        "relief, assuming nothing": [[12, -0.15], [300, 0.85]],
        "relief, assuming edge to edge": [[77, 0.85]],
    }
    assert sorted(series) == sorted(expected)
    for label, points in expected.items():
        assert series[label] == [pytest.approx(p, abs=1e-12) for p in points], label
    assert [label.get_text() for label in axes.get_yticklabels()] == ["a (4)", "b (9)"]
    assert axes.get_xscale() == "log"


def test_a_stopped_search_is_an_open_marker() -> None:
    (axes,) = plotting.regimes_at_a_glance(CORPUS_ROWS, E2E_ROWS).axes
    stopped = next(c for c in axes.collections if "lower bound" in str(c.get_label()))
    assert len(stopped.get_facecolor()) == 0  # facecolors "none"
    assert len(stopped.get_edgecolor()) == 1


def test_the_glance_refuses_a_table_without_its_columns() -> None:
    broken = [{k: v for k, v in CORPUS_ROWS[0].items() if k != "Whole search"}]
    with pytest.raises(ValueError, match="Whole search"):
        plotting.regimes_at_a_glance(broken, E2E_ROWS)


def test_an_svg_is_the_same_file_when_drawn_twice(tmp_path: Path) -> None:
    first, second = tmp_path / "1.svg", tmp_path / "2.svg"
    plotting.save(plotting.regimes_at_a_glance(CORPUS_ROWS, E2E_ROWS), first)
    plotting.save(plotting.regimes_at_a_glance(CORPUS_ROWS, E2E_ROWS), second)
    assert first.read_bytes() == second.read_bytes()
    assert b"<dc:date>" not in first.read_bytes()


@pytest.mark.parametrize("suffix", [".png", ".svg"])
def test_a_figure_is_saved_where_asked(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / "figures" / f"nodes{suffix}"
    plotting.save(plotting.nodes_by_tolerance(RECORDS), path)
    assert path.stat().st_size > 1_000
