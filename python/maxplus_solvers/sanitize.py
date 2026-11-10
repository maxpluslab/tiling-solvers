"""Turn a solved assembly into a solver instance and a separate answer key.

A source puzzle gives the answer away in more ways than its reference poses:

* each piece is stored in its solved orientation;
* piece ids and piece order follow the construction;
* each polygon's vertex list starts at a construction-dependent corner.

``sanitize`` removes all of them: a seeded random rotation per piece (the roof
gradient turns with it), a random starting vertex, a shuffle, and opaque ids.
The reference poses are carried through the same transformation into an
:class:`AnswerKey`, which only tests and diagnostics may read.

The seed is itself part of the answer, because the rotations can be recomputed
from it. It is recorded in the key and never in the instance.
"""

import hashlib
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from maxplus_solvers import _polygon
from maxplus_solvers._polygon import Vec2
from maxplus_solvers.models import (
    Piece,
    Pose,
    PuzzleInstance,
    Regime,
    Roof,
    Rules,
    SourceRef,
    ValidationConstants,
)

SANITIZER_VERSION = 1

# A stored polygon must differ from its solved orientation by at least this
# fraction of its circumradius, measured between vertex sets. The measure is
# geometric so that it accounts for symmetry: a square turned by 90 degrees is
# still in its solved orientation. 0.15 corresponds to a turn of about 9 degrees.
MIN_DISPLACEMENT = 0.15
_MAX_ATTEMPTS = 1000


@dataclass(frozen=True, slots=True)
class SolvedPiece:
    """A piece together with where it goes."""

    source_id: str
    polygon: tuple[Vec2, ...]
    pose: Pose
    roof: Roof | None = None


@dataclass(frozen=True, slots=True)
class SolutionCount:
    """A solution count known by construction, with the convention it is counted under.

    ``assemblies`` counts distinct tilings of the target, pieces unlabelled.
    ``canonical`` counts them up to rotations of the target onto itself. Both are
    statements about exact geometry; a tolerant check may accept more.
    """

    canonical: int
    assemblies: int

    def to_dict(self) -> dict[str, int]:
        return {"canonical": self.canonical, "assemblies": self.assemblies}


@dataclass(frozen=True, slots=True)
class SolvedAssembly:
    """A puzzle with its answer, before sanitization. Never handed to a solver."""

    id: str
    target: tuple[Vec2, ...]
    pieces: tuple[SolvedPiece, ...]
    span_mm: float
    validation: ValidationConstants
    relief_mm: float | None = None
    rules: Rules = field(default_factory=Rules)
    source: SourceRef | None = None
    tropical: Mapping[str, Any] | None = None
    solution_count: SolutionCount | None = None

    @property
    def has_roofs(self) -> bool:
        return all(p.roof is not None for p in self.pieces)


@dataclass(frozen=True, slots=True)
class AnswerKey:
    """Reference poses for a sanitized instance. For tests and diagnostics only."""

    instance_id: str
    instance_hash: str
    seed: int
    poses: Mapping[str, Pose]
    source_ids: Mapping[str, str]
    solution_count: SolutionCount | None = None
    sanitizer_version: int = SANITIZER_VERSION

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "instanceId": self.instance_id,
            "instanceHash": self.instance_hash,
            "sanitizer": {"version": self.sanitizer_version, "seed": self.seed},
            "poses": {pid: pose.to_dict() for pid, pose in self.poses.items()},
            "sourceIds": dict(self.source_ids),
        }
        if self.solution_count is not None:
            out["solutionCount"] = self.solution_count.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        count = data.get("solutionCount")
        return cls(
            instance_id=data["instanceId"],
            instance_hash=data["instanceHash"],
            seed=data["sanitizer"]["seed"],
            poses={pid: Pose.from_dict(p) for pid, p in data["poses"].items()},
            source_ids=dict(data["sourceIds"]),
            solution_count=None if count is None else SolutionCount(**count),
            sanitizer_version=data["sanitizer"]["version"],
        )


def derive_seed(base_seed: int, puzzle_id: str) -> int:
    """A per-puzzle seed, so that a puzzle and its flat twin get unrelated rotations."""
    digest = hashlib.sha256(f"{base_seed}:{puzzle_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def vertex_set_distance(a: tuple[Vec2, ...], b: tuple[Vec2, ...]) -> float:
    """Hausdorff distance between two vertex sets."""

    def one_way(p: tuple[Vec2, ...], q: tuple[Vec2, ...]) -> float:
        return max(min(math.dist(u, v) for v in q) for u in p)

    return max(one_way(a, b), one_way(b, a))


def _wrap_angle(theta: float) -> float:
    """Reduce an angle to (-pi, pi]."""
    wrapped = math.remainder(theta, 2.0 * math.pi)
    return math.pi if wrapped == -math.pi else wrapped


def _draw_rotation(rng: random.Random, polygon: tuple[Vec2, ...]) -> float:
    """An angle that takes ``polygon`` visibly away from itself, whatever its symmetry."""
    threshold = MIN_DISPLACEMENT * max(math.hypot(x, y) for x, y in polygon)
    for _ in range(_MAX_ATTEMPTS):
        angle = rng.random() * 2.0 * math.pi
        turned = tuple(_polygon.rotate(p, angle) for p in polygon)
        if vertex_set_distance(turned, polygon) >= threshold:
            return angle
    raise ValueError("no rotation moves this polygon away from itself; is it nearly a circle?")


def _shuffled(rng: random.Random, n: int) -> list[int]:
    """Fisher-Yates on ``random()`` alone, the one stream Python keeps stable across versions."""
    order = list(range(n))
    for i in range(n - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        order[i], order[j] = order[j], order[i]
    return order


def sanitize(
    solved: SolvedAssembly, seed: int, regime: Regime | str | None = None
) -> tuple[PuzzleInstance, AnswerKey]:
    """Build the instance a solver may see, and the key that tests may see.

    ``regime`` defaults to relief when every piece has a roof and footprint
    otherwise. The same seed gives the same geometry in every regime, so the
    regimes of one puzzle differ only in the information attached.
    """
    if regime is None:
        regime = Regime.RELIEF if solved.has_roofs else Regime.FOOTPRINT
    regime = Regime(regime)
    if regime is not Regime.FOOTPRINT and not solved.has_roofs:
        raise ValueError(f"{solved.id}: the {regime} regime needs a roof on every piece")
    if regime is Regime.TROPICAL_AWARE and solved.tropical is None:
        raise ValueError(f"{solved.id}: no construction data for the tropical-aware regime")

    rng = random.Random(derive_seed(seed, solved.id))
    width = max(2, len(str(len(solved.pieces) - 1)))

    turned: list[tuple[tuple[Vec2, ...], Roof | None, Pose]] = []
    for piece in solved.pieces:
        angle = _draw_rotation(rng, piece.polygon)
        start = int(rng.random() * len(piece.polygon))
        rotated = [_polygon.rotate(p, angle) for p in piece.polygon]
        polygon = tuple(rotated[start:] + rotated[:start])
        roof = piece.roof
        if roof is not None:
            gx, gy = _polygon.rotate((roof.gx, roof.gy), angle)
            roof = Roof(roof.z0, gx, gy)
        # world = R(theta0) local + t = R(theta0 - angle) (R(angle) local) + t
        pose = Pose(piece.pose.x, piece.pose.y, _wrap_angle(piece.pose.theta - angle))
        turned.append((polygon, roof, pose))

    pieces: list[Piece] = []
    poses: dict[str, Pose] = {}
    source_ids: dict[str, str] = {}
    for new_index, old_index in enumerate(_shuffled(rng, len(turned))):
        polygon, roof, pose = turned[old_index]
        piece_id = f"p{new_index:0{width}d}"
        pieces.append(Piece(piece_id, polygon, roof))
        poses[piece_id] = pose
        source_ids[piece_id] = solved.pieces[old_index].source_id

    # Build with everything the assembly has, then remove what the regime may not see.
    instance = PuzzleInstance(
        id=solved.id,
        regime=Regime.RELIEF if solved.has_roofs else Regime.FOOTPRINT,
        target=solved.target,
        pieces=tuple(pieces),
        span_mm=solved.span_mm,
        validation=solved.validation,
        relief_mm=solved.relief_mm,
        rules=solved.rules,
        source=solved.source,
    )
    if regime is Regime.FOOTPRINT:
        instance = instance.as_regime(Regime.FOOTPRINT)
    elif regime is Regime.TROPICAL_AWARE:
        instance = PuzzleInstance(
            instance.id,
            Regime.TROPICAL_AWARE,
            instance.target,
            instance.pieces,
            instance.span_mm,
            instance.validation,
            instance.relief_mm,
            instance.rules,
            instance.source,
            {"construction": solved.tropical, "pieceTerms": dict(source_ids)},
        )

    key = AnswerKey(
        instance_id=instance.id,
        instance_hash=instance.instance_hash(),
        seed=seed,
        poses=poses,
        source_ids=source_ids,
        solution_count=solved.solution_count,
    )
    return instance, key
