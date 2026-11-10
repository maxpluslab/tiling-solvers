# Roadmap

Each phase is sized for one working session and ends with an exit criterion that can be checked. Do them in order; each builds on the one before. The design behind them is in [architecture.md](architecture.md).

| Phase | Subject | Status |
| --- | --- | --- |
| 0 | Repository skeleton | Done |
| 1 | Contracts and fixtures | Next |
| 2 | Independent validator | |
| 3 | Rust geometry kernel | |
| 4 | Contact candidates, Python prototype, solver contract | |
| 5 | Rust contact DFS | |
| 6 | CP-SAT backend | |
| 7 | Benchmark and research platform | |

The source corpus is 8 constructions in two variants each (relief and flat), 16 puzzles of 6 to 20 convex pieces with 4 or 5 vertices, in a 144 mm square tray.

## Phase 0: repository skeleton

Cargo workspace with four crates, the `maxplus_solvers` package with its `_native` extension, one primitive (`signed_area`) exercised from both Rust and Python, lint and type-check configuration, CI on Linux and Windows.

## Phase 1: contracts and fixtures

- Python models: `PuzzleInstance`, `Piece`, `Pose`, `TolerancePolicy`, `Solution`, `SolveResult`, `SolverConfig`. Mirror the instance types in `tiling-core`.
- `schemas/instance-v1.json`: the versioned instance format.
- `io/tropical.py`: importer for the source `puzzle.json`, and the sanitizer described in [architecture.md](architecture.md#sanitization). It emits an instance per information regime: footprint, relief, and tropical-aware, the last keeping the `tropical` block in a separate field.
- `scripts/import_fixtures.py --source ../tropical-puzzle-lab` writes:
  - `benchmarks/fixtures/<id>.json`, recording the source `geometryHash` and commit;
  - `tests/keys/<id>.json`, the reference poses carried through the same rotation and shuffle.
- Synthetic fixtures with known solution counts: a square split into two rectangles, a 2×2 grid of identical squares, a triangle dissection.
- `load_puzzle()` in the public API.

**Exit:** all 16 fixtures and the synthetics load and validate against the schema. A test asserts that no fixture contains reference poses, tropical data or original piece ids, and that no piece is stored in its solved orientation.

## Phase 2: independent validator

- `validation.py` on Shapely (optional extra `validate`), implementing the four completion checks of the browser player:
  - overlap: penetration depth of every pair;
  - inside: no vertex farther outside the target than the tolerance;
  - area: overlap plus outside area, and uncovered area, computed from an exact union (the browser uses a first-order approximation);
  - roof, relief only: height mismatch along antiparallel shared edges.
- Tolerances come from `TolerancePolicy`, defaulting to the source `validation` block scaled by span, area and relief height.
- The result carries residuals for each check, not only pass or fail.
- It must not import `_native`.

**Exit:** every answer key validates. Perturbed keys fail the expected check: a shifted piece, a rotated piece, two swapped pieces, and a relief assembly that tiles but has mismatched roofs.

## Phase 3: Rust geometry kernel

- In `tiling-geometry`: a convex polygon type, rigid transforms, SAT penetration depth, convex clipping and intersection area, containment and outside depth, edge extraction, and edge signatures (length, adjacent angles, roof heights at the ends).
- Property tests with proptest.
- Exposed through `_native` with stubs in `_native.pyi`.
- Decide here whether `geo` earns a place or the convex routines suffice.

**Exit:** differential tests agree with the Shapely validator on random poses of fixture pieces, within a stated tolerance.

## Phase 4: contact candidates, Python prototype, solver contract

- Candidate API in Rust: `propose(state, frontier)` and `check_placement(state, pose)`. A contact is a pair of antiparallel flush edges with aligned endpoints, against a tray wall or a placed piece.
- `solvers/prototypes/contact_dfs.py`: integer indices, reversible state, deterministic iteration, geometry through `_native`. Footprint regime first.
- `api.solve()`, the solver registry, the metrics record, and a `maxplus-solve` command.
- `docs/algorithms.md`: the frontier rule and the argument that it loses no solutions, or a plain statement that it is heuristic.
- `docs/solver-contract.md`: status values and what each completeness claim means.

**Exit:** `python.contact_dfs` solves the 6-piece and 9-piece flat fixtures, and every solution it returns passes the validator.

## Phase 5: Rust contact DFS

- `tiling-search::contact_dfs`: the whole search in Rust, one boundary crossing per solve. Time limit, `max_solutions`, seed, and counts of nodes, backtracks and candidates.
- Relief filtering: roof heights must agree at the ends of a contact.
- Canonical solution form: identical pieces are interchangeable, and assemblies equal up to a rotation of the tray count once.
- Registered as `rust.contact_dfs`.

**Exit:** all 16 fixtures are solved and validated. Time to first solution and time to exhaust the search are reported separately. On the small fixtures the solution set equals the Python prototype's.

## Phase 6: CP-SAT backend

- `enumerate(instance, policy)` builds a finite candidate set; pairwise conflicts are precomputed in Rust.
- `solvers/cp_sat.py` (optional extra `cp-sat`): one Boolean per placement, exactly one placement per piece, pairwise conflict constraints. Enumeration runs single-worker with no objective.
- `SolveResult` records whether the candidate set is proven complete. `INFEASIBLE` is reported as relative to that set.
- Registered as `cp_sat.placements`.

**Exit:** CP-SAT and the Rust DFS produce the same canonical solution sets on every fixture where both exhaust.

## Phase 7: benchmark and research platform

- `benchmarks/manifests/` and `experiments/benchmark.py`, writing JSONL with solver version, input hash, seed, tolerances and configuration.
- Tolerance sweeps; relief against flat for the same footprints; search effort against the Leinster–Cobbold difficulty rating in the source `puzzles/index.json`.
- `experiments/plotting.py` and a first notebook (optional extra `analysis`).

**Exit:** one command reproduces a results table for the whole corpus across all registered solvers.

## Backlog

Unordered, to be scheduled once phase 7 shows where the interesting questions are:

- branch and bound in `tiling-search`;
- tolerance-aware search with continuous refinement of poses;
- a solver for the tropical-aware regime;
- exact or adaptive geometric predicates;
- Z3 or exact-cover backends;
- exporting results in a form the browser player can import.
