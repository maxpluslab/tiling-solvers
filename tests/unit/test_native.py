"""Smoke tests for the Python -> _native -> tiling-geometry -> tiling-core chain."""

import pytest

import maxplus_solvers
from maxplus_solvers import _native

UNIT_SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def test_version_matches_the_package() -> None:
    assert _native.version() == maxplus_solvers.__version__
    assert maxplus_solvers.__version__.count(".") == 2


def test_signed_area_is_positive_counter_clockwise() -> None:
    assert _native.signed_area(UNIT_SQUARE) == pytest.approx(1.0)
    assert _native.signed_area(UNIT_SQUARE[::-1]) == pytest.approx(-1.0)


def test_signed_area_accepts_tuples() -> None:
    assert _native.signed_area([(0, 0), (4, 0), (0, 3)]) == pytest.approx(6.0)
