"""Importer for the ``puzzle.json`` format published by Tropical Puzzle Lab.

The format is described in that repository's ``docs/puzzle-format.md``. A source
file contains the answer, so it is read into a :class:`SolvedAssembly` and only
ever leaves this module through :func:`maxplus_solvers.sanitize.sanitize`.

Dropped on the way: ``reference`` (it becomes the answer key), ``provenance``,
``scramble``, the name and description, flat thickness, and the tray rim. The
``tropical`` block survives only in a tropical-aware instance.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from maxplus_solvers.models import (
    InstanceError,
    Pose,
    PuzzleInstance,
    Regime,
    Roof,
    Rules,
    SourceRef,
    ValidationConstants,
)
from maxplus_solvers.sanitize import AnswerKey, SolvedAssembly, SolvedPiece, sanitize

SOURCE_REPOSITORY = "https://github.com/maxpluslab/tropical-puzzle-lab"
SOURCE_FORMAT_VERSION = 1


def read_source(path: str | Path) -> dict[str, Any]:
    """Load a source ``puzzle.json``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def solved_assembly(
    document: Mapping[str, Any], *, commit: str, repository: str = SOURCE_REPOSITORY
) -> SolvedAssembly:
    """Interpret a source document. ``commit`` identifies the source revision it was read at."""
    if document.get("formatVersion") != SOURCE_FORMAT_VERSION:
        raise InstanceError(f"unsupported source formatVersion {document.get('formatVersion')!r}")
    geometry = document["geometry"]
    if geometry.get("model") != "planar" or geometry.get("units") != "mm":
        raise InstanceError("source geometry must be planar, in mm")
    if geometry["target"].get("type") != "polygon":
        raise InstanceError("source target must be a polygon")
    variant = document["variant"]
    if variant not in ("relief", "tiling"):
        raise InstanceError(f"unknown source variant {variant!r}")

    poses = {p["id"]: Pose(p["x"], p["y"], p["theta"]) for p in document["reference"]["poses"]}
    pieces = []
    for piece in document["pieces"]:
        roof = None
        if variant == "relief":
            r = piece["roof"]
            roof = Roof(r["z0"], r["gx"], r["gy"])
        polygon = tuple((float(x), float(y)) for x, y in piece["polygon"])
        pieces.append(SolvedPiece(piece["id"], polygon, poses[piece["id"]], roof))
    if len(poses) != len(pieces):
        raise InstanceError("source reference poses do not match the pieces")

    rules = document["rules"]
    if rules.get("snap") is not False:
        raise InstanceError("source rules must have snap=false")
    return SolvedAssembly(
        id=document["id"],
        target=tuple((float(x), float(y)) for x, y in geometry["target"]["vertices"]),
        pieces=tuple(pieces),
        span_mm=float(geometry["spanMm"]),
        validation=ValidationConstants.from_dict(document["validation"], "source validation"),
        relief_mm=float(geometry["reliefMm"]) if variant == "relief" else None,
        rules=Rules(rules["translate"], rules["rotate"], rules["flip"]),
        source=SourceRef(repository, commit, document["id"], document["geometryHash"]),
        tropical=document.get("tropical"),
    )


def import_puzzle(
    document: Mapping[str, Any],
    *,
    seed: int,
    commit: str,
    regime: Regime | str | None = None,
    repository: str = SOURCE_REPOSITORY,
) -> tuple[PuzzleInstance, AnswerKey]:
    """Sanitize a source document into an instance and its answer key.

    The regime defaults to relief for a relief puzzle and footprint for a flat
    one. A relief puzzle can also be imported as footprint or tropical-aware; a
    flat puzzle has no roofs and is footprint only.
    """
    return sanitize(solved_assembly(document, commit=commit, repository=repository), seed, regime)
