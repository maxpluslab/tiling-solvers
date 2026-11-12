"""Generate the benchmark fixtures and their answer keys.

    uv run python scripts/import_fixtures.py --source ../tropical-puzzle-lab
    uv run python scripts/import_fixtures.py --source ../tropical-puzzle-lab --check

Writes, from the repository root:

* ``benchmarks/fixtures/<id>.json``: one sanitized instance per source puzzle,
  and one per synthetic builder;
* ``benchmarks/fixtures/index.json``: what was imported and from which commit;
* ``tests/keys/<id>.json``: the reference poses, for tests only.

``--check`` writes nothing. It regenerates everything in memory and fails if the
committed files differ, comparing numbers to 1e-9 because trigonometric
functions may differ in the last bit between platforms.

These files are generated. Change the importer or the source and rerun; never
edit them by hand.
"""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

from maxplus_solvers.io.instance import write_json
from maxplus_solvers.io.tropical import SOURCE_REPOSITORY, import_puzzle, read_source
from maxplus_solvers.models import PuzzleInstance
from maxplus_solvers.sanitize import SANITIZER_VERSION, AnswerKey, sanitize
from maxplus_solvers.synthetic import BUILDERS

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "benchmarks" / "fixtures"
KEYS = ROOT / "tests" / "keys"
INDEX = FIXTURES / "index.json"

# The seed is part of the answer: it is recorded in the keys, never in a fixture.
DEFAULT_SEED = 20261109
NUMERIC_TOL = 1e-9


def git(source: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(source), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def build(source: Path, seed: int, commit: str) -> dict[Path, Any]:
    """Every file this script owns, as path -> JSON document."""
    documents: dict[Path, Any] = {}
    entries: list[dict[str, Any]] = []

    def add(kind: str, instance: PuzzleInstance, key: AnswerKey, **more: Any) -> None:
        documents[FIXTURES / f"{instance.id}.json"] = instance.to_dict()
        documents[KEYS / f"{instance.id}.json"] = key.to_dict()
        entries.append(
            {
                "id": instance.id,
                "kind": kind,
                "regime": instance.regime.value,
                "pieceCount": len(instance.pieces),
                "instanceHash": instance.instance_hash(),
                **more,
            }
        )

    source_index = json.loads((source / "puzzles" / "index.json").read_text(encoding="utf-8"))
    for entry in sorted(source_index["puzzles"], key=lambda e: e["id"]):
        document = read_source(source / "puzzles" / entry["path"])
        # The construction a puzzle and its flat twin share, and the source's own difficulty
        # rating. Both describe the puzzle, not its solution; they go in the index for the
        # experiments and never into an instance.
        add(
            "corpus",
            *import_puzzle(document, seed=seed, commit=commit),
            construction=entry["construction"],
            sourceDifficulty=dict(entry["difficulty"]),
        )
    for name in sorted(BUILDERS):
        add("synthetic", *sanitize(BUILDERS[name](), seed))

    documents[INDEX] = {
        "formatVersion": 1,
        "source": {"repository": SOURCE_REPOSITORY, "commit": commit},
        "sanitizerVersion": SANITIZER_VERSION,
        # How the source rates difficulty: its method and parameters, as published.
        "sourceDifficulty": dict(source_index["difficulty"]),
        "fixtures": entries,
    }
    return documents


def difference(expected: Any, actual: Any, where: str = "") -> str | None:
    """The first place two JSON documents differ, or ``None`` if they agree to the tolerance."""
    numeric = (int, float)
    if (
        isinstance(expected, numeric)
        and isinstance(actual, numeric)
        and not isinstance(expected, bool)
        and not isinstance(actual, bool)
    ):
        if not math.isclose(expected, actual, rel_tol=NUMERIC_TOL, abs_tol=NUMERIC_TOL):
            return f"{where}: {actual!r} on disk, {expected!r} regenerated"
        return None
    if type(expected) is not type(actual):
        return f"{where}: type differs"
    if isinstance(expected, dict) and isinstance(actual, dict):
        if list(expected) != list(actual):
            return f"{where}: keys differ"
        for k in expected:
            found = difference(expected[k], actual[k], f"{where}/{k}")
            if found:
                return found
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"{where}: length differs"
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            found = difference(e, a, f"{where}/{i}")
            if found:
                return found
        return None
    return None if expected == actual else f"{where}: {actual!r} on disk, {expected!r} regenerated"


def strip_hashes(document: Any) -> Any:
    """Drop instance hashes before a tolerant comparison: they change with the last bit."""
    if isinstance(document, dict):
        return {k: strip_hashes(v) for k, v in document.items() if k != "instanceHash"}
    if isinstance(document, list):
        return [strip_hashes(v) for v in document]
    return document


def check(documents: dict[Path, Any]) -> list[str]:
    problems = []
    for path, expected in documents.items():
        name = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        actual = json.loads(path.read_text(encoding="utf-8"))
        found = difference(strip_hashes(expected), strip_hashes(actual), name)
        if found:
            problems.append(found)
    for directory in (FIXTURES, KEYS):
        for path in sorted(directory.glob("*.json")):
            if path not in documents:
                problems.append(
                    f"{path.relative_to(ROOT).as_posix()}: not produced by the importer"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--source", type=Path, default=ROOT.parent / "tropical-puzzle-lab")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    parser.add_argument(
        "--allow-dirty", action="store_true", help="accept uncommitted changes under puzzles/"
    )
    parser.add_argument(
        "--print-source-commit",
        action="store_true",
        help="print the source commit the committed fixtures were imported from, and exit",
    )
    args = parser.parse_args(argv)
    if args.print_source_commit:
        print(json.loads(INDEX.read_text(encoding="utf-8"))["source"]["commit"])
        return 0

    source: Path = args.source.resolve()
    if not (source / "puzzles" / "index.json").is_file():
        print(f"error: no puzzles/index.json under {source}", file=sys.stderr)
        return 2
    commit = git(source, "rev-parse", "HEAD")
    if not args.allow_dirty and git(source, "status", "--porcelain", "--", "puzzles"):
        print("error: uncommitted changes under puzzles/ in the source", file=sys.stderr)
        return 2

    documents = build(source, args.seed, commit)
    count = len(documents) // 2
    if args.check:
        problems = check(documents)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print(f"{len(problems)} difference(s) from source commit {commit}", file=sys.stderr)
            return 1
        print(f"{count} fixtures match source commit {commit[:12]}")
        return 0

    for directory in (FIXTURES, KEYS):
        for stale in directory.glob("*.json"):
            if stale not in documents:
                stale.unlink()
    for path, document in documents.items():
        write_json(path, document)
    print(f"wrote {count} fixtures and keys from source commit {commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
