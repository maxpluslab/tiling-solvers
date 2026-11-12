# Architecture

This is the charter for the repository: what it is for, how it is layered, and the decisions that are fixed. The order of work is in [roadmap.md](roadmap.md).

The algorithmic background is the [research brief](research-brief.md): problem taxonomy, solver families, tolerance models, tropical-specific constraints and the literature. Where the two differ, this document decides. The brief sketches a pure-Python `solver/` package with Shapely in the search path; here the search and its geometry are in Rust, and Shapely is confined to the independent validator.

## Purpose

A solver laboratory, not a single solver. It should be easy to:

- develop and compare several custom Rust algorithms;
- use established engines such as OR-Tools CP-SAT;
- prototype in Python and move the hot parts to Rust;
- share geometry, candidate generation, input formats, validation and benchmarking across solvers;
- study puzzle difficulty, ambiguity, uniqueness and the effect of geometric tolerances.

Geometry is a reusable capability, solvers are interchangeable algorithms, and experiments are first-class research artifacts.

## Layers

| Layer | Contents | Language |
| --- | --- | --- |
| Application and experiments | CLI, notebooks, benchmark runner, plots, solver registry | Python |
| Contracts | Puzzle instance, solver config, solve result | Python models, mirrored in `tiling-core` |
| Solvers | Rust solvers (contact DFS, branch and bound, later ones); external solvers (CP-SAT, later Z3 or exact cover); Python prototypes | Rust and Python |
| Geometry and candidates | Convex polygons, transforms, overlap and containment, contact matching, relief constraints | Rust (`tiling-geometry`) |
| Data and validation | Sanitized instances, independent solution checking, reproducible corpus | Python |

Puzzle representation, geometric reasoning and search are kept apart. Different solvers reuse the same geometric primitives without being forced into the same search strategy.

## Two interfaces

### Solver interface

Every solver takes an instance and a configuration and returns a standard result.

```python
from maxplus_solvers import load_puzzle, solve, SolverConfig

puzzle = load_puzzle("benchmarks/fixtures/new2.json")
result = solve(
    puzzle,
    SolverConfig(
        solver="rust.contact_dfs",
        mode="relief",
        time_limit_s=60,
        max_solutions=2,
        seed=42,
    ),
)
print(result.status, result.solutions, result.metrics)
```

Switching solver means changing `solver` to, say, `cp_sat.placements` or `python.contact_dfs`. Every result has the same representation of piece poses, completion status, search metrics and completeness claims.

### Candidate interface

Solvers use candidates differently. A backtracker generates placements lazily at exposed edges; CP-SAT needs a finite universe built before solving. Both are supported.

| Operation | Purpose |
| --- | --- |
| `propose(state, frontier)` | Generate candidates lazily during search |
| `enumerate(instance, policy)` | Build a finite candidate set for CP-SAT and similar solvers |
| `check_placement(state, pose)` | Evaluate containment, collisions and relief |
| `validate_solution(instance, poses)` | Check a whole assembly, independently of the search |

The first three are implemented in `tiling-geometry`. A solver that needs none of them (contact-graph assembly, say) is free to ignore them.

## Data model

| Object | Contents |
| --- | --- |
| `PuzzleInstance` | Target polygon, pieces, physical constraints, provenance |
| `Piece` | Local polygon, optional roof plane, stable opaque identity |
| `Pose` | `x`, `y`, `theta` |
| `TolerancePolicy` | Separate overlap, outside, coverage, angle and roof tolerances |
| `CandidatePlacement` | Piece index, pose, generating contact, optional scores |
| `Solution` | Piece poses, validation residuals |
| `SolveResult` | Status, solutions, metrics, completeness metadata |

Coordinates are millimetres and radians, as in the browser player; there are no normalized units in the core. `PuzzleInstance` is independent of the source `puzzle.json` format.

### Information regimes

| Regime | What the solver sees |
| --- | --- |
| Footprint | Polygon geometry only |
| Relief | Polygons and the physically observable roof planes |
| Tropical-aware | Construction-level information as well, such as the tropical coefficients |

They are separate because construction metadata could make a puzzle computationally trivial for reasons unrelated to its physical difficulty.

### Assumptions

Across the regimes runs a second axis: what a solver may take for granted about the assembly, without being told anything more about the pieces. The one so far is `edge-to-edge`, that pieces never meet in a T, which every tropical cut satisfies and which can be made with roofs or without. An assumption narrows what is looked for, so unlike a pruning rule it can change what a search finds. A solver declares the assumptions it can make, a result records the ones it made and names a candidate set that says so, and results under different assumptions are not compared. The contract is in [solver-contract.md](solver-contract.md#assumptions).

### Sanitization

The source `puzzle.json` reveals the answer in three ways:

1. `reference.poses` is the solved assembly.
2. Every reference `theta` is 0, so each piece's stored polygon is already in its solved orientation, and its centroid offset is all that is missing.
3. Piece ids (`Ab`, `Cd`) name the tropical terms, and piece order is construction order.

Two smaller leaks are closed as well:

4. The starting vertex of each polygon, which the generator chooses consistently. Each vertex list is cyclically shifted by a random amount.
5. The sanitizer's own seed. The rotation angles can be recomputed from it, so it is recorded in the answer key and never in the instance.

An instance is therefore built by rotating each piece by a seeded random angle (the roof gradient rotates with it), shifting its starting vertex, shuffling the pieces, assigning opaque ids, and dropping `reference`, `tropical`, `provenance`, `scramble`, names and descriptions. A rotation is redrawn until the stored polygon differs visibly from its solved orientation as a set of vertices, so that a square turned by a quarter does not count as moved. A puzzle and its flat variant get unrelated seeds. The reference poses are carried through the same transformation into a separate answer key, used by tests and diagnostics and never by a solver. The browser itself judges completion by geometric feasibility, not by equality to the reference.

## Geometry

| Area | Operations |
| --- | --- |
| Basic | Convex polygon operations, orientation, rigid transforms, edge extraction, point and segment tests, SAT collision and penetration depth, containment, intersection |
| Contact | Edge signatures, possible mates, antiparallel alignment, collinear interval overlap, partial-edge contact, candidate transforms |
| Relief | Roof height matching at edge endpoints, tangential gradient agreement, continuity checks |
| Solution checking | Whole-assembly overlap, uncovered target area, boundary error, maximum roof mismatch |

Two facts make relief checks cheap and exact in form. Roofs are affine, so the height difference of two roofs along a shared straight segment is affine and its maximum lies at an endpoint: comparing endpoint heights bounds the mismatch on the whole segment. And two roofs that agree along an edge with tangent v satisfy (g₁ − g₂) · v = 0. Requiring equal gradients would be wrong, because ridges and valleys are where they differ.

Candidate placements come from contacts, never from an angular grid: aligning a piece edge antiparallel to a fixed edge sets the rotation, and an endpoint coincidence sets the translation. The sources, in the order they are implemented, are tray edges, exposed piece edges, collinear chains of edges, and vertex contacts as a rescue. Whether these are complete for the generator's subdivisions is an open question, and results must say so.

Numbers are `f64` with explicit tolerances and property tests. Exact or adaptive predicates can follow if experiments expose problems. A floating-point implementation is not a guarantee of mathematical exactness and results must not be described as one.

The kernel is specialized convex routines with no geometry dependency. The [`geo`](https://docs.rs/geo) crate was considered in phase 3 and left out: nothing yet needs general polygon operations, and GEOS through Shapely is the cross-check. The Rust geometry is tested differentially against the validator on random poses of fixture pieces.

The final validator is kept independent of this engine, on Shapely at first, so that one bug cannot affect both search and verification. Its rules mirror the browser's completion check in `tropical-puzzle-lab/web/src/geometry/evaluate.ts`, and where it departs from it the validator is the stricter or more exact of the two: uncovered area comes from an exact union, outside depth is the Euclidean distance to the target, and penetration depth is the true shortest separating translation. The last two coincide with the browser's values for any near-solution.

## CP-SAT

Given a finite candidate set P_i for each piece i, with one Boolean x_ip per placement:

- exactly one placement per piece: Σ_p x_ip = 1;
- for each incompatible pair: x_ip + x_jq ≤ 1.

Conflicts are precomputed by the Rust geometry. If all pieces lie inside the target with disjoint interiors and their total area equals the target area, coverage follows, so no exact-cover grid is needed in the exact formulation. The tolerant formulation still validates coverage explicitly.

`INFEASIBLE` means infeasible within the generated candidate set, unless that set has been proven complete. The API preserves the distinction. Complete enumeration in CP-SAT cannot use an objective and runs with a single search worker.

As built (phase 6), the candidate set is the placements the Rust contact search reaches, congruent pieces share their placements (a class of k pieces takes k of them), and conflicts are stated mostly as "at most one of the placements that hold this point" instead of pair by pair. Coverage constraints, "at least one of the placements that reach this point", are added although they follow from the rest: without them CP-SAT is far slower than the search. [algorithms.md](algorithms.md#choosing-from-a-list-cp-sat) has the model and the measurements.

## Python to Rust

Algorithms are prototyped in Python without making Python-specific machinery part of the design: integer piece and candidate indices, typed state, reversible assignments, deterministic iteration. Prototypes call the same Rust geometry as production solvers, so porting replaces search state and control flow, not geometry.

Bindings are PyO3 built by maturin into the private module `maxplus_solvers._native`. Production solvers receive the puzzle once and run the whole search in Rust; the boundary is not crossed per node.

## Benchmarking

Recorded for every run:

| Category | Metrics |
| --- | --- |
| Performance | Wall time, CPU time. Peak memory is not recorded yet: nothing here measures it the same way on both platforms. |
| Search effort | Nodes, backtracks, depth, propagations |
| Geometry | Candidate placements, compatibility checks, rejected collisions |
| Outcomes | First solution, solutions found, whether the search was exhaustive |
| Validity | Coverage, overlap, exterior penetration, roof mismatch |
| Reproducibility | Solver version, input hash, seed, tolerances, configuration |

Time to first solution and time to establish uniqueness are reported separately. Equivalent assemblies have a canonical form, so swapping indistinguishable pieces does not inflate solution counts.

## Tooling

| Component | Choice |
| --- | --- |
| Python environment | uv |
| Rust build | Cargo workspace |
| Binding | PyO3 and maturin, stable ABI |
| Python tests | pytest |
| Rust tests | `cargo test`, proptest |
| Static checks | Ruff, Pyright, Clippy, rustfmt |
| External solver | OR-Tools, optional dependency |
| Analysis | Jupyter, Polars, matplotlib, optional dependencies |
| CI | GitHub Actions on Linux and Windows |

## Fixed decisions

| Decision | Choice |
| --- | --- |
| Programming model | Python orchestration, Rust kernels and search |
| Layout | One repository, one Cargo workspace, one Python package |
| Domain abstraction | `PuzzleInstance` with convex polygons and optional affine roofs |
| Solver abstraction | Common `solve()` contract, optional candidate API |
| First custom solver | Rust contact-based DFS |
| First external backend | OR-Tools CP-SAT |
| Python prototypes | First-class, written with Rust-compatible logic |
| Validation | Independent of the search algorithm |
| Scientific integrity | Sanitized benchmarks, explicit completeness and uniqueness claims |
| Puzzle generation | Stays in Tropical Puzzle Lab; this repository consumes its published format |
