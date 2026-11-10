# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A solver laboratory for geometric tiling puzzles: shared Rust geometry, interchangeable solvers behind one `solve()` contract, independent validation, and benchmarking. The design is in `docs/architecture.md`; the algorithmic background and literature are in the research brief, `docs/research-brief.md`, and where they differ the architecture document decides. Work proceeds one phase at a time from `docs/roadmap.md`; read the phase before starting it and tick it off when its exit criterion is met. Everything committed here is public.

The puzzles come from the sibling repository `maxpluslab/tropical-puzzle-lab` (usually cloned at `../tropical-puzzle-lab`). Its `docs/puzzle-format.md` and `docs/puzzle-rules.md` define the source format and the completion rules, and `web/src/geometry/evaluate.ts` is the reference implementation of those rules. The puzzle generator stays there; never move it here.

## Commands

```sh
uv sync                                   # create .venv, build the Rust extension
uv run pytest                             # all Python tests
uv run pytest tests/unit/test_native.py::test_version_matches_the_package
uv run ruff check && uv run ruff format --check
uv run pyright

cargo fmt --all
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --exclude tiling-py          # tiling-py is a cdylib, tested through pytest
cargo test -p tiling-geometry signed_area
```

`uv sync` and `uv run` rebuild the extension when anything under `crates/` changes (`[tool.uv] cache-keys` in `pyproject.toml`). The extension uses the stable ABI (`abi3-py311`), so one build serves every supported Python. CI (`.github/workflows/ci.yml`) runs all of the above on Linux and Windows.

## Architecture

- `crates/tiling-core`: domain types. No dependencies on the other crates.
- `crates/tiling-geometry`: convex geometry, contact matching, candidate generation. Depends on core.
- `crates/tiling-search`: custom solvers, one module each. Depends on core and geometry.
- `crates/tiling-py`: PyO3 bindings, built by maturin as `maxplus_solvers._native`. Converts types and forwards calls; no algorithms.
- `python/maxplus_solvers`: the user-facing package: models, importers, solver adapters, validation, experiments. When a function is added to `_native`, add it to `_native.pyi` too.

## Invariants that are easy to break

- **Solver instances carry no answer.** The source `puzzle.json` leaks the solution three ways: `reference.poses`; local polygons stored in their solved orientation (every reference `theta` is 0); and piece ids and order that encode the tropical construction. Instances must be sanitized: seeded random rotation per piece (roof gradient rotated with it), shuffled order, opaque ids, no `reference`, `tropical` or `provenance`. Answer keys live under `tests/` and only tests load them.
- **Three information regimes stay separate:** footprint (polygons only), relief (polygons and roof planes), tropical-aware (construction data as well). A solver declares which one it uses; results from different regimes are not comparable.
- **The validator is independent of the search.** `validation.py` must not import `_native` or reuse the Rust geometry, so one bug cannot affect both.
- **Completeness and uniqueness are explicit claims.** A result says whether the search was exhaustive and over which candidate set. "No solution found" and CP-SAT `INFEASIBLE` are relative to the candidates generated unless completeness is proven.
- **Layering is one-way:** core ← geometry ← search ← py. Python reaches Rust only through `_native`.
- **Production solvers cross the Python/Rust boundary once per solve.** Prototypes may call individual geometry primitives; a Rust solver receives the instance and runs to completion.
- **Units are millimetres and radians,** matching the browser player. Polygons are convex and counter-clockwise, in local coordinates about the area centroid. A pose rotates by `theta` then translates by `(x, y)`.
- **`f64` with explicit tolerances is not exactness.** Don't describe a floating-point result as a mathematical proof.
- **Optional dependencies stay optional.** OR-Tools, Shapely and the analysis stack are extras; the Rust solvers must run without them.
