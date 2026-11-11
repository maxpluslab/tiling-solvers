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

**Contracts and fixtures.** The instance format, the sanitizing importer and the benchmark corpus exist: 16 puzzles from Tropical Puzzle Lab and 4 synthetic ones with known solution counts, each with an answer key that only tests read. An independent validator checks an assembly against the browser player's completion rules. The Rust geometry kernel (separating-axis depth, convex clipping, containment, edge signatures, roof continuity) is in place and agrees with the validator on random poses of every fixture's pieces. Three solvers exist. `python.contact_dfs` is a Python prototype of the contact search. `rust.contact_dfs` is that search in Rust with roofs, pruning and symmetry handling: it solves all 16 corpus puzzles, runs every search to its end, and returns assemblies that pass the validator. `cp_sat.placements` hands the placements that search reaches to OR-Tools CP-SAT as a plain choice problem, and returns the same assemblies by other means. Each rule of either can be switched off, because the question here is what makes a puzzle hard and what helps, not how fast one solver is; [docs/algorithms.md](docs/algorithms.md) has the measurements. The work is laid out in [docs/roadmap.md](docs/roadmap.md), and the design in [docs/architecture.md](docs/architecture.md).

```python
from maxplus_solvers import load_puzzle

puzzle = load_puzzle("benchmarks/fixtures/new2.json")
flat = load_puzzle(
    "benchmarks/fixtures/new2.json", regime="footprint"
)  # the same pieces without roofs
```

Solving, from Python or from the command line:

```python
from maxplus_solvers import SolverConfig, solve

result = solve(puzzle, SolverConfig("rust.contact_dfs", mode="relief", max_solutions=None))
print(result.status, len(result.solutions), result.exhaustive, result.metrics["nodes"])
```

```sh
uv run maxplus-solve new2 --mode relief --max-solutions all --validate
uv run maxplus-solve rat1-flat --max-solutions all --option closure_pruning=false
```

What a result claims, and what it does not, is in [docs/solver-contract.md](docs/solver-contract.md).

With the `validate` extra (Shapely), poses can be checked against the completion rules:

```python
from maxplus_solvers.validation import validate_solution

report = validate_solution(puzzle, poses)  # poses: {piece id: Pose}
print(report.solved, report.failed, report.residuals())
```

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
schemas/             versioned exchange formats (`instance-v1.json`)
benchmarks/fixtures/ sanitized puzzle instances, generated
scripts/             `import_fixtures.py` regenerates fixtures and answer keys
tests/               pytest suites: unit, property, corpus, architecture; answer keys in `tests/keys/`
docs/                architecture, roadmap, the solver contract and the algorithms
```

Planned, added by the roadmap phase that needs them: benchmark manifests, `notebooks/`.

## Relation to Tropical Puzzle Lab

Tropical Puzzle Lab remains the authority for constructing puzzles. This repository consumes its published `puzzle.json` format and turns it into sanitized solver instances: no reference poses, no construction metadata, pieces rotated and shuffled so that nothing about the stored form hints at the answer.

## License

[MIT](LICENSE)
