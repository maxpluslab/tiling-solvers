# Algorithms

How the solvers in this repository search, and what can be said for each rule. The contract every solver answers to is in [solver-contract.md](solver-contract.md); the design around them is in [architecture.md](architecture.md).

Statements marked **Argument** are reasoning about exact assemblies in exact arithmetic. The code computes in `f64` with tolerances. Its results are evidence for what the arguments say, never a proof of it.

## Contact search by corners

Used by `python.contact_dfs` and by `rust.contact_dfs`, which adds the rules of [the next section](#the-rust-contact-search). The geometry is in `tiling-geometry` (`contact`, `graph`, `assembly`) and reaches Python as `_native.Assembly`.

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

Rotations of the whole tray are *not* removed where candidates are generated. A square tray gives each assembly four times unless the assembly has a rotational symmetry of its own. The prototype returns all of them; `rust.contact_dfs` [removes them in the search](#the-trays-rotations).

### The edge compatibility graph

Nodes are the oriented edges of the tray and of every piece; an arc from a fixed edge to a piece edge says the two may lie flush. It is built once from the edge signatures.

Without roofs the graph rules out nothing between different pieces. Pieces need not meet edge to edge, so lengths prove nothing, and whether an angle fits depends on the corner, which only the state knows. With roofs it prunes: two roofs are continuous along a shared edge only if their slopes along it agree, and the two edges run in opposite directions, so the slopes along them must cancel. On the corpus this removes more than half of all edge pairs, and it keeps every contact present in the answer keys. Poses are not stored on arcs; a pose is computed when a corner asks for one.

The prototype works in the footprint regime and so sees the unpruned graph. The relief search of `rust.contact_dfs` uses the pruned one.

### What the prototype leaves out

No pruning beyond the dead-end test: no check that a cavity can still be filled, no bound from areas or widths. Their absence is visible in the numbers below, and they are the subject of the next section.

### Measurements of the prototype

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
- `rat1` without its roofs has 101. Every one passes the validator as an exact tiling. Its pieces are mostly rectangles with commensurable sides, which can be rearranged in blocks. The relief search answers whether the roofs single out one of the 101: [they do](#what-makes-a-puzzle-hard-and-what-helps).

## The Rust contact search

`rust.contact_dfs` (`tiling-search::contact_dfs`) is the search above, run entirely in Rust, with six additions. Each is an option that can be switched off (`SolverConfig.options`, listed in [solver-contract.md](solver-contract.md#options-of-rustcontact_dfs)), because the purpose of this solver is less to be fast than to show what makes a puzzle hard and which reasoning helps. With all of them off and `tray_rotations=all` it visits exactly the nodes the prototype visits, which a test checks count by count.

None of the additions changes what a whole search finds. For each there is an argument below, and a test that the set of assemblies found is the same with the rule on and off: on the corpus (`tests/corpus/test_rust_contact_dfs.py`) and in Rust on random convex polygons cut into pieces by chords (`the_rules_change_the_work_and_not_what_is_found`).

### Roofs

In the relief regime a placement must continue the roofs already down. Two tests, both inside candidate generation, so that a placement refused for its roof never counts towards a corner:

1. *At the corner, before any polygon work.* The corner's first side belongs to a placed piece. The roof of the candidate at its contact vertex must be as high as that piece's roof at the corner. This is one subtraction on numbers kept in the edge signatures.
2. *Along shared edges, after the placement is known to fit.* For every edge stretch the candidate shares with a placed piece, the two roofs are compared at both ends of the stretch. Roofs are planes, so their difference along a segment is largest at an end.

The tolerance on a height is the contact noise times the steepest roof gradient in the puzzle, and at least the contact noise: a point misplaced by the contact noise changes a roof's height by that much times its slope.

**Argument.** In an exact assembly with continuous roofs, every pair of neighbouring pieces agrees in height along the whole of their shared boundary, including the corner point. A placement that fails either test is part of no such assembly.

The second test is compared with the validator's seam check on the corpus: with one piece's roof raised or tilted, the step `Assembly.roof_step` reports is the validator's worst mismatch to 1e-9 mm.

### Cavity pruning (`cavity_pruning`)

The uncovered region falls into *cavities*, its connected pieces. They are traced from the corners: from each corner along its first side to the next corner on the boundary, until the loop closes. A cavity's area comes from the shoelace formula on its loop, and if the loop is convex its least width is computed. A state in which the loops do not close, or in which the uncovered region has a hole (a placed piece touching nothing), is not judged at all: the rule then prunes nothing.

A state is abandoned when

- some cavity's area is not the sum of the areas of any set of remaining pieces that could go into it, a piece being able to go into a cavity if its area is no larger and, for a convex cavity, its least width no larger; or
- some remaining piece can go into no cavity.

**Argument.** In a completion every remaining piece lies in the uncovered region. The interior of a piece is connected, so it lies in one cavity. The pieces in a cavity therefore tile it, and their areas add up to its area. A convex set inside another is no wider than it in any direction, so no wider in its narrowest.

The subset-sum question is answered by a bounded search, largest areas first. If the bound is reached the answer is "perhaps", which prunes nothing.

Cavities are compared with Shapely on partly assembled fixtures: `target − union(placed)` has the same components with the same areas and widths, and has a hole exactly when the trace declines.

### Closure pruning (`closure_pruning`)

Two necessary conditions that look only at the boundary of the uncovered region.

- *Runs.* Take a straight stretch of the boundary between two consecutive corners that are both convex. Its length must be a sum of edge lengths, one edge each from different remaining pieces.
- *Corners.* The angle of a convex corner must be a sum of interior angles, one each from different remaining pieces.

**Argument for runs.** Let the run go from A to B. In a completion, every point of the run is on the boundary of some remaining piece, and a convex piece that meets a line along more than a point, from one side, does so along a whole edge. At A the corner is convex: the uncovered region near A lies inside a wedge of less than a half turn, one of whose sides runs towards B. The continuation of the run backwards past A is outside that wedge, so no remaining piece has an edge reaching past A, and likewise past B. The edges lying on the run therefore lie within it, cover it and do not overlap: their lengths add up to its length. A convex piece has at most one edge on a line, so they belong to different pieces.

**Argument for corners.** By the corner argument of the previous section, a piece that contains the corner point V has a vertex there, since the wedge is narrower than a half turn. The remaining pieces that contain V are wedges at V near V; together they fill the corner's wedge without overlapping, so their angles at V add up to its angle. A piece has one vertex at V.

Both questions are "is this number a sum of one value each from some of these pieces", asked again and again about the same runs and corners as the search moves between neighbouring states. Answers are remembered per number: a set of pieces that supplied it still does while all of them are free, and a set that could not still cannot when pieces are taken away. The search for a sum is bounded, and reaching the bound answers "perhaps".

Runs with a reflex corner at an end are not tested: a piece may reach past a reflex corner, so the run's length need not be a sum of whole edges.

### Looking ahead (`lookahead`, off by default)

With this on, a placement counts towards a corner only if the state it leads to is not a dead end by the pruning rules that are on. The corner branched on is then the one with the fewest placements that *survive*, and the dead ones are never descended into. Corners are examined shortest list first, and a corner is dropped as soon as it cannot beat the best so far.

It is sound for the same reason the rules are: it removes only placements whose result the rules would abandon one node later. What it changes is the choice of corner, and the price is one placement, one corner scan and one round of pruning tests per candidate examined. The metric `pruned_lookahead` counts those; `nodes + pruned_lookahead` is the number of states the search examined, and that sum, not `nodes`, is what its time follows.

### The tray's rotations

(`tray_rotations`, `anchor`.) A tray with a rotational symmetry of order k gives every assembly k times, unless the assembly has that symmetry itself. With `tray_rotations=once` each family is returned once.

*The anchor.* One piece, the anchor, is only ever placed with its centroid in one sector of the tray: directions 0 to 2π/k as seen from the tray's centroid. The anchor is the largest piece that is congruent to no other, so that "the anchor" names one place in any assembly. If every piece has a twin there is no anchor, and nothing is pruned.

**Argument.** Take an assembly. Some rotation of the tray brings the anchor's centroid into the sector, because the k images of the sector cover the plane. That rotated assembly is a valid assembly and is not pruned.

A centroid on a sector boundary, or at the centre, lies in the sector under more than one rotation, and without an anchor every rotation is found. So complete assemblies are compared before they are returned, and one that is a rotation of an earlier one is counted in `duplicates` and dropped.

*Canonical form* (`tiling-search::canonical`). An assembly is described by a *seat* for each piece: where its centroid is, and how it is turned, the turn taken modulo the piece's own symmetry. Three things are removed:

- *which twin sits where:* within a class of congruent pieces, the seats are sorted and dealt out in piece order;
- *a piece turned onto itself:* by taking the turn modulo 2π over the order of the piece's symmetry;
- *the tray turned:* the seats are computed for each of the k rotations and the first list in order is kept.

Congruent pieces are not stored the same way round: the sanitizer turns each by its own random angle. A seat's turn is therefore measured for the first piece of the class, as the turn that piece would need to lie exactly there, and converted back for whichever twin receives the seat.

The order is by x, then y, then turn, with two numbers within the tolerance counted as equal. That is a workable order only because, in an assembly, seats that differ do so by millimetres and seats that agree do so to rounding.

Canonical forms are tested against an oracle that knows nothing of seats: two assemblies are the same when they put the same polygons in the same places (`tests/support/assemblies.py`).

### The order of candidates (`order`)

The branching rule fixes which corner is filled. The order in which that corner's placements are tried is free, changes nothing a whole search finds, and decides how soon the first solution turns up.

- `generated`: by piece, then by vertex, as `propose` returns them. The prototype's order.
- `matched-edges` (the default): placements that share the most whole edges with pieces already down come first; ties stay in generated order.
- `random`: shuffled by a generator seeded from `SolverConfig.seed`.

On the corpus, measured by nodes to the first solution with the default rules. The random column is five seeds: least, median, most.

| Fixture | Pieces | `matched-edges` | `generated` | `random` |
| --- | --- | --- | --- | --- |
| `new5-flat` | 6 | 55 | 55 | 24, 46, 88 |
| `new3-flat` | 9 | 135 | 139 | 1 862, 3 044, 4 512 |
| `new4-flat` | 9 | 377 | 386 | 73, 347, 457 |
| `rev2-flat` | 9 | 30 | 31 | 13, 31, 44 |
| `rat1-flat` | 11 | 334 | 345 | 167, 664, 1 887 |
| `new1-flat` | 16 | 803 543 | 803 632 | 98 078, 382 284, 955 946 |
| `new2-flat` | 16 | 392 912 | 392 980 | 16 262, 523 407, 889 623 |
| `rat2-flat` | 20 | 5 555 | 6 265 | 15 584, 50 253, 69 562 |

Preferring matched edges barely differs from the generated order: the corner rule already leaves few placements to order, and where the search goes wrong it does so near the root, where little is placed and nothing matches. A random order is sometimes fifty times quicker than either on the 16-piece puzzles and sometimes slower, which says the cost of the first solution there is mostly the luck of the first few placements.

### What makes a puzzle hard, and what helps

Whole searches of every corpus fixture with `rust.contact_dfs`, each rule switched off in turn. Counts are nodes; they are deterministic. "> n" is a search stopped at 90 s with n nodes visited. All statements are relative to the candidates generated, in `f64` with tolerances.

**With roofs** (relief regime):

| Fixture | Pieces | Assemblies | Nodes, default | Nodes, every rule off | Roof refusals, every rule off |
| --- | --- | --- | --- | --- | --- |
| `new5` | 6 | 1 | 26 | 41 | 200 |
| `new3` | 9 | 1 | 44 | 65 | 901 |
| `new4` | 9 | 1 | 45 | 65 | 720 |
| `rev2` | 9 | 1 | 26 | 49 | 21 |
| `rat1` | 11 | 1 | 90 | 122 | 1 924 |
| `new1` | 16 | 1 | 68 | 109 | 2 339 |
| `new2` | 16 | 1 | 68 | 110 | 2 390 |
| `rat2` | 20 | 1 | 94 | 146 | 1 458 |

With every rule off the search has no anchor, so it finds the assembly in each of the tray's four orientations: 4 × 16 + 1 = 65 of `new1`'s 109 nodes lie on the way to a solution.

**Without roofs** (footprint regime):

| Fixture | Pieces | Assemblies | Default | No closure | No cavity | No anchor | Every rule off | Lookahead: nodes | Lookahead: states |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `new5-flat` | 6 | 1 | 90 | 145 | 90 | 111 | 166 | 16 | 144 |
| `new3-flat` | 9 | 1 | 6 104 | 8 990 | 6 104 | 6 160 | 9 080 | 453 | 8 146 |
| `new4-flat` | 9 | 1 | 510 | 2 671 | 510 | 572 | 2 862 | 35 | 1 193 |
| `rev2-flat` | 9 | 1 | 45 | 47 | 45 | 70 | 72 | 12 | 167 |
| `rat1-flat` | 11 | 101 | 17 425 | 38 710 | 17 521 | 18 258 | 30 596 | 845 | 10 612 |
| `new1-flat` | 16 | 1 | 1 064 878 | 1 240 046 | 1 064 878 | > 2 969 019 | > 1 664 612 | > 106 448 | > 3 276 307 |
| `new2-flat` | 16 | 1 | 909 750 | 1 173 124 | 909 750 | > 3 465 641 | > 1 700 428 | 22 979 | 890 708 |
| `rat2-flat` | 20 | 2 | 128 230 | 299 929 | 128 230 | 144 996 | 337 245 | 2 131 | 41 851 |

"No closure", "no cavity" and "no anchor" are the default with that one rule off. The last two columns are the default with `lookahead` on: nodes visited, and states examined (nodes plus placements looked at one step ahead), which is the fairer comparison with the other columns.

Times for the default, on one quiet machine and indicative only: `new1-flat` 23 s to its solution and 31 s to the end; `new2-flat` 9 s and 20 s; `rat2-flat` 0.2 s and 4.4 s; everything else under half a second, and every relief search under 20 ms.

What the tables say:

- **The roofs are what make these puzzles easy.** Every relief puzzle has one assembly, and the search for it hardly backtracks, with or without the other rules: 146 nodes for 20 pieces with everything off. The same pieces without roofs take up to a million. A roof plane is three numbers per piece, and it removes nearly every wrong placement at the corner where it is tried. This is the wall matching a person does by eye.
- **The roofs also decide uniqueness.** `rat1` has 101 footprint assemblies and one relief assembly; `rat2` two and one. The other six are unique either way.
- **The number of pieces is a poor measure of difficulty.** The 20-piece `rat2-flat` takes an eighth of the nodes of the 16-piece `new1-flat`. The 9-piece `new3-flat` takes 130 times the nodes of the 9-piece `rev2-flat`.
- **Finding and finishing are different costs.** `rat2-flat` gives its first assembly after 5 555 nodes and needs 128 230 to show there are two; `new1-flat` spends three quarters of its search before the only one turns up. The first is hard to certify, the second hard to find.
- **Closure pruning is the rule that works on small footprints.** On `new5-flat`, `new3-flat`, `new4-flat`, `rat1-flat` and `rat2-flat` it removes a third to four fifths of the nodes, and without it the search is close to having no rules at all (`rev2-flat` is nearly free of backtracking either way). On the two 16-piece puzzles it removes only a seventh to a fifth of the nodes, though those it removes are the expensive ones: the searches took two to three times as long without it.
- **The anchor matters most where the search is deepest.** On the 16-piece footprints, searching all four orientations instead of one multiplies the work by about three or more; neither search finished in the time allowed. On small puzzles it saves little, and it can cost: removing the anchor's placements changes which corner has the fewest, and `rat1-flat` visits more nodes with the anchor and no closure rule (38 710) than with no rules (30 596).
- **Cavity pruning does almost nothing here.** It fires a few thousand times in a million nodes and never changes a node count by more than one percent. Corner filling rarely leaves an enclosed cavity whose area or width is wrong before a corner or a run is; the closure rule sees the trouble first.
- **Looking ahead trades nodes for work per node, and the trade goes both ways.** It always cuts nodes, by a factor of 3 to 60. Counted in states it wins on `rat1-flat`, `rat2-flat` (three times fewer) and narrowly `new2-flat`, and loses on the other five, by more than a factor of three on `new1-flat`. It is off by default because its worst case is the corpus's hardest instance.
- **What is left.** The two 16-piece footprints are hard for every configuration tried. Their searches die five or six pieces deep, in states no present rule recognises as dead when they are created. That is where learning from dead ends, or a rule that sees further, would have to show its worth.

These are eight constructions. They are enough to say what happens on this corpus and not enough to say why; the difficulty proxies of phase 7 are meant for that.
