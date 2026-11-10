# Algorithms for Geometric Tiling and Jigsaw-Like Assembly in Tropical Puzzle Lab

## Executive summary and repository assessment

The attached research brief asks for more than a solver: it asks for a rigorous bridge between geometric tiling theory, practical optimization software, tolerance-aware assembly, and the specific mathematical structure of MaxPlus Lab’s Tropical Puzzle Lab. The repository is unusually well positioned for such work because its puzzle data already separates authoritative construction recipes, generated geometry, player state, reference poses, validation tolerances, and tropical metadata. The generated `puzzle.json` format stores each piece as a **convex CCW polygon in millimeters**, plus either a planar roof \(z=z_0+g_xu+g_yv\) or a constant thickness; legal motions are continuous planar translations and continuous \(z\)-rotations, with no flipping. Reference poses are explicitly described as construction/reveal data rather than completion criteria. [[1]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md)

The current project is **not yet an automated solver project**. It already provides a browser player, seeded scrambles, arbitrary rotation/translation, overlap feedback, undo/redo, persistence, an optional solution outline, sticky-edge assistance, a relief-specific wall-match tool, tolerance-aware completion, STL export, and an experimental difficulty rating. Automated solving and systematic difficulty studies are still listed as planned work. [[2]](https://github.com/maxpluslab/tropical-puzzle-lab) The current difficulty heuristic is not search-based: it computes a similarity-sensitive Leinster–Cobbold diversity from scale-normalized intrinsic volumes of the piece solids, with lower diversity currently mapped to greater difficulty. The repository itself labels the rating experimental and unvalidated. [[3]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/generator/src/tropical_puzzle_lab/difficulty.py)

The strongest first solver architecture is therefore **not** a generic continuous nonlinear optimizer and **not** a rasterized polyomino solver. I recommend an **exact geometric backtracker over a lazily generated finite set of contact-induced rigid placements**, with relief constraints and geometry predicates applied incrementally. The key insight is that although each unplaced polygon has an infinite \(SE(2)\) pose space, intended tilings are supported by contacts: aligning an oriented straight edge of one convex piece with an already fixed edge of another piece or the tray determines the rotation and one component of translation, and endpoint/collinearity choices determine the remaining translation. This is the same broad idea by which no-fit-polygon methods replace unconstrained two-body motion with lower-dimensional configuration-space boundaries. NFP-based approaches are standard in irregular-polygon nesting. [[4]](https://www.frontiersin.org/journals/mechanical-engineering/articles/10.3389/fmech.2022.966691/full)

The principal recommendation is a three-stage research program. First, build a deterministic **footprint-exact contact backtracker** and use it as the transparent baseline. Second, add roof-aware compatibility, CP-SAT/exact-cover benchmark models over the same finite candidate set, and exhaustive solution counting for small instances. Third, add a **tolerance-aware discrete-continuous refinement layer**, where discrete adjacency hypotheses seed local optimization of \((x,y,\theta)\) under bounded gaps, overlaps, and roof mismatch. This staging keeps the science interpretable: any improvement can be attributed separately to geometry, relief information, tropical structure, propagation, or continuous tolerance. The repository’s own wall-match experiment already suggests that relief can alter branching dramatically: on `new2`, loosening the endpoint-height tolerance from ±0.25 mm to ±5 mm increases the mean number of candidate pieces per interior wall from about 1.03 to 7.5. [[5]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md)

## Problem taxonomy, formulations, and computational complexity

The central distinction is between **finite-placement discrete problems** and **continuous-pose geometric problems**. A polyomino tiling on a finite grid has a finite set of legal cells and orientations; every legal placement can be enumerated in advance and represented as a row of a 0–1 incidence matrix. An arbitrary-polygon puzzle with continuous rotation and translation instead begins with infinitely many poses. The algorithmic challenge is therefore often not the final combinatorial search but constructing a small, complete or nearly complete placement set. Tropical Puzzle Lab belongs to the latter class: pieces have continuous rotations and translations, although their convex polygonal structure and edge-to-edge origin make finite contact-generated candidate sets especially plausible. [[1]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md)

| Problem class | Typical variables | Core constraints | Search character | Representative methods |
|---|---|---|---|---|
| Polyomino/polyform tiling | Boolean \(x_{p,r,t}\) for piece-placement choices | each cell covered exactly once; each piece used once | finite, discrete | backtracking, exact cover/DLX, SAT, MILP |
| Exact/generalized exact cover | Boolean row selections | primary columns exactly once; optional/generalized columns at-most/other cardinalities | finite, discrete | Algorithm X/DLX, SAT, CP-SAT |
| Polygon packing/nesting | \(x_i,y_i,\theta_i\), sometimes binary disjunctions | containment, pairwise non-overlap | mixed continuous/discrete | NFP, MILP, nonlinear optimization, heuristics |
| Jigsaw reconstruction | pairwise adjacency, relative pose, sometimes image labels | compatible interfaces, globally consistent embedding | graph + geometry | compatibility graphs, branch-and-bound, relaxation, global optimization |
| Edge matching | cell/tile/orientation assignments | neighboring labels/colors compatible | finite, discrete | backtracking, SAT, exact cover/CP |
| Constraint-based geometric assembly | pose + contact variables | incidence, non-overlap, connectivity, kinematic consistency | hybrid | CP/SAT + geometry oracle |
| Imperfect-geometry assembly | pose variables + residual/slack variables | bounded/penalized gaps, overlap, mismatch | hybrid continuous/discrete | robust optimization, nonlinear refinement, heuristic search |

Several hardness results are directly relevant, but they must be attached to their assumptions. Exact cover is a canonical NP-complete combinatorial problem; Algorithm X/DLX is an exhaustive search procedure, not a polynomial-time escape from that hardness. Knuth specifically presents tiling examples as applications of DLX. [[6]](https://arxiv.org/abs/cs/0011047) Finite-region polyomino tiling remains NP-complete under strikingly restricted tile sets; Moore and Robson prove NP-completeness for variants using right trominoes and square tetrominoes, while later work establishes NP-completeness plus counting and “another solution” hardness for additional restricted tromino/bar formulations. [[7]](https://arxiv.org/abs/math/0003039) Demaine and Demaine show NP-completeness and polynomial transformations among particular formulations of jigsaw puzzles, edge-matching puzzles, and polyomino packing. These results justify expecting exponential worst cases, but they do **not** imply that every practical Tropical Puzzle Lab instance is hard or that its continuous formulation has exactly the same complexity classification. [[8]](https://erikdemaine.org/papers/Jigsaw_GC/)

The objective also matters. **Feasibility** asks for one valid assembly. **Optimization** might minimize total mismatch, maximum mismatch, overlap, or a manufacturing-error likelihood. **Counting** asks for all solutions, while **uniqueness certification** requires finding one solution and proving there is no inequivalent second one. The latter two can be substantially more expensive than finding one assembly: restricted tiling formulations are known to have #P-complete counting variants and hard “another-solution” variants. [[9]](https://dspace.jaist.ac.jp/dspace/handle/10119/15100?locale=en) For Tropical Puzzle Lab, solution equivalence must also quotient out irrelevant symmetries such as permutations of geometrically identical pieces and, when the tray permits it, global rotational symmetry.

A useful mathematical model for an exact finite-candidate solver is

\[
x_{ip}\in\{0,1\},
\]

where \(x_{ip}=1\) means piece \(i\) takes candidate pose \(p\). Piece-use constraints are

\[
\sum_{p\in P_i}x_{ip}=1.
\]

For any geometrically incompatible pair \((i,p),(j,q)\),

\[
x_{ip}+x_{jq}\le 1.
\]

Coverage may be expressed through exact-cover cells, boundary/contact constraints, or incremental geometric validation. This formulation translates naturally to SAT, MILP, or CP-SAT once the continuous pose domain has been reduced to \(P_i\). CP-SAT is integer-valued, can enumerate solutions, and returns explicit feasible/infeasible/optimal statuses, making it especially attractive as an independent benchmark rather than necessarily as the first production search engine. [[10]](https://developers.google.com/optimization/cp/cp_solver/)

## Solver families and how they apply

The eight main approaches differ less in expressive power than in **where they pay the combinatorial cost**. For Tropical Puzzle Lab, candidate generation and geometric propagation are likely to dominate solver design more than the choice between SAT, DLX, CP-SAT, and hand-written DFS.

| Method | Mechanism and miniature example | Geometry representation | Main advantage | Main limitation here |
|---|---|---|---|---|
| Backtracking + propagation | Choose the most constrained open boundary segment; try each compatible piece edge; reject overlaps immediately. With three remaining pieces having candidate counts \(2,7,4\), branch on the 2-candidate piece/contact first. | Native polygons and poses | easiest to make geometry-aware; excellent instrumentation | worst-case exponential; engineering quality matters |
| Algorithm X / DLX | Rows are placements; columns can mean “piece A used,” “piece B used,” and discrete coverage cells. Selecting a row removes every conflicting row. | Requires finite placements and usually discrete coverage/contact columns | extremely lean exact enumeration | continuous geometry must be discretized/generated first |
| SAT/SMT | Boolean \(X_{ip}\); clauses enforce exactly-one placement and pairwise exclusions. SMT can additionally represent arithmetic predicates. | finite candidates; SMT can retain arithmetic | strong propagation, proofs/unsat reasoning | nonlinear geometry/rotation encoding becomes awkward |
| MILP | \(x_{ip}\) binary; incompatibilities become \(x_{ip}+x_{jq}\le1\); minimize mismatch penalties | finite candidates or disjunctive continuous models | objectives and soft penalties are natural | exact polygon non-overlap with free rotation is cumbersome |
| CP / CP-SAT | placement-choice integer or Boolean variables; table/no-overlap-like exclusions; enumerate or optimize | finite candidates | excellent cardinality propagation and search infrastructure | integer-only CP-SAT means continuous refinement stays external |
| Edge-generated geometric search | Fix one piece; align a candidate edge to an exposed assembly edge; validate and recurse | exact/native polygons | attacks continuous-position explosion directly | completeness depends on contact-generation assumptions |
| Branch-and-bound/metaheuristics | rank partial assemblies by mismatch or unresolved boundary; prune lower bounds; GA/SA can search orderings | arbitrary | useful for large/noisy packing | weak for uniqueness proof unless wrapped in exact search |
| Hybrid discrete-continuous | choose adjacency graph/edge pairings discretely, then optimize pose residuals continuously | polygons + \((x,y,\theta)\) | best match to manufactured/noisy pieces | hardest architecture and hardest to certify |

Backtracking is the right conceptual baseline because every stronger formulation still embodies the same recurring actions: choose a decision, infer consequences, reject a contradiction, and undo. Knuth’s DLX optimizes exactly this reversible state-update pattern for sparse exact-cover matrices; its “smallest column” heuristic is the exact-cover analogue of minimum-remaining-values. [[6]](https://arxiv.org/abs/cs/0011047) A Tropical-specific DFS can generalize this idea: choose the exposed boundary edge or unplaced piece with the fewest currently legal mates, not simply the next piece in an arbitrary order.

For a toy edge example, suppose fixed edge \(e=[(0,0),(10,0)]\) must mate with a candidate piece edge \(f=[(2,1),(2,11)]\). Because flipping is forbidden, reverse the endpoint order of one boundary, rotate the direction vector of \(f\) onto \(-e\), then translate one corresponding endpoint. That rigid transform is a candidate pose; the solver then tests tray containment, non-overlap, contact extent, and any roof condition. No angular grid is required. This is the most important way to avoid the naive infinity of continuous positions.

DLX becomes attractive once these rigid transforms have been precomputed. A row can encode “piece \(i\), placement \(p\), covers these atomic regions/contact slots.” Knuth’s implementation achieves fast reversible updates by unlinking and relinking nodes rather than reconstructing domains on backtrack. [[6]](https://arxiv.org/abs/cs/0011047) For Tropical Puzzle Lab, however, defining a compact set of exact “coverage columns” is less natural than for a square lattice. A DLX benchmark is therefore most compelling if the target is first planar-subdivided into arrangement cells induced by candidate polygon boundaries, or if columns represent required contacts rather than Euclidean area.

SAT and CP-SAT are particularly good as **cross-checking solvers over precomputed placements**. A Boolean incompatibility graph is trivial to encode: one exactly-one constraint per physical piece, pairwise clauses for overlapping placements, and optional clauses or tables for required neighbor contacts. Z3 additionally supports richer arithmetic through SMT and is MIT-licensed; OR-Tools’ CP-SAT is Apache-2.0 and supports Python. [[11]](https://microsoft.github.io/z3guide/) The practical advantage is methodological: if a custom DFS and CP-SAT independently report the same number of solutions for small puzzles, confidence in the benchmark corpus rises sharply.

MILP is strongest when soft costs enter the model. For example,

\[
\min \sum_{(i,p),(j,q)} c_{ipjq} y_{ipjq}
\]

can penalize imperfect matched contacts while retaining piece-selection binaries. Recent irregular-packing research still develops continuous MIP formulations and geometry-specific valid cuts, demonstrating that MIP remains relevant for polygon nesting, although such models become substantially more involved than finite-placement formulations. [[12]](https://www.sciencedirect.com/science/article/pii/S0377221723006148)

Generic nesting heuristics should be treated primarily as **reference geometry engines**, not complete Tropical solvers. NFP methods compute relative forbidden/contact regions of two polygons and are mature in irregular packing; free rotation makes the problem more costly and is often handled by sampled angles or specialized heuristics. [[4]](https://www.frontiersin.org/journals/mechanical-engineering/articles/10.3389/fmech.2022.966691/full) Tropical puzzles differ from industrial nesting because the goal is exact tray reconstruction rather than density minimization, and contact identity plus roof continuity carry far more information than they do in generic cutting-stock problems.

## Tolerance, imperfect geometry, and why difficulty can be non-monotone

Tolerance should be modeled as **several separate parameters**, not a single epsilon. The repository already follows this principle: completion separately controls pairwise penetration depth, outside-tray depth, area error, edge angular alignment, minimum contact overlap, roof mismatch, and a lower “contact noise” scale. For `rev2`, the documented initial tolerances include about 0.86 mm penetration/outside depth, 249 mm² area error, and 1.75 mm roof mismatch; the documentation explicitly says these are first guesses rather than settled constants. [[5]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md) This is a strong starting point for solver research because it prevents a misleading equivalence between, for example, “0.5 mm edge-length disagreement” and “0.5 mm physical overlap.”

Five distinct uncertainty models should be kept separate:

\[
\begin{aligned}
&\text{edge compatibility:} && |\ell_i-\ell_j|\le \tau_\ell,\\
&\text{pose residual:} && \|\Delta t\|\le\tau_t,\quad |\Delta\theta|\le\tau_\theta,\\
&\text{roof residual:} && \max_{s\in e}|h_i(s)-h_j(s)|\le\tau_h,\\
&\text{manufacturing uncertainty:} && p_k\in B(\hat p_k,\Sigma_k)\ \text{or}\ \|p_k-\hat p_k\|\le r_k,\\
&\text{soft mismatch:} && \min \sum_e w_e \rho(r_e)\quad\text{or}\quad\min\max_e r_e .
\end{aligned}
\]

The last two distinguish “the true geometry lies somewhere inside an uncertainty set” from “we accept a visibly imperfect fit.” Archaeological reconstruction work makes the same conceptual distinction in practice: real fragments may have erosion, spurious boundaries, gaps, and imprecise transformations, so matching scores and confidence measures replace exact boundary equality. [[13]](https://www.sciencedirect.com/science/article/abs/pii/S0031320321002521) Recent polygonal-jigsaw work likewise studies convex polygon pieces contaminated with geometric noise and uses global constraints to prevent locally plausible matches from producing incoherent assemblies. [[14]](https://openaccess.thecvf.com/content/CVPR2021/html/Harel_Crossing_Cuts_Polygonal_Puzzles_Models_and_Solvers_CVPR_2021_paper.html)

The central complexity question has a genuinely two-sided answer. Raising a compatibility tolerance generally increases the degree of the edge-compatibility graph and therefore the branching factor of a contact search. Tropical Puzzle Lab already contains a clean empirical micro-example: in the 16-piece `new2` wall matcher, relaxing height tolerance from ±0.25 mm to ±5 mm increases mean candidate pieces per interior wall from 1.03 to 7.5 and reduces uniquely identified walls from 96% to 0%. [[5]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md) That is strong evidence for the **branching-expansion effect**.

But a wider tolerance also enlarges the feasible region. If the task is “find any feasible assembly,” more tolerance can rescue branches that would otherwise fail from tiny geometric residuals, potentially reducing backtracking. Conversely, if the task is “prove uniqueness” or “enumerate all accepted assemblies,” enlarged feasibility can make the task sharply harder because more alternatives survive. This predicts a plausible non-monotone runtime curve: very tight tolerance can make feasibility hard or impossible; intermediate tolerance can make the intended solution easy; high tolerance can create a combinatorial explosion of alternatives. This is a research hypothesis rather than an established theorem for Tropical Puzzle Lab and should be tested explicitly.

Continuous adjustment adds another effect. With strict edge coincidence, an edge match determines a rigid pose almost discretely. If ±translation and ±rotation slack are permitted, each discrete adjacency hypothesis becomes a **continuous feasible tube** in configuration space. Solving then becomes closer to constrained registration or nonlinear optimization. Harel and Ben-Shahar’s noisy polygon puzzle work is relevant precisely because geometrical noise breaks exact contact constructions and forces global correction mechanisms. [[14]](https://openaccess.thecvf.com/content/CVPR2021/html/Harel_Crossing_Cuts_Polygonal_Puzzles_Models_and_Solvers_CVPR_2021_paper.html)

Global consistency is essential because acceptable local residuals can accumulate around a cycle. If pieces \(A,B,C,D\) each have a small relative pose error, the composed transform around \(A\to B\to C\to D\to A\) may fail to close. A robust solver should therefore impose both local contact residual bounds and **cycle/embedding consistency** after every connected component grows beyond a tree. This can be implemented either by fixing absolute poses during search or by storing relative transforms and checking loop closure before expensive polygon operations.

Physical feasibility must remain a hard outer constraint even in a soft-mismatch model. A low sum of edge residuals must never compensate for substantial overlap, uncovered cavities, or leaving the tray. That design is consistent with the current player, which separately checks penetration, outside distance, coverage/error area, and relief continuity. [[5]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md) A sensible lexicographic objective is therefore: first satisfy non-overlap/containment/coverage within strict physical bounds; only then minimize edge and roof residuals.

Numerical robustness deserves its own implementation layer. Orientation tests, collinearity, segment intersection, and polygon Boolean operations can change combinatorially when floating-point values lie near zero. Shewchuk’s adaptive exact predicates are the classic solution for orientation/incircle tests, and CGAL offers kernels with exact predicates and exact constructions. [[15]](https://people.eecs.berkeley.edu/~jrs/papers/robust-predicates.pdf) For a Python prototype, Shapely is a pragmatic geometry engine with predicates and an STRtree spatial index, but correctness-critical certification should either use quantized/rational coordinates inherited from the exact generator or delegate final predicates to an exact backend. Shapely itself is BSD-3-Clause licensed and actively maintained. [[16]](https://shapely.readthedocs.io/en/stable/strtree.html)

A good tolerance sweep should include at least \(\tau=0\) or machine-exact construction geometry, a range near expected print/measurement error, the current browser-completion scale, and intentionally exaggerated levels. For each level record candidate graph degree, generated poses, DFS nodes, contradiction depth, solutions found, maximum residual, and closure error. To detect phase-transition behavior, use geometric spacing near apparent transitions rather than only a few hand-picked tolerances.

## Tropical-specific constraints and candidate generation

Tropical Puzzle Lab exposes substantially more structure than a generic jigsaw. A tropical polynomial in max convention is a maximum of affine functions, and its domains of linearity form a polyhedral subdivision; the repository turns those cells into pieces and uses the corresponding affine function as the relief roof. Rational puzzles use the common refinement of numerator and denominator subdivisions and a roof equal to the local affine difference. [[2]](https://github.com/maxpluslab/tropical-puzzle-lab) This means each piece carries both planar geometry and an analytically exact affine height model.

An oriented footprint edge should therefore have a cached signature such as

\[
\sigma(e)=
(\ell,\ \alpha_{\text{left}},\alpha_{\text{right}},\
h_0,h_1,\
g_x,g_y,\
\text{boundary-class},\
\text{tropical labels}),
\]

where \(\ell\) is length, the \(\alpha\)'s are endpoint corner angles, \(h_0,h_1\) are roof heights at ordered endpoints, and \(g=(g_x,g_y)\) is the roof gradient in piece-local coordinates. For candidate lookup, quantized bins or interval indices over \(\ell,h_0,h_1\) can reduce an \(O(E^2)\) edge scan to small buckets before exact checks.

There is an especially useful exact result for relief matching. Let two transformed roof planes restricted to a common straight segment be \(h_1(t)=a_1t+b_1\) and \(h_2(t)=a_2t+b_2\). Their difference \(d(t)\) is affine. Therefore:

\[
d(0)=d(1)=0 \quad\Longrightarrow\quad d(t)=0\ \forall t\in[0,1].
\]

Moreover,

\[
\max_{t\in[0,1]}|d(t)|
=\max(|d(0)|,|d(1)|).
\]

Thus **endpoint heights are sufficient to certify both exact continuity and a uniform absolute height-tolerance bound along a straight matched segment**, provided both roofs are affine over that segment. This rigorously justifies the project’s wall matcher comparing top-edge heights at both endpoints. [[5]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md)

A second rigorous invariant is more powerful than raw gradient equality. If two affine planes agree along a line with tangent \(v\),

\[
(g_1-g_2)\cdot v = 0.
\]

So the gradient jump must be **normal to the shared edge**. Requiring \(g_1=g_2\) would be wrong: a tropical ridge or valley is precisely a location where adjacent affine pieces can have different gradients while remaining continuous. The tangential-gradient equality, however, is a valid hard constraint and can be checked before polygon overlap. This is an example of tropical structure producing a stronger-than-generic but mathematically justified filter.

For exact candidate generation, use four sources:

1. **Tray-edge placements.** Match a piece edge to each compatible target boundary segment, generating transforms that place the piece inside the tray.
2. **Piece-edge placements.** Match an edge of an unplaced piece antiparallel to an exposed edge of the current assembly.
3. **Collinear-chain placements.** Allow one long edge to mate to a sequence of shorter collinear edges or vice versa; generate candidate offsets from endpoint coincidences and interval partitions.
4. **Vertex-contact rescue placements.** For pathological solutions lacking any full new edge match, derive transforms from two independent point/line incidences.

The first two should solve the intended generated families if their assemblies preserve the cell-complex adjacencies cleanly; the latter two protect completeness as the puzzle catalogue broadens.

Precompute an **edge compatibility graph** whose nodes are oriented piece edges and tray edges. An edge pair is admitted only if hard invariants pass: allowed orientation, compatible length/overlap structure, corner geometry where appropriate, and relief endpoint/tangential-gradient constraints for the relief-aware mode. Then generate rigid transforms lazily from graph arcs rather than precomputing every piece-pair pose.

For search ordering, use a geometric version of MRV: score each exposed assembly edge by the number of currently unused compatible edges that produce a legal pose after cheap tests. Branch on the minimum score. Propagate piece-use, compatibility, tray containment, and neighbor impossibilities immediately. Knuth’s smallest-column strategy provides the exact-cover analogue and the motivation for this ordering. [[6]](https://arxiv.org/abs/cs/0011047)

Convexity enables additional cheap pruning. The repository specifies convex piece polygons, so pairwise overlap can be rejected quickly with separating-axis tests before invoking general polygon Boolean operations. [[1]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md) Maintain a spatial index over placed-piece bounding boxes, test only nearby pieces, and cache transformed edge normals. Shapely’s STRtree is directly suitable for broad-phase indexing. [[16]](https://shapely.readthedocs.io/en/stable/strtree.html)

Area is a global invariant but is weak by itself. Stronger cavity checks should construct the uncovered region after each sufficiently large partial assembly and reject any connected component whose area cannot equal a subset sum of remaining piece areas within tolerance, whose width is below every remaining piece’s minimum width, or whose boundary signature admits no remaining contact. Exact subset-sum filtering may be expensive, so bitset/quantized-area approximations can provide a cheap necessary condition.

Tropical metadata should be used carefully. Piece identifiers and original term labels are potentially **solution leakage** if they encode generating relationships, so benchmark solvers should have modes that deliberately exclude them. By contrast, geometric roof quantities that are physically observable from the piece—endpoint heights, slopes, side-wall profiles—are legitimate “relief-aware” clues. A separate “tropical-structure-aware” solver may use term coefficients or balancing-style invariants, but its results must be reported separately from the physical-information baseline. This separation is essential to the benchmark requested in the brief.

## Existing software and reference implementations

The most useful software falls into two categories: **search/optimization engines** and **geometry engines**. No reviewed package is a drop-in Tropical Puzzle Lab solver; the adaptable architecture is to combine a geometry-specific candidate generator with one or more generic search engines.

| Project | Type | License / language | Geometry support | Matching | Maintenance / role | Tropical fit |
|---|---|---|---|---|---|---|
| OR-Tools CP-SAT | CP/SAT optimization library | Apache-2.0; C++ core, Python/Java/C# APIs | no native arbitrary-polygon tiling model required | exact finite-domain; integer soft costs | actively maintained | **Excellent benchmark backend** once placements exist. [[17]](https://github.com/google/or-tools) |
| Z3 | SMT/SAT theorem prover | MIT; C++ with Python etc. | arithmetic/logical formulas | exact symbolic/discrete; richer arithmetic than CP-SAT | actively maintained | **Excellent research/proof prototype**, especially for adjacency/pose relations. [[18]](https://github.com/z3prover/z3) |
| `tdons/dlx` | Algorithm X / DLX | MIT; C + Python bindings | none natively | exact cover | compact reference implementation | Good for validating finite-placement encodings. [[19]](https://github.com/tdons/dlx) |
| `jwg4/exact_cover` | Algorithm X / DLX | C core + Python helpers | none natively | exact cover | practical Python-facing library | Good secondary DLX benchmark. [[20]](https://github.com/jwg4/exact_cover) |
| libnest2d | polygon nesting | LGPL-3.0; modern C++ | irregular polygons, NFP-style nesting | geometric packing; approximate/search-oriented | established library | **Best reference for configuration-space/NFP engineering**, not a puzzle solver. [[21]](https://github.com/tamasmeszaros/libnest2d) |
| SVGnest | browser nesting | MIT; JavaScript | SVG polygons, NFP-based nesting | packing heuristic | historically influential | Useful conceptual/reference code; less aligned with exact proof. [[22]](https://github.com/Dexus/svgnest/blob/main/readme.md) |
| Shapely / GEOS | computational geometry | BSD-3-Clause; Python/C | polygon Boolean ops, predicates, STRtree | numeric geometry | active | **Best Python prototype geometry layer**. [[23]](https://github.com/shapely/shapely) |
| CGAL | exact computational geometry | GPL/LGPL + commercial; C++ | exact predicates/constructions, polygon Boolean ops | exact/robust | mature/active | **Best certification/backend option** if Python/GEOS robustness becomes limiting. [[24]](https://doc.cgal.org/Manual/4.1/doc_html/cgal_manual/Kernel_23_ref/Class_Exact_predicates_exact_constructions_kernel.html) |
| SCIP / PySCIPOpt | MILP/MINLP/constraint solver | Apache-2.0 from 8.0.3; C/C++ + Python interface | user-modeled | exact MIP / nonlinear capabilities depending model | active | Strong for soft objectives and comparison models. [[25]](https://scipopt.org/) |

Three implementations deserve study first. **Knuth/DLX** should be read to internalize reversible exact search and MRV-style column selection, even if it is not the eventual geometry engine. [[6]](https://arxiv.org/abs/cs/0011047) **OR-Tools CP-SAT** should be used as the first independent finite-candidate benchmark because its Python interface, solution enumeration, and permissive license make it easy to integrate. [[10]](https://developers.google.com/optimization/cp/cp_solver/) **libnest2d/SVGnest plus the NFP literature** should be studied for geometric candidate-generation techniques, because they explicitly transform polygon non-overlap into configuration-space computations rather than sampling arbitrary translations. [[21]](https://github.com/tamasmeszaros/libnest2d)

The recent jigsaw literature is more useful algorithmically than many hobby puzzle solvers. Harel and Ben-Shahar’s crossing-cuts polygonal puzzles target general convex polygons and analyze geometric noise; Derech, Tal, and Shimshoni tackle erosion and imprecise transformations; Illig et al. use shape invariants and global optimization for apictorial assembly. [[14]](https://openaccess.thecvf.com/content/CVPR2021/html/Harel_Crossing_Cuts_Polygonal_Puzzles_Models_and_Solvers_CVPR_2021_paper.html) These are much closer to the anticipated tolerance-aware Tropical work than image-grid jigsaw solvers whose primary signal is RGB continuity.

## Recommended custom architecture and pseudocode

The proposed Python package should separate **representation**, **candidate generation**, **geometry certification**, **constraint propagation**, **search**, and **experimentation**. That mirrors the existing repository’s clean split between exact recipe generation and browser gameplay, while avoiding any dependency on hidden reference poses. The generator itself already uses exact rational arithmetic for construction; solver import should preserve exact/quantized values where possible rather than round immediately to arbitrary floating point. [[2]](https://github.com/maxpluslab/tropical-puzzle-lab)

```text
solver/
    io.py                 # load sanitized puzzle.json
    normalize.py          # canonical local geometry, orientation, symmetry classes
    edges.py              # edge signatures and compatibility graph
    candidates.py         # rigid pose generation from contacts
    geometry.py           # containment, SAT overlap, Boolean coverage, spatial index
    relief.py             # endpoint heights, gradient/tangent constraints
    propagate.py          # piece/contact/domain propagation
    search.py             # DFS, MRV, value ordering, nogoods
    cp_model.py           # optional CP-SAT finite-candidate benchmark
    refine.py             # tolerance-aware continuous optimization
    validate.py           # independent final certificate
    metrics.py            # nodes, backtracks, timings, domain reductions
    benchmark.py          # reproducible corpus runner
```

Three designs should be maintained as explicit experimental variants.

**Exact geometric backtracking** keeps native polygons and generates a placement only when an exposed boundary needs to be filled. Its strengths are low memory, transparent pruning, continuous-angle support without discretization, and direct access to solver-difficulty metrics. Its weakness is that correctness/completeness rests on candidate-generation rules. This is the recommended **first implementation**.

**Finite-candidate exact-cover/CP-SAT** first exhausts contact-generated placements, computes a conflict graph, then solves the discrete selection problem. It is easier to enumerate all solutions and independently validate the custom DFS. Its weakness is possible candidate blow-up and the difficulty of representing exact continuous coverage compactly. CP-SAT’s all-solution enumeration is directly available. [[10]](https://developers.google.com/optimization/cp/cp_solver/)

**Hybrid discrete-continuous** searches an adjacency/contact hypothesis, then refines absolute poses to minimize residuals:

\[
\min_{\{x_i,y_i,\theta_i\}}
\lambda_h\sum_e r_h(e)^2+
\lambda_g\sum_e r_{\text{gap}}(e)^2+
\lambda_\theta\sum_e r_\theta(e)^2
\]

subject to hard or barrier constraints for overlap and tray containment. This is the correct long-term architecture for scans or manufactured pieces, but it should come only after the zero-tolerance solver establishes a clean baseline.

The main exact search can be written as:

```text
SOLVE(state):
    propagate(state)
    if contradiction(state):
        return

    if all pieces placed:
        if independent_validate(state):
            emit canonicalized_solution(state)
        return

    frontier = exposed_contacts(state)

    c = argmin(frontier,
               number_of_legal_candidate_placements(c, state))

    candidates = generate_candidates(c)
    candidates = filter_unused_piece(candidates, state)
    candidates = filter_edge_invariants(candidates)
    candidates = order_by(
        boundary_support_desc,
        new_constraints_desc,
        ambiguity_asc
    )

    for pose in candidates:
        if not cheap_inside_test(pose): continue
        if spatial_index_overlap(pose): continue
        if relief_mode and not roof_contacts_ok(pose): continue
        if creates_impossible_cavity(pose): continue

        push(state, pose)
        update_spatial_index(state)
        update_contact_domains(state)

        SOLVE(state)

        undo(state)
```

Several implementation details matter disproportionately. First, fix one anchor symmetry whenever possible: a corner or boundary piece may be placed in a canonical tray position so globally equivalent branches are not rediscovered. Second, canonicalize geometrically indistinguishable pieces into symmetry classes and impose an ordering constraint. Third, memoize partial states using a canonical contact graph plus quantized poses rather than insertion order. Fourth, learn simple **nogoods**: if a set of \(k\) contact assignments inevitably creates overlap or an impossible cavity, cache that subset.

For geometry, start with Shapely for polygon Boolean operations and STRtree broad-phase filtering, while retaining custom convex SAT tests in the hot path. [[16]](https://shapely.readthedocs.io/en/stable/strtree.html) If numerical edge cases become scientifically significant, add a small compiled extension using CGAL exact predicates/constructions rather than attempting to “fix” them with ever larger epsilons. [[24]](https://doc.cgal.org/Manual/4.1/doc_html/cgal_manual/Kernel_23_ref/Class_Exact_predicates_exact_constructions_kernel.html)

A particularly important validation rule is architectural independence: the final `validate.py` should not share all the same approximations as `search.py`. A solver solution should be reconstructed from poses, checked for pairwise intersections, tray difference area, uncovered area, and relief continuity using a separate code path. This prevents a bug in a pruning predicate from also becoming the definition of correctness.

## Benchmark design, difficulty experiments, and roadmap

The benchmark corpus should be generated from Tropical Puzzle Lab recipes but exported through a **sanitizer** that strips `reference.poses`, generating positions, and any identifiers or tropical labels that could reveal placement. The public puzzle format explicitly contains reference poses and tropical construction metadata, so using the unmodified JSON would compromise a benchmark intended to measure geometric inference. [[1]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md) The sanitized instance should retain only what the chosen experimental condition permits: piece polygons, tray polygon, physical roof planes/thicknesses, and validation parameters.

Run three information regimes on the **same footprint instances**. The footprint-only solver receives polygons and tray geometry. The relief-aware solver additionally receives roof planes/heights that would be observable in the physical relief puzzle. The tropical-aware solver may additionally access construction-level metadata and mathematically derived invariants; it should never be merged into the relief baseline because that would confound physically available clues with privileged generative information.

The principal metrics should be runtime, CPU time, search nodes, candidate placements generated, domain deletions from propagation, backtracks, maximum recursion depth, peak memory, number of solutions, time to first solution, time to prove uniqueness, overlap/outside/coverage residuals, and maximum roof mismatch. For a search-based difficulty measure, **nodes under a fixed solver configuration** is more reproducible than wall-clock time; nevertheless both should be recorded. Search-node counts remain algorithm-dependent, so the corpus should be run under several fixed heuristic policies to estimate how much “difficulty” is intrinsic versus induced by one variable-ordering rule.

A useful decomposition is

\[
\text{instance difficulty}
\approx
\text{candidate ambiguity}
+
\text{global-consistency depth}
+
\text{symmetry}
+
\text{geometric-test cost},
\]

with measurable proxies: average/maximum compatible-edge degree; fraction of edges with unique mates; median contradiction depth; automorphism/symmetry counts; and average overlap/cavity checks per node. This directly tests the open questions already recorded in the repository about plausible placements, branching, backtracking, near-symmetry, boundary clues, and roof continuity. [[26]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/research-notes.md)

Tolerance experiments should form a two-dimensional grid rather than one scalar sweep. One axis should vary geometric pose/penetration tolerance; another should vary relief-height tolerance. For each pair, record: feasibility, number of distinct accepted solutions, time to first solution, time to uniqueness proof, edge-graph density, and residual distributions. This can reveal whether relief clues shift or eliminate the branching transition caused by looser footprint tolerances.

Human-comparison experiments should use the browser’s existing seeded scrambles and report instrumentation. The current player records elapsed active time and use of solution reveal, sticky edges, and wall match; this supports controlled comparisons among unassisted flat, unassisted relief, and assisted conditions. [[1]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md) Human time should not be interpreted as direct computational complexity: perceptual shape recognition, parallel visual processing, motor cost, and spatial memory have no simple analogue in DFS node counts. The scientifically useful question is instead whether solver-derived variables—candidate ambiguity, contradiction depth, symmetry, relief discriminability—predict human time after controlling for piece count.

A phased roadmap is:

| Phase | Main deliverable | Approximate research/development effort |
|---|---|---:|
| Geometry baseline | sanitized importer, edge signatures, exact contact generator, overlap/containment tests | 5–8 working days |
| Exact DFS | MRV search, symmetry breaking, solution enumeration, instrumentation | 5–8 days |
| Relief solver | endpoint-height and tangent-gradient pruning; wall-profile compatibility | 3–5 days |
| Independent benchmark | CP-SAT finite-candidate encoding + cross-validation | 4–7 days |
| Benchmark corpus | automated instance generation/sanitization, reproducible runs | 4–6 days |
| Tolerance study | parameter sweeps, hybrid pose refinement, ambiguity analysis | 7–12 days |
| Difficulty study | heuristic ablations, human-vs-algorithm analysis, report tooling | 7–15 days |

The highest-value scientific experiment is not simply “which solver is fastest?” It is the factorial comparison **flat vs. relief × tolerance × search heuristic × puzzle family**, with uniqueness and ambiguity measured explicitly. That experiment can establish whether relief changes only constant factors or qualitatively changes search structure; whether the current intrinsic-volume diversity metric predicts actual search effort; and whether tolerance creates a branching/feasibility phase transition.

## Research conclusions, open questions, and source guide

Several conclusions are already well supported. First, the project’s geometry is favorable for a specialized solver: pieces are convex polygons, roofs are affine planes, and the target is a known convex polygon. [[1]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md) Second, edge-contact generation is the natural bridge from continuous pose space to discrete combinatorial search, consistent with broader configuration-space/NFP approaches in irregular packing. [[4]](https://www.frontiersin.org/journals/mechanical-engineering/articles/10.3389/fmech.2022.966691/full) Third, relief information can be converted into exact local invariants rather than treated as a vague 3D similarity score; endpoint heights and tangential gradient continuity are especially strong. Fourth, the existing difficulty metric measures **shape diversity**, not solver effort or human difficulty, so it should be treated as one explanatory covariate rather than a ground truth. [[3]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/generator/src/tropical_puzzle_lab/difficulty.py)

The most promising near-term contribution is a rigorous characterization of **when contact-induced finite placement generation is complete** for these tropical cell decompositions. If every nontrivial partial tiling can be grown by attaching a remaining convex cell along a full or decomposable collinear boundary segment, then the apparently continuous problem collapses to an exact finite search without angular discretization. That statement should be proved for the specific family of subdivisions produced by the generator rather than assumed from examples.

A second promising mathematical question is whether tropical structure yields valid pruning beyond ordinary roof continuity. The gradient-jump-normal condition is immediate and rigorous. More ambitious ideas—balancing conditions, allowable cyclic gradient sequences, reconstruction of local Newton-subdivision structure—could potentially prune assemblies that are geometrically and height-continuous but globally impossible as the specified tropical function class. Such constraints should be labeled experimental until proved; ordinary continuity does not by itself imply that an arbitrary assembled piecewise-linear surface comes from the intended tropical polynomial or rational-function construction. Tropical polynomials are maxima/minima of affine functions and induce polyhedral complexes, which gives the correct mathematical setting for pursuing these questions. [[27]](https://link.springer.com/article/10.1007/s13348-022-00354-9)

A third contribution is likely to be empirical: **tolerance-dependent ambiguity**. The repository already provides a concrete local signal that candidate multiplicity can change by an order of magnitude as relief tolerance widens. [[5]](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md) A full solver can determine whether this produces a global phase transition, whether time-to-first-solution and time-to-uniqueness move in opposite directions, and whether the effect differs between flat and relief puzzles. I did not find a direct theorem or established empirical literature answering this exact question for continuous polygonal tilings with affine relief profiles; the closest literature concerns noisy polygonal jigsaw reconstruction and toleranced geometric matching. [[14]](https://openaccess.thecvf.com/content/CVPR2021/html/Harel_Crossing_Cuts_Polygonal_Puzzles_Models_and_Solvers_CVPR_2021_paper.html) This appears to be a credible research gap rather than something that should be presented as established novelty.

The practical source set to retain alongside the implementation is compact: Knuth’s *Dancing Links* for exact search and reversible propagation; Demaine & Demaine for complexity relationships among jigsaw, edge matching, and polyomino packing; Moore & Robson for restricted tiling hardness; the 2021–2024 polygonal-jigsaw literature for noisy geometric assembly; current OR-Tools and Z3 documentation for discrete benchmark engines; the irregular-packing/NFP literature and libnest2d for configuration-space placement; Shewchuk and CGAL for robust computational geometry; and the Tropical Puzzle Lab repository itself as the authoritative source for actual data representation, tolerances, controls, and present/planned functionality. [[6]](https://arxiv.org/abs/cs/0011047)

The prioritized implementation decision is therefore: **build the native geometry-aware backtracker first, make contact generation the central abstraction, add relief constraints as a plug-in information layer, and use CP-SAT/DLX as independent finite-candidate benchmarks rather than forcing the geometry into those formalisms prematurely**. After that baseline is trustworthy, tolerance-aware continuous refinement becomes a scientifically meaningful extension instead of a source of ambiguity about whether failures come from geometry, search, numerical error, or optimization.

## References

1. [Tropical Puzzle Lab, `docs/puzzle-format.md`](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-format.md)
2. [Tropical Puzzle Lab repository](https://github.com/maxpluslab/tropical-puzzle-lab)
3. [Tropical Puzzle Lab, `generator/src/tropical_puzzle_lab/difficulty.py`](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/generator/src/tropical_puzzle_lab/difficulty.py)
4. [Two-dimensional irregular packing problems: A review](https://www.frontiersin.org/journals/mechanical-engineering/articles/10.3389/fmech.2022.966691/full)
5. [Tropical Puzzle Lab, `docs/puzzle-rules.md`](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/puzzle-rules.md)
6. [Dancing links](https://arxiv.org/abs/cs/0011047)
7. [Hard Tiling Problems with Simple Tiles](https://arxiv.org/abs/math/0003039)
8. [Erik D. Demaine and Martin L. Demaine: Jigsaw Puzzles, Edge Matching, and Polyomino Packing: Connections and Complexity](https://erikdemaine.org/papers/Jigsaw_GC/)
9. [Complexity of Tiling a Polygon with Trominoes or Bars (JAIST Repository)](https://dspace.jaist.ac.jp/dspace/handle/10119/15100?locale=en)
10. [CP-SAT Solver, OR-Tools, Google for Developers](https://developers.google.com/optimization/cp/cp_solver/)
11. [Online Z3 Guide](https://microsoft.github.io/z3guide/)
12. [Mixed-integer programming models for irregular strip packing based on vertical slices and feasibility cuts](https://www.sciencedirect.com/science/article/pii/S0377221723006148)
13. [Solving archaeological puzzles](https://www.sciencedirect.com/science/article/abs/pii/S0031320321002521)
14. [Crossing Cuts Polygonal Puzzles: Models and Solvers](https://openaccess.thecvf.com/content/CVPR2021/html/Harel_Crossing_Cuts_Polygonal_Puzzles_Models_and_Solvers_CVPR_2021_paper.html)
15. [Robust Adaptive Floating-Point Geometric Predicates](https://people.eecs.berkeley.edu/~jrs/papers/robust-predicates.pdf)
16. [STRtree, Shapely 2.1.2 documentation](https://shapely.readthedocs.io/en/stable/strtree.html)
17. [google/or-tools: Google's Operations Research tools](https://github.com/google/or-tools)
18. [Z3Prover/z3: The Z3 Theorem Prover](https://github.com/z3prover/z3)
19. [tdons/dlx: An efficient backtracking algorithm that solves instances of the Exact Cover problem](https://github.com/tdons/dlx)
20. [jwg4/exact_cover: Python package to solve exact cover problems](https://github.com/jwg4/exact_cover)
21. [tamasmeszaros/libnest2d: 2D irregular bin packaging and nesting library written in modern C++](https://github.com/tamasmeszaros/libnest2d)
22. [Dexus/svgnest, `readme.md`](https://github.com/Dexus/svgnest/blob/main/readme.md)
23. [shapely/shapely: Manipulation and analysis of geometric objects](https://github.com/shapely/shapely)
24. [CGAL manual, `Exact_predicates_exact_constructions_kernel`](https://doc.cgal.org/Manual/4.1/doc_html/cgal_manual/Kernel_23_ref/Class_Exact_predicates_exact_constructions_kernel.html)
25. [SCIP](https://scipopt.org/)
26. [Tropical Puzzle Lab, `docs/research-notes.md`](https://github.com/maxpluslab/tropical-puzzle-lab/blob/main/docs/research-notes.md)
27. [Point line geometry in the tropical plane](https://link.springer.com/article/10.1007/s13348-022-00354-9)
