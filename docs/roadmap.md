# Roadmap

Each phase is sized for one working session and ends with an exit criterion that can be checked. Do them in order; each builds on the one before. The design behind them is in [architecture.md](architecture.md), and the algorithmic background in the [research brief](research-brief.md).

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

- In `tiling-geometry`: a convex polygon type, rigid transforms, SAT penetration depth, convex clipping and intersection area, containment and outside depth, edge extraction, and edge signatures (length, adjacent corner angles, roof heights at the ends, roof gradient).
- Relief primitives. Both roofs are affine, so along a shared straight segment the height difference is affine too: its maximum is at an endpoint, and comparing the two endpoint heights bounds the mismatch on the whole segment. Equivalently, the gradient difference must be normal to the edge, `(g1 − g2) · v = 0`; the gradients themselves need not be equal, since a ridge or valley is exactly where they differ.
- Property tests with proptest.
- Exposed through `_native` with stubs in `_native.pyi`.
- Decide here whether `geo` earns a place or the convex routines suffice.

**Exit:** differential tests agree with the Shapely validator on random poses of fixture pieces, within a stated tolerance.

## Phase 4: contact candidates, Python prototype, solver contract

- Candidate API in Rust: `propose(state, frontier)` and `check_placement(state, pose)`. A contact is a pair of antiparallel flush edges with a coinciding endpoint, which fixes the rotation and both translation components without any angular grid. Two sources in this phase: tray-edge placements and piece-edge placements.
- An edge compatibility graph over oriented piece and tray edges, built once from the signatures; rigid transforms are generated lazily from its arcs.
- `solvers/prototypes/contact_dfs.py`: integer indices, reversible state, deterministic iteration, geometry through `_native`. Footprint regime first. The frontier rule is minimum remaining values: branch on the exposed edge with the fewest legal mates.
- `api.solve()`, the solver registry, the metrics record, and a `maxplus-solve` command.
- `docs/algorithms.md`: the frontier rule and the argument that it loses no solutions, or a plain statement that it is heuristic.
- `docs/solver-contract.md`: status values and what each completeness claim means.

**Exit:** `python.contact_dfs` solves the 6-piece and 9-piece flat fixtures, and every solution it returns passes the validator.

## Phase 5: Rust contact DFS

- `tiling-search::contact_dfs`: the whole search in Rust, one boundary crossing per solve. Time limit, `max_solutions`, seed, and counts of nodes, backtracks and candidates.
- Collinear-chain placements: one long edge mating with a run of shorter collinear edges, with offsets taken from endpoint coincidences.
- Relief filtering: the tangential-gradient test before any polygon work, then roof heights at the ends of the contact.
- Cavity pruning: reject a partial assembly that leaves an uncovered component no subset of the remaining pieces can fill, by area or by minimum width.
- Symmetry: anchor the first placement to break the tray's rotations, and order geometrically identical pieces.
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
- The factorial experiment the brief singles out: flat against relief × tolerance × search heuristic × puzzle family, with ambiguity and uniqueness measured explicitly.
- Tolerance as a two-dimensional grid, pose and penetration tolerance against roof-height tolerance, spaced geometrically near any apparent transition. Time to first solution and time to exhaust are expected to move in opposite directions as tolerance widens; test that.
- Difficulty proxies per instance: compatible-edge degree, fraction of edges with a unique mate, contradiction depth, symmetry count, geometry checks per node. Compare them, and node counts under several fixed heuristics, with the Leinster–Cobbold rating in the source `puzzles/index.json`.
- `experiments/plotting.py` and a first notebook (optional extra `analysis`).

**Exit:** one command reproduces a results table for the whole corpus across all registered solvers.

## Backlog

Unordered, to be scheduled once phase 7 shows where the interesting questions are:

- a proof, for the subdivisions the generator produces, that contact-generated placements are complete, which is what would turn "no solution found" into a real claim;
- vertex-contact rescue placements, for assemblies that no full edge match can extend;
- nogood learning and memoization of partial states by canonical contact graph;
- branch and bound in `tiling-search`;
- tolerance-aware search with continuous refinement of poses, including loop-closure checks on relative transforms;
- a solver for the tropical-aware regime, and tropical pruning beyond roof continuity (balancing conditions, admissible gradient sequences), experimental until proved;
- exact or adaptive geometric predicates;
- Z3, DLX exact-cover and MILP soft-mismatch backends;
- comparison with human solve times from the browser player's report lines;
- exporting results in a form the browser player can import.
