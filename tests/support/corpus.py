"""Locations and raw loaders for the committed fixtures and answer keys.

Documents are returned as plain JSON so that corpus tests inspect what is
actually on disk, without going through the package's loaders.
"""

import json
import os
from collections.abc import Collection
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "benchmarks" / "fixtures"
KEYS = ROOT / "tests" / "keys"
SCHEMA = ROOT / "schemas" / "instance-v1.json"
MINI_SOURCE = ROOT / "tests" / "data" / "source" / "mini" / "puzzle.json"

SOURCE_ENV = "TROPICAL_PUZZLE_LAB"

# Corpus fixtures whose whole search, assuming nothing, has not been seen to end:
# cor1-flat was stopped at 3 000 000 nodes. Tests that compare against the end of
# that search leave these out by name, and test them separately for what can be said.
UNFINISHED = frozenset({"cor1-flat"})

# Corpus fixtures whose whole search, assuming nothing, the test suite does not run:
# 909 750 nodes and more (cor1-flat stops at the corpus manifest's limit of 1 500 000),
# against at most 128 230 for the rest (benchmarks/results/corpus.md). Run again and
# again across the tests they took over ten minutes. The suite reproduces the other rows
# of the committed tables; these rows are checked by running the full command by hand.
EXPENSIVE = frozenset({"cor1-flat", "new1-flat", "new2-flat"})
# CP-SAT on rat2-flat: whole, but 80 s of choosing among its listed placements.
EXPENSIVE_FOR_CP_SAT = EXPENSIVE | {"rat2-flat"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def index() -> dict[str, Any]:
    return read_json(FIXTURES / "index.json")


def fixture_ids(kind: str | None = None, regime: str | None = None) -> list[str]:
    """Ids listed in the manifest, optionally filtered."""
    return [
        entry["id"]
        for entry in index()["fixtures"]
        if (kind is None or entry["kind"] == kind) and (regime is None or entry["regime"] == regime)
    ]


def fixture(fixture_id: str) -> dict[str, Any]:
    return read_json(FIXTURES / f"{fixture_id}.json")


def key(fixture_id: str) -> dict[str, Any]:
    return read_json(KEYS / f"{fixture_id}.json")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table(text: str) -> list[dict[str, str]]:
    """The rows of a committed Markdown results table, by column title, ``Fixture`` bare."""
    lines = text.splitlines()
    header = _cells(lines[0])
    rows = [dict(zip(header, _cells(line), strict=True)) for line in lines[2:]]
    for row in rows:
        row["Fixture"] = row["Fixture"].strip("`")
    return rows


def table_rows(text: str, fixtures: Collection[str]) -> str:
    """A committed Markdown results table cut down to its header and these fixtures' rows."""
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines[2:] if _cells(line)[0].strip("`") in fixtures]
    return "".join(lines[:2] + kept)


def schema() -> dict[str, Any]:
    return read_json(SCHEMA)


def source_checkout() -> Path | None:
    """The tropical-puzzle-lab checkout, from the environment or beside this repository."""
    candidates = [Path(p) for p in [os.environ.get(SOURCE_ENV, "")] if p]
    candidates.append(ROOT.parent / "tropical-puzzle-lab")
    for candidate in candidates:
        if (candidate / "puzzles" / "index.json").is_file():
            return candidate
    return None
