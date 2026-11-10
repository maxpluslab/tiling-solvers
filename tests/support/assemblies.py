"""Comparing assemblies as sets of placed polygons, independently of ``maxplus_solvers`` geometry.

Two assemblies are the same when they put the same polygons in the same
places, whichever piece is which and whatever pose produced each polygon. That
is the right notion for a solver that treats congruent pieces as
interchangeable, and for comparing its answer with an answer key.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from support import geometry

Polygon = Sequence[Sequence[float]]

# Millimetres. Far above rounding, far below any feature of a puzzle.
SAME_MM = 1e-6


def world(instance: Mapping[str, Any], poses: Mapping[str, Mapping[str, float]]) -> list[Polygon]:
    """Every piece of an instance document where the poses put it."""
    return [geometry.place_polygon(p["polygon"], poses[p["id"]]) for p in instance["pieces"]]


def same(a: Sequence[Polygon], b: Sequence[Polygon], tol: float = SAME_MM) -> bool:
    """Whether the two lists hold the same polygons, in any order."""
    if len(a) != len(b):
        return False
    remaining = list(b)
    for polygon in a:
        match = next((q for q in remaining if geometry.same_polygon(polygon, q, tol)), None)
        if match is None:
            return False
        remaining.remove(match)
    return True


def turned(polygons: Sequence[Polygon], angle: float, about: Sequence[float]) -> list[Polygon]:
    """The whole assembly rotated about a point."""
    c, s = math.cos(angle), math.sin(angle)
    cx, cy = about
    return [
        [(cx + c * (x - cx) - s * (y - cy), cy + s * (x - cx) + c * (y - cy)) for x, y in polygon]
        for polygon in polygons
    ]


def tray_turns(target: Polygon) -> list[float]:
    """The rotations about its centroid that map the target onto itself, 0 included."""
    n = len(target)
    centre = geometry.centroid(target)
    return [
        2 * math.pi * k / n
        for k in range(n)
        if geometry.same_polygon(turned([target], 2 * math.pi * k / n, centre)[0], target, SAME_MM)
    ]


def orbits(target: Polygon, found: Sequence[Sequence[Polygon]]) -> list[list[int]]:
    """Group assemblies that are rotations of one another with the tray. Indices into ``found``."""
    centre = geometry.centroid(target)
    turns = tray_turns(target)
    groups: list[list[int]] = []
    for index, assembly in enumerate(found):
        for group in groups:
            first = found[group[0]]
            if any(same(turned(assembly, turn, centre), first) for turn in turns):
                group.append(index)
                break
        else:
            groups.append([index])
    return groups
