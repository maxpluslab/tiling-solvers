# tiling-solvers

A solver laboratory for geometric tiling puzzles, starting with the tropical puzzles published by [Tropical Puzzle Lab](https://github.com/maxpluslab/tropical-puzzle-lab).

The aim is a research platform, not a single solver:

- several custom Rust algorithms that can be developed and compared side by side;
- established engines such as OR-Tools CP-SAT as independent backends;
- Python prototypes that migrate to Rust once the idea is settled;
- geometry, candidate generation, input formats, validation and benchmarking shared by all of them;
- experiments on puzzle difficulty, ambiguity, uniqueness and geometric tolerances.

Python owns orchestration and analysis. Rust owns the geometry and the search.

## Status

**Skeleton only.** The workspace builds, the Python package imports its Rust extension, and CI runs on Linux and Windows. No solver exists yet. The work is laid out in [docs/roadmap.md](docs/roadmap.md), and the design in [docs/architecture.md](docs/architecture.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and a stable [Rust toolchain](https://rustup.rs/).

```sh
uv sync            # creates .venv and builds the Rust extension
uv run pytest      # Python tests
cargo test --workspace --exclude tiling-py   # Rust tests
```

`uv sync` and `uv run` rebuild the extension when Rust sources change.

## Layout

```
crates/
  tiling-core/       shared domain types
  tiling-geometry/   convex geometry, contact matching, candidates
  tiling-search/     custom Rust solvers, one module each
  tiling-py/         PyO3 bindings only
python/maxplus_solvers/   the Python package; `_native` is the Rust extension
tests/               pytest suites
docs/                architecture and roadmap
```

Planned, added by the roadmap phase that needs them: `schemas/` (versioned exchange formats), `benchmarks/` (sanitized fixtures and manifests), `scripts/`, `notebooks/`.

## Relation to Tropical Puzzle Lab

Tropical Puzzle Lab remains the authority for constructing puzzles. This repository consumes its published `puzzle.json` format and turns it into sanitized solver instances: no reference poses, no construction metadata, pieces rotated and shuffled so that nothing about the stored form hints at the answer.

## License

[MIT](LICENSE)
