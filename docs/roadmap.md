# Roadmap

Each phase is sized for one working session and ends with an exit criterion that can be checked. Do them in order; each builds on the one before. The design behind them is in [architecture.md](architecture.md), and the algorithmic background in the [research brief](research-brief.md).

| Phase | Subject | Status |
| --- | --- | --- |
| 0 | Repository skeleton | Done |
| 1 | Contracts and fixtures | Done |
| 2 | Independent validator | Done |
| 3 | Rust geometry kernel | Done |
| 4 | Contact candidates, Python prototype, solver contract | Done |
| 5 | Rust contact DFS | Done |
| 6 | CP-SAT backend | Next |
| 7 | Benchmark and research platform | |

The source corpus is 8 constructions in two variants each (relief and flat), 16 puzzles of 6 to 20 convex pieces with 3 to 8 vertices, in a 144 mm square tray.

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

Done, with these decisions:

- The exit criterion is `tests/corpus/`. The testing rules that came out of this phase are in [CLAUDE.md](../CLAUDE.md#testing).
- Committed fixtures are footprint (the `-flat` puzzles) and relief. The importer also builds tropical-aware instances, but none is committed until a solver for that regime exists.
- The sanitizer seed is recorded in the answer key and not in the fixture, because the rotations can be recomputed from it. Each polygon's starting vertex is randomized as well.
- A puzzle and its flat twin are sanitized with unrelated seeds, so a flat solution does not transfer pose for pose.
- "Solved orientation" is measured between vertex sets, so a symmetric piece counts as solved in each of its equivalent orientations.
- There are four synthetics: two rectangles, the same with a ridge roof, four squares, and four triangles in a triangular target. Their keys record the solution count by construction, as tilings and up to rotation of the target. Corpus keys record no count: uniqueness there is an open question.
- The models are dataclasses with no runtime dependencies. The `tiling-core` mirror has no Python conversion yet; it arrives with the first Rust consumer, with a round-trip test.
- The keys are checked here for area, containment and roof continuity at shared corners. Pairwise overlap needs the validator of phase 2.

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

Done, with these decisions:

- The exit criterion is `tests/corpus/test_keys_validate.py`. Every piece of every fixture is shifted by 5 mm in four directions, turned by 20° both ways, and swapped with a piece of another shape; each must fail a depth check, not only the looser area check.
- "Tiles but has mismatched roofs" is tested on the ridge synthetic and on every corpus piece whose footprint is unchanged by half a turn. Half-turned, such a piece must fail the roof check and nothing else.
- The validator differs from the browser in three places, each time on the stricter or more exact side: uncovered area from an exact union; outside depth as Euclidean distance to the target, which is larger beyond a corner; and penetration depth as the true shortest separating translation. The browser's formula for the last takes the shared extent along each edge normal, which understates the depth when one piece's extent lies inside the other's. They agree for every near-solution.
- A finding about the corpus: `rat1` has a rectangular piece with a level roof (`p02` in the fixture). It fits both ways round, so the relief puzzle has at least two solutions at the level of poses, though one assembly. A test pins this so the corpus cannot change unnoticed. Canonical solution forms in phase 5 must treat the two as equal.
- Phase 3 follows from the penetration decision: the Rust SAT routine must return the true separating distance, or the differential tests against this validator will disagree on nested pieces.

## Phase 3: Rust geometry kernel

- In `tiling-geometry`: a convex polygon type, rigid transforms, SAT penetration depth, convex clipping and intersection area, containment and outside depth, edge extraction, and edge signatures (length, adjacent corner angles, roof heights at the ends, roof gradient).
- Relief primitives. Both roofs are affine, so along a shared straight segment the height difference is affine too: its maximum is at an endpoint, and comparing the two endpoint heights bounds the mismatch on the whole segment. Equivalently, the gradient difference must be normal to the edge, `(g1 − g2) · v = 0`; the gradients themselves need not be equal, since a ridge or valley is exactly where they differ.
- Property tests with proptest.
- Exposed through `_native` with stubs in `_native.pyi`.
- Decide here whether `geo` earns a place or the convex routines suffice.

**Exit:** differential tests agree with the Shapely validator on random poses of fixture pieces, within a stated tolerance.

Done, with these decisions:

- The exit criterion is `tests/corpus/test_native_agrees_with_validator.py`. For every fixture, pieces are thrown at seeded random poses and each quantity is computed twice, by `_native` and by the validator, Shapely or the Python models. The tolerances are 1e-9 mm for lengths (penetration depth, outside depth, roof heights) and 1e-6 mm² for areas. Whole assemblies, keyed and disturbed by 0.01 mm to a few millimetres, give the same overlap and outside residuals by both routes.
- The same comparisons run on random convex polygons in `tests/property/test_native_properties.py`, and the kernel has its own proptest properties beside the code.
- The tests were made to fail once by hand: with the browser's shared-extent formula in place of the separating distance, and with one clipping edge dropped. Both turned the differential tests red.
- A finding about the oracle: CI on Linux produced two triangles, the kernel's intersection and Shapely's, equal to one unit in the last place, for which GEOS 3.14 reports no shared area. The kernel was right. Results are therefore compared with Shapely by distance and area, never by overlaying two nearly coincident polygons, and the case is pinned as an example. The validator overlays pieces with one another, not with copies of themselves; if two pieces ever coincide to rounding, its area residual may be understated, while the depth check, which does not use GEOS, still fails.
- `geo` is not added. Everything in this phase is a convex routine of a few lines, the corpus targets are convex, and GEOS through Shapely already serves as the independent cross-check. General polygon operations (unions, non-convex free regions) have no user yet; the question reopens with the first solver that needs one.
- Edge signatures carry the roof's slope along the edge and along its outward normal, not a gradient vector: both numbers are unchanged by a rigid motion, so signatures can be compared before any pose exists.
- What is not here: finding which edges of two placed pieces are shared. The kernel measures the roof step along a given segment; choosing the segments is contact matching, in phase 4. The differential roof test therefore uses the edges two pieces share end to end, which is a subset of the seams the validator examines.
- `_native` takes polygons as sequences of pairs, poses as `(x, y, theta)` and roofs as `(z0, gx, gy)`. These are prototype-facing primitives; a production solver receives the whole instance once.

## Phase 4: contact candidates, Python prototype, solver contract

- Candidate API in Rust: `propose(state, frontier)` and `check_placement(state, pose)`. A contact is a pair of antiparallel flush edges with a coinciding endpoint, which fixes the rotation and both translation components without any angular grid. Two sources in this phase: tray-edge placements and piece-edge placements.
- An edge compatibility graph over oriented piece and tray edges, built once from the signatures; rigid transforms are generated lazily from its arcs.
- `solvers/prototypes/contact_dfs.py`: integer indices, reversible state, deterministic iteration, geometry through `_native`. Footprint regime first. The frontier rule is minimum remaining values: branch on the exposed edge with the fewest legal mates.
- `api.solve()`, the solver registry, the metrics record, and a `maxplus-solve` command.
- `docs/algorithms.md`: the frontier rule and the argument that it loses no solutions, or a plain statement that it is heuristic.
- `docs/solver-contract.md`: status values and what each completeness claim means.

**Exit:** `python.contact_dfs` solves the 6-piece and 9-piece flat fixtures, and every solution it returns passes the validator.

Done, with these decisions:

- The exit criterion is `tests/corpus/test_contact_dfs_solves.py`. The four small flat fixtures are solved, the searches are also run to their end, and every assembly returned passes the validator as an exact tiling.
- The frontier is corners, not edges. The search branches on one convex corner of the uncovered region, the one with the fewest candidates, and a candidate puts a piece vertex at the corner with the edge leaving it flush against the corner's first side. [algorithms.md](algorithms.md) gives the argument that this loses no exact assembly of convex pieces. The corners are found from the directions each polygon occupies around a vertex; the uncovered region is never built as a polygon, so no general polygon library is needed.
- The candidate interface is `_native.Assembly`: `frontier()`, `propose(corner)`, `check_placement(piece, pose)`, with `place` and `undo` as a stack. It lives in `tiling-geometry` (`contact`, `graph`, `assembly`).
- The edge compatibility graph rules out nothing in the footprint regime: pieces need not meet edge to edge, so lengths prove nothing. With roofs it keeps only edge pairs whose slopes along the edge cancel, which removes more than half of all pairs on the corpus and keeps every contact in the answer keys. The same signatures identify congruent pieces and a piece's own symmetry, and proposals leave those repetitions out.
- `candidates_proven_complete` stays `false`. The argument is about exact arithmetic and exact assemblies; the code is `f64` with tolerances, and the validator also accepts arrangements that are not exact.
- `SolveResult` gained `candidate_set`, `config` and `solver_version`, and `Solution` gained `valid`. `no_solution_found` now requires an exhaustive search and `interrupted` forbids one. [solver-contract.md](solver-contract.md) is the reference.
- `solve(..., validate=True)` runs the validator on what a solver returns. No solver calls it; an architecture test checks that.
- Tests beyond the exit: the frontier against the corners of `target − union(placed)` from GEOS, `check_placement` against Shapely and the validator, `propose` against a brute-force enumeration with the test oracle, and in Rust a property over random tilings cut by chords that every convex corner is offered its true filler. Each was made to fail once by breaking the code.
- Findings, relative to the candidates generated. The 6-piece and 9-piece footprint puzzles each have exactly one assembly, found in the tray's four orientations. `rat1-flat` (11 pieces) has 101; all pass the validator; the count is pinned by a test. The prototype does not finish the 16-piece footprint puzzles in 90 s and finds a first assembly of the 20-piece one in about 7 s.
- For phase 5: by the corner argument, collinear-chain placements add no assemblies, since a piece lying against a run of shorter edges still has a vertex in a convex corner. They should be implemented only if measurements show the search needs them. What the measurements do ask for is pruning, and removing the tray's rotations.

## Phase 5: Rust contact DFS

- `tiling-search::contact_dfs`: the whole search in Rust, one boundary crossing per solve. Time limit, `max_solutions`, seed, and counts of nodes, backtracks and candidates.
- Collinear-chain placements: one long edge mating with a run of shorter collinear edges, with offsets taken from endpoint coincidences. (Phase 4 found these are not needed for completeness; see its decisions.)
- Relief filtering: the tangential-gradient test before any polygon work, then roof heights at the ends of the contact.
- Cavity pruning: reject a partial assembly that leaves an uncovered component no subset of the remaining pieces can fill, by area or by minimum width.
- Symmetry: anchor the first placement to break the tray's rotations, and order geometrically identical pieces.
- Canonical solution form: identical pieces are interchangeable, and assemblies equal up to a rotation of the tray count once.
- Registered as `rust.contact_dfs`.

**Exit:** all 16 fixtures are solved and validated. Time to first solution and time to exhaust the search are reported separately. On the small fixtures the solution set equals the Python prototype's.

Done, with these decisions:

- The exit criterion is `tests/corpus/test_rust_contact_dfs.py`. Each of the 16 fixtures is searched to the end in its own regime; every assembly returned passes the validator as an exact tiling, with continuous roofs in relief; the answer key is among them. `first_solution_s` and `exhausted_s` are separate metrics. On the five footprint fixtures the prototype can finish, the two solvers return the same assemblies, and with its additions switched off the Rust search visits exactly the prototype's nodes.
- The lens is difficulty, not speed. Every rule beyond the prototype's is a switch in `SolverConfig.options`, and the whole search is tested to find the same assemblies with each switch on and off. What each rule buys is measured and tabulated in [algorithms.md](algorithms.md#what-makes-a-puzzle-hard-and-what-helps).
- Relief filtering is in candidate generation: a placement is refused if its roof height at the corner differs from the roof already there, before any polygon work, and if its roof steps along any edge stretch shared with a placed piece. The candidate set of the relief regime is named `corner-contact-relief/1`.
- Cavity pruning by area and by least width, as planned. It turned out to matter little: on the corpus it never changes a node count by more than one percent.
- Closure pruning, which the roadmap did not foresee and which is the pruning rule that works on footprints: a straight run of boundary between two convex corners must be a sum of whole edges of different remaining pieces, and a convex corner a sum of their angles.
- Looking one placement ahead is implemented and off by default. It cuts the nodes visited by a factor of 3 to 60; counted in states examined it wins on three footprint fixtures and loses on five, worst on the hardest.
- Symmetry: one piece, the largest that is congruent to no other, is held to one sector of the tray, and repeats are removed by comparing canonical forms. `tray_rotations=all` restores the prototype's counting. Congruent pieces and self-symmetric pieces were already handled where candidates are generated.
- Canonical form (`tiling-search::canonical`): seats, a centroid and a turn modulo the piece's symmetry, sorted within each class of congruent pieces, smallest over the tray's rotations. Congruent pieces are stored at unrelated rotations by the sanitizer; the turn is measured relative to the class's first piece. The validator caught the first version getting that wrong on the synthetic fixtures.
- Collinear-chain placements are not implemented. The corner argument of phase 4 shows they add no assemblies, and no measurement asked for them.
- Candidate ordering is an option: by matched edges (the default), as generated, or random from the seed.
- `SolverSpec` now maps each regime to its candidate set. `maxplus-solve` takes `--option NAME=VALUE` and defaults to `rust.contact_dfs`.
- `tiling-geometry` exposes its proptest strategies behind a `testing` feature, so that `tiling-search` tests its search on the same random tilings.
- Tests beyond the exit: cavities against a Shapely difference, the roof step of a placement against the validator's seam mismatch, canonical forms against the polygon-set oracle, properties in Rust over random tilings cut by chords (the search finds the tiling it was cut from; no rule changes what is found; roofs under one plane are continuous and a lifted one is not), and an architecture test that a production solver makes one `_native` call. The rules were each broken by hand once and the tests watched to fail.
- Findings, relative to the candidates generated. In relief every corpus puzzle has exactly one assembly, and the search for it is nearly free of backtracking: at most 146 nodes for 20 pieces with every rule off. As footprints, six of the eight have one assembly, `rat1-flat` has 101 and `rat2-flat` has 2. The roofs single out one of `rat1`'s 101. The hard instances are the 16-piece footprints: about a million nodes each to finish, and for `new1-flat` hundreds of thousands to the first solution.
- For later phases: the 16-piece footprint searches are the benchmark that pruning or learning has to move. Both are dominated by dead ends five or six pieces deep that no current rule sees coming.

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
