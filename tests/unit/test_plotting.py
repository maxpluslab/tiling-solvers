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


@pytest.mark.parametrize("suffix", [".png", ".svg"])
def test_a_figure_is_saved_where_asked(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / "figures" / f"nodes{suffix}"
    plotting.save(plotting.nodes_by_tolerance(RECORDS), path)
    assert path.stat().st_size > 1_000
