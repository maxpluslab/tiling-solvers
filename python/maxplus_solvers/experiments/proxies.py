"""Difficulty proxies: numbers read off an instance that might say how hard it is.

The static proxies come from the edge compatibility graph and the symmetries,
without any search:

* how many edges of other pieces, and of the tray, each piece edge could lie
  against (*degree*): the fewer, the more each edge says about its neighbour;
* the fraction of piece edges with exactly one such mate;
* how many ways the pieces can be exchanged or turned onto themselves, and the
  tray turned, without changing an assembly.

The dynamic ones come from a whole search and are read from a benchmark record:
the mean depth of its dead ends and the candidates it generated per node.

None of these is known to predict anything. They are here to be compared with
what the searches cost and with the difficulty rating the puzzle's source
publishes, which is what :func:`correlations` does.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from maxplus_solvers import _native
from maxplus_solvers.experiments.report import spearman
from maxplus_solvers.models import PuzzleInstance, Regime, TolerancePolicy


@dataclass(frozen=True, slots=True)
class StaticProxies:
    pieces: int
    edges: int
    # Over piece edges: edges of other pieces it is compatible with.
    mean_degree: float
    max_degree: int
    # Fraction of piece edges compatible with exactly one edge of another piece.
    unique_mate_fraction: float
    # Fraction compatible with no edge of another piece: they must lie on the tray.
    no_mate_fraction: float
    # Over piece edges: tray edges it could lie along.
    mean_tray_degree: float
    # Classes of congruent pieces, and the ways to exchange pieces within them.
    classes: int
    exchanges: int
    # Ways to turn pieces onto themselves, all pieces together.
    piece_turns: int
    # Rotations of the tray onto itself.
    tray_turns: int

    @property
    def symmetry_count(self) -> int:
        """Descriptions of one assembly that differ only by a symmetry."""
        return self.exchanges * self.piece_turns * self.tray_turns

    def to_dict(self) -> dict[str, float]:
        return {**asdict(self), "symmetry_count": self.symmetry_count}


def tray_turns(target: Sequence[Sequence[float]], tolerance_mm: float) -> int:
    """How many rotations about its centroid map a convex polygon onto itself.

    A rotation that does so permutes the vertices cyclically, so it is enough
    to try the turns by a whole number of vertices.
    """
    count = len(target)
    cx = sum(x for x, _ in target) / count
    cy = sum(y for _, y in target) / count
    # For a polygon with a rotational symmetry the vertex mean is its centre.
    turns = 0
    for shift in range(count):
        angle = math.atan2(target[shift][1] - cy, target[shift][0] - cx) - math.atan2(
            target[0][1] - cy, target[0][0] - cx
        )
        c, s = math.cos(angle), math.sin(angle)
        if all(
            math.hypot(
                cx + c * (x - cx) - s * (y - cy) - target[(i + shift) % count][0],
                cy + s * (x - cx) + c * (y - cy) - target[(i + shift) % count][1],
            )
            <= tolerance_mm
            for i, (x, y) in enumerate(target)
        ):
            turns += 1
    return turns


def static(
    instance: PuzzleInstance,
    tolerances: TolerancePolicy | None = None,
    *,
    edge_to_edge: bool = False,
) -> StaticProxies:
    """The static proxies of an instance, with the tolerances the solvers fit to.

    With ``edge_to_edge`` the edge graph is the one the search uses under that
    assumption, where a piece edge lies only against an equally long one.
    """
    policy = tolerances or TolerancePolicy.from_instance(instance)
    fit = policy.contact_noise_mm
    roofs = None
    if instance.regime is Regime.RELIEF:
        roofs = []
        for piece in instance.pieces:
            assert piece.roof is not None, "a relief instance has a roof on every piece"
            roofs.append((piece.roof.z0, piece.roof.gx, piece.roof.gy))
    polygons = [piece.polygon for piece in instance.pieces]
    assembly = _native.Assembly(
        instance.target,
        polygons,
        roofs,
        length_tol=fit,
        angle_tol=fit / instance.span_mm,
        slope_tol=fit / instance.span_mm,
        edge_to_edge=edge_to_edge,
    )
    degrees: list[int] = []
    tray_degrees: list[int] = []
    for piece, polygon in enumerate(polygons):
        for edge in range(len(polygon)):
            degrees.append(
                sum(
                    assembly.compatible(other, other_edge, piece, edge)
                    for other, other_polygon in enumerate(polygons)
                    if other != piece
                    for other_edge in range(len(other_polygon))
                )
            )
            tray_degrees.append(
                sum(
                    assembly.compatible(None, tray_edge, piece, edge)
                    for tray_edge in range(len(instance.target))
                )
            )
    classes = assembly.classes()
    sizes = [classes.count(first) for first in sorted(set(classes))]
    return StaticProxies(
        pieces=len(polygons),
        edges=len(degrees),
        mean_degree=sum(degrees) / len(degrees),
        max_degree=max(degrees),
        unique_mate_fraction=sum(d == 1 for d in degrees) / len(degrees),
        no_mate_fraction=sum(d == 0 for d in degrees) / len(degrees),
        mean_tray_degree=sum(tray_degrees) / len(tray_degrees),
        classes=len(sizes),
        exchanges=math.prod(math.factorial(size) for size in sizes),
        piece_turns=math.prod(assembly.symmetry()),
        tray_turns=tray_turns(instance.target, fit),
    )


def dynamic(record: Mapping[str, Any]) -> dict[str, float]:
    """The proxies a search leaves behind, from its benchmark record.

    Absent where the search made no node or no backtrack.
    """
    metrics = record.get("metrics", {})
    out: dict[str, float] = {}
    if metrics.get("backtracks"):
        out["mean_dead_end_depth"] = metrics["backtrack_depth"] / metrics["backtracks"]
        out["dead_end_depth_fraction"] = out["mean_dead_end_depth"] / record["pieces"]
    if metrics.get("nodes"):
        out["candidates_per_node"] = metrics["candidates_generated"] / metrics["nodes"]
        out["nodes"] = metrics["nodes"]
    return out


# Every number a fixture's row may carry: the static proxies, the dynamic ones, the
# source's rating and the cost itself.
PROXY_NAMES = frozenset(
    {
        "pieces",
        "edges",
        "mean_degree",
        "max_degree",
        "unique_mate_fraction",
        "no_mate_fraction",
        "mean_tray_degree",
        "classes",
        "exchanges",
        "piece_turns",
        "tray_turns",
        "symmetry_count",
        "mean_dead_end_depth",
        "dead_end_depth_fraction",
        "candidates_per_node",
        "nodes",
        "source_diversity",
        "source_rating",
    }
)


def correlations(
    table: Mapping[str, Mapping[str, float]], against: str
) -> list[tuple[str, float | None, int]]:
    """Rank correlation of every column of a table with one of them.

    ``table`` maps a fixture to its named numbers. Returns, for each other
    name, Spearman's coefficient over the fixtures that have both, and how
    many those are. With eight puzzles a coefficient is a description of
    eight points, not an estimate of anything.
    """
    out = []
    for name in sorted(PROXY_NAMES - {against}):
        pairs = [
            (row[name], row[against]) for row in table.values() if name in row and against in row
        ]
        xs, ys = [a for a, _ in pairs], [b for _, b in pairs]
        out.append((name, spearman(xs, ys), len(pairs)))
    return out
