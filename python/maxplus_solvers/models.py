"""The contracts shared by every solver: instances, poses, tolerances, results.

Units are millimetres and radians. Polygons are strictly convex and
counter-clockwise; a piece's polygon is in local coordinates about its area
centroid. A pose rotates by ``theta`` and then translates by ``(x, y)``.

The JSON form of :class:`PuzzleInstance` is ``schemas/instance-v1.json``. The
schema fixes the structure; the constructors here also enforce what a schema
cannot express (convexity, orientation, centring, consistency with the regime).
An instance carries no answer: there is nowhere to put reference poses, and
``from_dict`` rejects unknown keys.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from maxplus_solvers import _polygon
from maxplus_solvers._polygon import Vec2

FORMAT_VERSION = 1

# A piece's centroid may be this far from its local origin, in millimetres.
CENTROID_TOL_MM = 1e-6


class InstanceError(ValueError):
    """A document or object that is not a valid puzzle instance."""


class Regime(StrEnum):
    """How much a solver is told. Results from different regimes are not comparable."""

    FOOTPRINT = "footprint"
    RELIEF = "relief"
    TROPICAL_AWARE = "tropical-aware"


class SolveStatus(StrEnum):
    """Outcome of a solve. ``docs/solver-contract.md`` says what each value claims.

    * ``solved``: at least one solution is returned.
    * ``no_solution_found``: the search ran to its end and found none. This is
      a statement about the candidates the solver generated, and about the
      puzzle only if those are proven complete.
    * ``interrupted``: a limit stopped the search before it found anything.
    """

    SOLVED = "solved"
    NO_SOLUTION_FOUND = "no_solution_found"
    INTERRUPTED = "interrupted"


# --- small parsing helpers -------------------------------------------------


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InstanceError(f"{where}: expected a number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise InstanceError(f"{where}: {value!r} is not finite")
    return result


def _mapping(value: Any, where: str, required: Sequence[str], optional: Sequence[str] = ()) -> Any:
    if not isinstance(value, Mapping):
        raise InstanceError(f"{where}: expected an object")
    missing = [k for k in required if k not in value]
    if missing:
        raise InstanceError(f"{where}: missing {', '.join(missing)}")
    unknown = sorted(set(value) - set(required) - set(optional))
    if unknown:
        raise InstanceError(f"{where}: unexpected {', '.join(map(str, unknown))}")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise InstanceError(f"{where}: expected a non-empty string")
    return value


def _polygon_from(value: Any, where: str) -> tuple[Vec2, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise InstanceError(f"{where}: expected a list of [x, y] pairs")
    points: list[Vec2] = []
    for i, pair in enumerate(value):
        if not isinstance(pair, Sequence) or isinstance(pair, str) or len(pair) != 2:
            raise InstanceError(f"{where}[{i}]: expected an [x, y] pair")
        points.append((_number(pair[0], f"{where}[{i}]"), _number(pair[1], f"{where}[{i}]")))
    return tuple(points)


def _polygon_to(polygon: Sequence[Vec2]) -> list[list[float]]:
    return [[x, y] for x, y in polygon]


# --- geometry-bearing types -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pose:
    """Rotate counter-clockwise by ``theta`` about the local origin, then translate."""

    x: float
    y: float
    theta: float

    def apply(self, p: Vec2) -> Vec2:
        """Map a point from piece-local to world coordinates."""
        u, v = _polygon.rotate(p, self.theta)
        return (self.x + u, self.y + v)

    def to_local(self, p: Vec2) -> Vec2:
        """Map a point from world to piece-local coordinates."""
        return _polygon.rotate((p[0] - self.x, p[1] - self.y), -self.theta)

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "theta": self.theta}

    @classmethod
    def from_dict(cls, data: Any, where: str = "pose") -> Self:
        d = _mapping(data, where, ("x", "y", "theta"))
        return cls(
            _number(d["x"], f"{where}.x"),
            _number(d["y"], f"{where}.y"),
            _number(d["theta"], f"{where}.theta"),
        )


@dataclass(frozen=True, slots=True)
class Roof:
    """The top plane ``z = z0 + gx*u + gy*v`` in piece-local coordinates, mm above the underside."""

    z0: float
    gx: float
    gy: float

    def height_at(self, local: Vec2) -> float:
        return self.z0 + self.gx * local[0] + self.gy * local[1]

    def to_dict(self) -> dict[str, float]:
        return {"z0": self.z0, "gx": self.gx, "gy": self.gy}

    @classmethod
    def from_dict(cls, data: Any, where: str = "roof") -> Self:
        d = _mapping(data, where, ("z0", "gx", "gy"))
        return cls(*(_number(d[k], f"{where}.{k}") for k in ("z0", "gx", "gy")))


@dataclass(frozen=True, slots=True)
class Piece:
    """A convex piece. ``id`` is opaque: it says nothing about how the puzzle was built."""

    id: str
    polygon: tuple[Vec2, ...]
    roof: Roof | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "polygon", tuple((float(x), float(y)) for x, y in self.polygon))
        defect = _polygon.convexity_defect(self.polygon)
        if defect:
            raise InstanceError(f"piece {self.id}: polygon {defect}")
        cx, cy = _polygon.centroid(self.polygon)
        if math.hypot(cx, cy) > CENTROID_TOL_MM:
            raise InstanceError(
                f"piece {self.id}: centroid ({cx:.3g}, {cy:.3g}) is not at the local origin"
            )

    @property
    def area(self) -> float:
        return _polygon.signed_area(self.polygon)

    def world_polygon(self, pose: Pose) -> tuple[Vec2, ...]:
        return tuple(pose.apply(p) for p in self.polygon)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "polygon": _polygon_to(self.polygon)}
        if self.roof is not None:
            out["roof"] = self.roof.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Any, where: str = "piece") -> Self:
        d = _mapping(data, where, ("id", "polygon"), ("roof",))
        roof = Roof.from_dict(d["roof"], f"{where}.roof") if "roof" in d else None
        return cls(
            _string(d["id"], f"{where}.id"), _polygon_from(d["polygon"], f"{where}.polygon"), roof
        )


@dataclass(frozen=True, slots=True)
class Rules:
    """How pieces may move. Format version 1 has exactly one rule set."""

    translate: bool = True
    rotate: str = "continuous-z"
    flip: bool = False

    def __post_init__(self) -> None:
        if self.translate is not True or self.rotate != "continuous-z" or self.flip is not False:
            raise InstanceError(
                "rules: only translate=true, rotate='continuous-z', flip=false is supported"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"translate": self.translate, "rotate": self.rotate, "flip": self.flip}

    @classmethod
    def from_dict(cls, data: Any, where: str = "rules") -> Self:
        d = _mapping(data, where, ("translate", "rotate", "flip"))
        return cls(d["translate"], d["rotate"], d["flip"])


@dataclass(frozen=True, slots=True)
class ValidationConstants:
    """The source puzzle's scale-relative tolerances, as published.

    Lengths are fractions of the span, the area error is a fraction of the target
    area, and the roof mismatch is a fraction of the relief height.
    :class:`TolerancePolicy` turns them into millimetres.
    """

    contact_noise: float
    overlap_depth: float
    outside_depth: float
    area_error: float
    edge_angle_deg: float
    edge_min_overlap: float
    roof_mismatch: float | None = None

    _KEYS = (
        ("contactNoise", "contact_noise"),
        ("overlapDepth", "overlap_depth"),
        ("outsideDepth", "outside_depth"),
        ("areaError", "area_error"),
        ("edgeAngleDeg", "edge_angle_deg"),
        ("edgeMinOverlap", "edge_min_overlap"),
    )

    def __post_init__(self) -> None:
        for _, attr in self._KEYS:
            if not getattr(self, attr) >= 0:
                raise InstanceError(f"validation.{attr} must be non-negative")
        if self.roof_mismatch is not None and not self.roof_mismatch >= 0:
            raise InstanceError("validation.roof_mismatch must be non-negative")

    def to_dict(self) -> dict[str, float]:
        out = {key: getattr(self, attr) for key, attr in self._KEYS}
        if self.roof_mismatch is not None:
            out["roofMismatch"] = self.roof_mismatch
        return out

    @classmethod
    def from_dict(cls, data: Any, where: str = "validation") -> Self:
        keys = [key for key, _ in cls._KEYS]
        d = _mapping(data, where, keys, ("roofMismatch",))
        values = {attr: _number(d[key], f"{where}.{key}") for key, attr in cls._KEYS}
        roof = _number(d["roofMismatch"], f"{where}.roofMismatch") if "roofMismatch" in d else None
        return cls(**values, roof_mismatch=roof)


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where a corpus instance came from. It identifies the source and nothing about the answer."""

    repository: str
    commit: str
    puzzle_id: str
    geometry_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "commit": self.commit,
            "puzzleId": self.puzzle_id,
            "geometryHash": self.geometry_hash,
        }

    @classmethod
    def from_dict(cls, data: Any, where: str = "source") -> Self:
        keys = ("repository", "commit", "puzzleId", "geometryHash")
        d = _mapping(data, where, keys)
        return cls(*(_string(d[k], f"{where}.{k}") for k in keys))


@dataclass(frozen=True, slots=True)
class PuzzleInstance:
    """A puzzle as a solver sees it: a target, pieces, and the rules of the regime."""

    id: str
    regime: Regime
    target: tuple[Vec2, ...]
    pieces: tuple[Piece, ...]
    span_mm: float
    validation: ValidationConstants
    relief_mm: float | None = None
    rules: Rules = field(default_factory=Rules)
    source: SourceRef | None = None
    # Construction data, present in the tropical-aware regime only:
    # {"construction": <the source tropical block>, "pieceTerms": {piece id: term id}}.
    tropical: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "regime", Regime(self.regime))
        object.__setattr__(self, "target", tuple((float(x), float(y)) for x, y in self.target))
        object.__setattr__(self, "pieces", tuple(self.pieces))
        where = f"instance {self.id}"
        defect = _polygon.convexity_defect(self.target)
        if defect:
            raise InstanceError(f"{where}: target {defect}")
        if not self.pieces:
            raise InstanceError(f"{where}: has no pieces")
        ids = [p.id for p in self.pieces]
        if len(set(ids)) != len(ids):
            raise InstanceError(f"{where}: piece ids are not unique")
        if not (math.isfinite(self.span_mm) and self.span_mm > 0):
            raise InstanceError(f"{where}: spanMm must be positive")

        has_roofs = self.regime is not Regime.FOOTPRINT
        for piece in self.pieces:
            if (piece.roof is not None) != has_roofs:
                state = "needs" if has_roofs else "must not have"
                raise InstanceError(f"{where}: {self.regime} piece {piece.id} {state} a roof")
        if has_roofs:
            if self.relief_mm is None or not (math.isfinite(self.relief_mm) and self.relief_mm > 0):
                raise InstanceError(f"{where}: {self.regime} needs a positive reliefMm")
            if self.validation.roof_mismatch is None:
                raise InstanceError(f"{where}: {self.regime} needs validation.roofMismatch")
        elif self.relief_mm is not None or self.validation.roof_mismatch is not None:
            raise InstanceError(f"{where}: footprint must not carry relief data")

        if (self.tropical is not None) != (self.regime is Regime.TROPICAL_AWARE):
            raise InstanceError(f"{where}: tropical data belongs to the tropical-aware regime only")
        if self.tropical is not None:
            t = _mapping(self.tropical, f"{where}.tropical", ("construction", "pieceTerms"))
            if not isinstance(t["pieceTerms"], Mapping) or set(t["pieceTerms"]) != set(ids):
                raise InstanceError(f"{where}: tropical.pieceTerms must name every piece once")

    @property
    def target_area(self) -> float:
        return _polygon.signed_area(self.target)

    def piece(self, piece_id: str) -> Piece:
        for piece in self.pieces:
            if piece.id == piece_id:
                return piece
        raise KeyError(piece_id)

    def as_regime(self, regime: Regime | str) -> "PuzzleInstance":
        """The same puzzle with less information. Information is only ever removed."""
        regime = Regime(regime)
        if regime is self.regime:
            return self
        order = [Regime.FOOTPRINT, Regime.RELIEF, Regime.TROPICAL_AWARE]
        if order.index(regime) > order.index(self.regime):
            raise InstanceError(f"cannot turn a {self.regime} instance into a {regime} one")
        if regime is Regime.RELIEF:
            return PuzzleInstance(
                self.id,
                regime,
                self.target,
                self.pieces,
                self.span_mm,
                self.validation,
                self.relief_mm,
                self.rules,
                self.source,
            )
        v = self.validation
        flat = ValidationConstants(
            v.contact_noise,
            v.overlap_depth,
            v.outside_depth,
            v.area_error,
            v.edge_angle_deg,
            v.edge_min_overlap,
        )
        pieces = tuple(Piece(p.id, p.polygon) for p in self.pieces)
        return PuzzleInstance(
            self.id, regime, self.target, pieces, self.span_mm, flat, None, self.rules, self.source
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "formatVersion": FORMAT_VERSION,
            "id": self.id,
            "regime": self.regime.value,
            "units": "mm",
            "spanMm": self.span_mm,
        }
        if self.relief_mm is not None:
            out["reliefMm"] = self.relief_mm
        out["target"] = {"vertices": _polygon_to(self.target)}
        out["pieces"] = [p.to_dict() for p in self.pieces]
        out["rules"] = self.rules.to_dict()
        out["validation"] = self.validation.to_dict()
        if self.source is not None:
            out["source"] = self.source.to_dict()
        if self.tropical is not None:
            out["tropical"] = json.loads(json.dumps(self.tropical))
        return out

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        required = (
            "formatVersion",
            "id",
            "regime",
            "units",
            "spanMm",
            "target",
            "pieces",
            "rules",
            "validation",
        )
        d = _mapping(data, "instance", required, ("reliefMm", "source", "tropical"))
        if d["formatVersion"] != FORMAT_VERSION or isinstance(d["formatVersion"], bool):
            raise InstanceError(f"instance: unsupported formatVersion {d['formatVersion']!r}")
        if d["units"] != "mm":
            raise InstanceError("instance: units must be 'mm'")
        try:
            regime = Regime(d["regime"])
        except ValueError:
            raise InstanceError(f"instance: unknown regime {d['regime']!r}") from None
        target = _mapping(d["target"], "instance.target", ("vertices",))
        if not isinstance(d["pieces"], Sequence) or isinstance(d["pieces"], str):
            raise InstanceError("instance.pieces: expected a list")
        return cls(
            id=_string(d["id"], "instance.id"),
            regime=regime,
            target=_polygon_from(target["vertices"], "instance.target.vertices"),
            pieces=tuple(
                Piece.from_dict(p, f"instance.pieces[{i}]") for i, p in enumerate(d["pieces"])
            ),
            span_mm=_number(d["spanMm"], "instance.spanMm"),
            validation=ValidationConstants.from_dict(d["validation"], "instance.validation"),
            relief_mm=_number(d["reliefMm"], "instance.reliefMm") if "reliefMm" in d else None,
            rules=Rules.from_dict(d["rules"], "instance.rules"),
            source=SourceRef.from_dict(d["source"], "instance.source") if "source" in d else None,
            tropical=d.get("tropical"),
        )

    def instance_hash(self) -> str:
        """SHA-256 of the canonical JSON form. Answer keys and results are bound to it."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- tolerances ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    """Absolute tolerances for one solve or one validation, in mm, mm² and radians."""

    contact_noise_mm: float
    overlap_depth_mm: float
    outside_depth_mm: float
    area_error_mm2: float
    edge_angle_rad: float
    edge_min_overlap_mm: float
    roof_mismatch_mm: float | None = None

    @classmethod
    def from_instance(cls, instance: PuzzleInstance) -> Self:
        """The browser player's tolerances: the published constants scaled by the instance.

        Lengths scale with the span, the area error with the target area, and the
        roof mismatch with the relief height.
        """
        v = instance.validation
        span = instance.span_mm
        roof = None
        if v.roof_mismatch is not None and instance.relief_mm is not None:
            roof = v.roof_mismatch * instance.relief_mm
        return cls(
            contact_noise_mm=v.contact_noise * span,
            overlap_depth_mm=v.overlap_depth * span,
            outside_depth_mm=v.outside_depth * span,
            area_error_mm2=v.area_error * instance.target_area,
            edge_angle_rad=math.radians(v.edge_angle_deg),
            edge_min_overlap_mm=v.edge_min_overlap * span,
            roof_mismatch_mm=roof,
        )

    def to_dict(self) -> dict[str, float | None]:
        return {
            "contactNoiseMm": self.contact_noise_mm,
            "overlapDepthMm": self.overlap_depth_mm,
            "outsideDepthMm": self.outside_depth_mm,
            "areaErrorMm2": self.area_error_mm2,
            "edgeAngleRad": self.edge_angle_rad,
            "edgeMinOverlapMm": self.edge_min_overlap_mm,
            "roofMismatchMm": self.roof_mismatch_mm,
        }

    @classmethod
    def from_dict(cls, data: Any, where: str = "tolerances") -> Self:
        keys = (
            "contactNoiseMm",
            "overlapDepthMm",
            "outsideDepthMm",
            "areaErrorMm2",
            "edgeAngleRad",
            "edgeMinOverlapMm",
            "roofMismatchMm",
        )
        d = _mapping(data, where, keys)
        roof = d["roofMismatchMm"]
        return cls(
            *(_number(d[k], f"{where}.{k}") for k in keys[:-1]),
            roof_mismatch_mm=None if roof is None else _number(roof, f"{where}.roofMismatchMm"),
        )


# --- solving ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """What to run and under which limits. ``mode`` is the regime the solver may use."""

    solver: str
    mode: Regime = Regime.FOOTPRINT
    time_limit_s: float | None = None
    max_solutions: int | None = 1
    seed: int = 0
    tolerances: TolerancePolicy | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", Regime(self.mode))
        if self.time_limit_s is not None and not self.time_limit_s > 0:
            raise ValueError("time_limit_s must be positive")
        if self.max_solutions is not None and self.max_solutions < 1:
            raise ValueError("max_solutions must be at least 1, or None for all")

    def to_dict(self) -> dict[str, Any]:
        return {
            "solver": self.solver,
            "mode": self.mode.value,
            "timeLimitS": self.time_limit_s,
            "maxSolutions": self.max_solutions,
            "seed": self.seed,
            "tolerances": None if self.tolerances is None else self.tolerances.to_dict(),
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        keys = ("solver", "mode", "timeLimitS", "maxSolutions", "seed", "tolerances", "options")
        d = _mapping(data, "config", keys)
        tolerances = d["tolerances"]
        return cls(
            solver=_string(d["solver"], "config.solver"),
            mode=Regime(d["mode"]),
            time_limit_s=d["timeLimitS"],
            max_solutions=d["maxSolutions"],
            seed=d["seed"],
            tolerances=None if tolerances is None else TolerancePolicy.from_dict(tolerances),
            options=dict(d["options"]),
        )


@dataclass(frozen=True, slots=True)
class Solution:
    """One assembly: a pose for every piece.

    ``residuals`` and ``valid`` are the independent validator's findings, and
    stay ``None`` until it has been run. A solver does not fill them in itself.
    """

    poses: Mapping[str, Pose]
    residuals: Mapping[str, float] | None = None
    valid: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "poses": {pid: pose.to_dict() for pid, pose in self.poses.items()},
            "residuals": None if self.residuals is None else dict(self.residuals),
            "valid": self.valid,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        d = _mapping(data, "solution", ("poses", "residuals", "valid"))
        poses = {pid: Pose.from_dict(p, f"solution.poses.{pid}") for pid, p in d["poses"].items()}
        return cls(poses, None if d["residuals"] is None else dict(d["residuals"]), d["valid"])


@dataclass(frozen=True, slots=True)
class SolveResult:
    """What a solver reports, including how far its claims reach.

    ``exhaustive`` says the search ran to completion over the candidate
    placements it generated. ``candidates_proven_complete`` says those candidates
    are known to include every solution. Only both together make "no solution"
    or "exactly these solutions" a claim about the puzzle; otherwise the result
    is relative to the candidate set, which ``candidate_set`` names.

    ``config`` and ``solver_version`` record what produced the result, so that
    it can be reproduced.
    """

    status: SolveStatus
    solver: str
    regime: Regime
    instance_hash: str
    solutions: tuple[Solution, ...] = ()
    exhaustive: bool = False
    candidates_proven_complete: bool = False
    metrics: Mapping[str, float] = field(default_factory=dict)
    candidate_set: str = ""
    config: SolverConfig | None = None
    solver_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SolveStatus(self.status))
        object.__setattr__(self, "regime", Regime(self.regime))
        object.__setattr__(self, "solutions", tuple(self.solutions))
        if (self.status is SolveStatus.SOLVED) != bool(self.solutions):
            raise ValueError("status is 'solved' exactly when there is at least one solution")
        if self.status is SolveStatus.NO_SOLUTION_FOUND and not self.exhaustive:
            raise ValueError("'no_solution_found' is only said by a search that ran to its end")
        if self.status is SolveStatus.INTERRUPTED and self.exhaustive:
            raise ValueError("an interrupted search was not exhaustive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "solver": self.solver,
            "regime": self.regime.value,
            "instanceHash": self.instance_hash,
            "solutions": [s.to_dict() for s in self.solutions],
            "exhaustive": self.exhaustive,
            "candidatesProvenComplete": self.candidates_proven_complete,
            "metrics": dict(self.metrics),
            "candidateSet": self.candidate_set,
            "config": None if self.config is None else self.config.to_dict(),
            "solverVersion": self.solver_version,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        keys = (
            "status",
            "solver",
            "regime",
            "instanceHash",
            "solutions",
            "exhaustive",
            "candidatesProvenComplete",
            "metrics",
            "candidateSet",
            "config",
            "solverVersion",
        )
        d = _mapping(data, "result", keys)
        return cls(
            status=SolveStatus(d["status"]),
            solver=d["solver"],
            regime=Regime(d["regime"]),
            instance_hash=d["instanceHash"],
            solutions=tuple(Solution.from_dict(s) for s in d["solutions"]),
            exhaustive=d["exhaustive"],
            candidates_proven_complete=d["candidatesProvenComplete"],
            metrics=dict(d["metrics"]),
            candidate_set=d["candidateSet"],
            config=None if d["config"] is None else SolverConfig.from_dict(d["config"]),
            solver_version=d["solverVersion"],
        )
