# Algorithms

How the solvers in this repository search, and what can be said for each rule. The contract every solver answers to is in [solver-contract.md](solver-contract.md); the design around them is in [architecture.md](architecture.md).

Statements marked **Argument** are reasoning about exact assemblies in exact arithmetic. The code computes in `f64` with tolerances. Its results are evidence for what the arguments say, never a proof of it.

## Contact search by corners

Used by `python.contact_dfs`. The geometry is in `tiling-geometry` (`contact`, `graph`, `assembly`) and reaches Python as `_native.Assembly`.

### State

A partial assembly: the target, and some pieces placed inside it without overlapping. Pieces are placed and taken back in stack order. The *uncovered region* is the target minus the placed pieces.

### Corners of the uncovered region

The uncovered region is never built as a polygon. Its corners are found locally.

Every corner of the region lies at a vertex of the target or of a placed piece. Around such a point, each polygon that touches it occupies a known range of directions:

| The point is | Directions occupied |
| --- | --- |
| a vertex of a placed piece | the piece's interior angle there |
| inside an edge of a placed piece | the half turn on the piece's side |
| a vertex of the target | everything outside the target's interior angle |
| inside an edge of the target | the half turn outside |
| strictly inside a placed piece | all of them: no corner here |

The ranges are merged around the circle. Each gap they leave is a *free wedge*: a corner of the uncovered region, given by its point, the direction of its first side, and its angle, counter-clockwise. The first side runs along an edge of the tray or of a placed piece, with uncovered area on its left. A gap of exactly a half turn is the middle of a straight run and is not a corner. A corner is *convex* if its angle is less than a half turn.

A point can carry more than one corner, where the uncovered region touches itself. Holes need no special handling: their corners are found the same way.

This is tested against GEOS on partly assembled fixtures: the corners found this way are the corners of `target − union(placed)` as Shapely computes it (`tests/corpus/test_candidates_agree_with_shapely.py`).

### Candidates for a corner

A piece is put into a corner by a contact: one of its vertices at the corner, and the edge leaving that vertex along the corner's first side. That fixes the rotation and both components of the translation. There is no angular grid.

`propose(corner)` returns, for every unplaced piece and every vertex of it whose interior angle is at most the corner's angle, that placement, provided it stays inside the target and enters no placed piece. The corner's first side belongs either to the tray or to a placed piece; those are the two sources of candidates, tray-edge and piece-edge contacts, and they are handled alike.

### The branching rule

At each node:

1. Find the corners of the uncovered region. If every piece is placed, the node is a solution exactly when there are none.
2. For each convex corner, compute its candidates.
3. Take the corner with the fewest candidates (the first such corner, in a fixed order). If it has none, the node is a dead end.
4. Try each of its candidates in turn.

Only one corner is branched on. The others are filled lower in the tree.

### Why the rule loses no assembly

**Argument.** Let the state be extendable: some placement of the remaining pieces, all convex, covers the uncovered region exactly.

*A convex corner exists.* The uncovered region is a non-empty polygonal region. Take its lowest point, and the leftmost if there are several. All of the region near that point lies above it or level to its right, so the wedge there spans less than a half turn.

*Any convex corner is filled by one of its candidates.* Take a convex corner at V with first side along the direction d. Points just inside the wedge, next to the first side and close to V, are uncovered, so in the completed assembly they belong to remaining pieces; since there are finitely many pieces, one piece P contains such points arbitrarily close to V. P is closed, so V is in P. P lies in the uncovered region, so near V it stays inside the region's wedges there, and it reaches the first side of this one. P is convex with positive area, so near V it is itself a wedge; that wedge contains d and nothing clockwise of d, since nothing clockwise of d is uncovered. Therefore V is a vertex of P, the edge of P that leaves V runs along d, and P's angle at V is at most the corner's angle, which is less than a half turn. That is one of the placements `propose` generates, and it passes the checks because it is part of a valid assembly.

So branching on any single convex corner, over all of its candidates, reaches every completion of the state. Choosing the corner with the fewest candidates is a choice among equally sound options: it changes the size of the tree, not the set of leaves. In a given completion each corner is filled by one piece in one position, so no completion is reached twice.

Three things this argument does not use, which is why they are not in the code: the pieces need not meet edge to edge; a piece edge that lies against several shorter collinear edges needs no separate "chain" placement, because the piece still has its vertex in some convex corner; and no placement is ever generated from a reflex corner.

The property is tested directly. For random convex polygons cut into convex pieces by chords, with any subset of the pieces in place, every convex corner's proposals include the piece that fills that corner in the tiling the pieces were cut from (`every_convex_corner_is_offered_its_true_filler` in `assembly.rs`), and the same on partly assembled fixtures against the answer keys. Both tests fail when the angle filter or the corner detection is broken by hand.

### What the argument does not cover

- **Arithmetic.** Coincidence is decided within a tolerance, the contact noise of the tolerance policy (1e-6 of the span, 0.000144 mm for the corpus). A corner narrower than the angle tolerance, or two features closer than the length tolerance, would be misjudged. Nothing in the corpus is near either.
- **Tolerant assemblies.** A finished assembly is judged by tolerances thousands of times looser (0.86 mm of overlap for the corpus). There are arrangements that pass those and are not exact assemblies; the search does not look for them. Whether such arrangements exist that are not small perturbations of an exact assembly is one of the questions this laboratory is for.
- **Non-convex pieces or targets.** The corner detection and the checks assume convexity.

For these reasons a result from this search reports `candidates_proven_complete = false`.

### What counts as one assembly

Two repetitions are removed where the candidates are generated, because they would multiply every count without telling anything apart:

- **Congruent pieces.** Of several unplaced pieces with the same shape (and the same roof, when roofs are in play), only the lowest-numbered is proposed for a corner.
- **A piece's own symmetry.** If a rotation maps a piece onto itself, the vertices that the rotation exchanges give the same placement, and only the first is proposed. A rectangle is tried at two of its vertices, a square at one.

Both are decided from the edge signatures, which is the job of the compatibility graph below. With them, four identical squares in a square tray are one assembly rather than 4! × 4⁴ labelled ones.

Rotations of the whole tray are *not* removed. A square tray gives each assembly four times unless the assembly has a rotational symmetry of its own. Removing them belongs to phase 5.

### The edge compatibility graph

Nodes are the oriented edges of the tray and of every piece; an arc from a fixed edge to a piece edge says the two may lie flush. It is built once from the edge signatures.

Without roofs the graph rules out nothing between different pieces. Pieces need not meet edge to edge, so lengths prove nothing, and whether an angle fits depends on the corner, which only the state knows. With roofs it prunes: two roofs are continuous along a shared edge only if their slopes along it agree, and the two edges run in opposite directions, so the slopes along them must cancel. On the corpus this removes more than half of all edge pairs, and it keeps every contact present in the answer keys. Poses are not stored on arcs; a pose is computed when a corner asks for one.

The prototype works in the footprint regime and so sees the unpruned graph. The pruned one is in place for the relief search of phase 5.

### What is not here yet

No pruning beyond the dead-end test: no check that a cavity can still be filled, no bound from areas or widths. These are phase 5. Their absence is visible in the numbers below.

### Measurements

From `python.contact_dfs` run to the end of its search on the footprint fixtures, on one machine. Node counts are deterministic; times are indicative only.

| Fixture | Pieces | Nodes | Assemblies found | Time |
| --- | --- | --- | --- | --- |
| `new5-flat` | 6 | 166 | 4, the answer key in 4 orientations | 5 ms |
| `rev2-flat` | 9 | 72 | 4, likewise | 3 ms |
| `new4-flat` | 9 | 2 862 | 4, likewise | 0.15 s |
| `new3-flat` | 9 | 9 080 | 4, likewise | 0.45 s |
| `rat1-flat` | 11 | 30 596 | 404: 101 assemblies in 4 orientations | 2.3 s |
| `new1-flat`, `new2-flat` | 16 | more than 500 000 | not finished in 90 s, none found | |
| `rat2-flat` | 20 | 25 485 to the first | first assembly in 7 s; not finished in 90 s | |

Two findings, both relative to the candidates generated:

- The 6-piece and 9-piece footprint puzzles have exactly one assembly each, up to turning the tray.
- `rat1` without its roofs has 101. Every one passes the validator as an exact tiling. Its pieces are mostly rectangles with commensurable sides, which can be rearranged in blocks. Whether the roofs single out one of the 101 is a question for the relief search.
