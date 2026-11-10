"""Hand-written instance documents, valid by inspection, as starting points for tests.

Two 72 mm by 144 mm strips in a 144 mm square, at the scale of the corpus so that
tolerances come out at the published rev2 values. Every call returns a fresh copy.
"""

from typing import Any

_VALIDATION = {
    "contactNoise": 1e-06,
    "overlapDepth": 0.006,
    "outsideDepth": 0.006,
    "areaError": 0.012,
    "edgeAngleDeg": 3,
    "edgeMinOverlap": 0.02,
}


def _strip() -> list[list[float]]:
    return [[-36.0, -72.0], [36.0, -72.0], [36.0, 72.0], [-36.0, 72.0]]


def footprint() -> dict[str, Any]:
    return {
        "formatVersion": 1,
        "id": "strips",
        "regime": "footprint",
        "units": "mm",
        "spanMm": 144.0,
        "target": {"vertices": [[-72.0, -72.0], [72.0, -72.0], [72.0, 72.0], [-72.0, 72.0]]},
        "pieces": [{"id": "p00", "polygon": _strip()}, {"id": "p01", "polygon": _strip()}],
        "rules": {"translate": True, "rotate": "continuous-z", "flip": False},
        "validation": dict(_VALIDATION),
    }


def relief() -> dict[str, Any]:
    doc = footprint()
    doc["regime"] = "relief"
    doc["reliefMm"] = 35.0
    doc["pieces"][0]["roof"] = {"z0": 20.0, "gx": 0.25, "gy": 0.0}
    doc["pieces"][1]["roof"] = {"z0": 20.0, "gx": -0.25, "gy": 0.0}
    doc["validation"]["roofMismatch"] = 0.05
    return doc


def tropical_aware() -> dict[str, Any]:
    doc = relief()
    doc["regime"] = "tropical-aware"
    doc["tropical"] = {
        "construction": {"convention": "max", "terms": [{"id": "A"}, {"id": "B"}]},
        "pieceTerms": {"p00": "B", "p01": "A"},
    }
    return doc


def with_source(doc: dict[str, Any]) -> dict[str, Any]:
    doc["source"] = {
        "repository": "https://example.invalid/puzzles",
        "commit": "0123abc",
        "puzzleId": "strips",
        "geometryHash": "feed",
    }
    return doc
