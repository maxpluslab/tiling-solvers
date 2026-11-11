//! Depth-first search over corner contacts.
//!
//! The rule is the one `tiling_geometry::assembly` argues for: at every node,
//! look at the convex corners of the uncovered region, take the one with the
//! fewest placements that fill it, and try each of those. Nothing else is
//! branched on.
//!
//! On top of the rule this search has what its Python prototype lacks.
//!
//! **Roofs.** When the pieces have roofs, a placement must also continue its
//! neighbours' roofs. That test is part of candidate generation
//! ([`Assembly::propose`]) and so it shapes the choice of corner as well.
//!
//! **Cavity pruning.** The uncovered region falls into cavities. The pieces
//! that end up in a cavity have exactly its area, and none is wider than a
//! convex cavity is. A state is a dead end when some cavity's area is not the
//! sum of the areas of any set of remaining pieces that could go into it, or
//! when some remaining piece could go into no cavity.
//!
//! **Closure pruning.** Take a straight run of the uncovered region's boundary
//! between two convex corners. Neither end lets a piece reach past it, so the
//! pieces that lie along the run each have one whole edge on it, and those
//! edges make up its length exactly. Likewise the pieces that meet in a convex
//! corner each have a vertex there, and their angles make up the corner's. A
//! state is a dead end when a run's length is not a sum of edge lengths of
//! different remaining pieces, or a convex corner's angle not a sum of their
//! angles.
//!
//! **Looking ahead.** Off by default. A placement counts towards a corner only if the state it
//! leads to is not a dead end by the two rules above. The corner branched on
//! is then the one with the fewest placements that survive, which is often one
//! and often none.
//!
//! **The tray's rotations.** A tray that can be turned onto itself gives every
//! assembly once per turn. With [`TrayRotations::Once`] one piece, the
//! *anchor*, is only ever put down with its centroid in one sector of the tray:
//! `[0, 2π/k]` as seen from the tray's centre, for a tray with `k` rotations.
//! Every assembly has a turn that brings the anchor there, so one of each
//! family survives. An anchor whose centroid is on a sector boundary or at the
//! centre survives more than once; those repeats are removed by comparing
//! canonical forms. The anchor is the largest piece that is congruent to no
//! other, so that "the anchor" names one place in an assembly. If there is no
//! such piece, nothing is pruned and the comparison does all of the work.
//!
//! All of this is `f64` with tolerances. The pruning rules are sound for exact
//! assemblies of convex pieces; that they change nothing is tested, here on
//! random tilings and from Python on the corpus.

use std::cell::RefCell;
use std::collections::HashMap;
use std::f64::consts::TAU;
use std::time::{Duration, Instant};

use tiling_core::{Pose, Vec2};
use tiling_geometry::{
    Assembly, AssemblyError, CandidatePlacement, CandidateStats, Cavity, ContactTolerance, Corner,
    Shape, centroid, least_width, signed_area, transform,
};

use crate::canonical::Symmetry;

/// What to do about assemblies that are turns of one another.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrayRotations {
    /// Return one assembly of each family, in canonical form.
    Once,
    /// Return every assembly as it is found.
    All,
}

/// How to run the search. Only `max_solutions`, the limits and
/// `tray_rotations` change what is returned; the rest change the work.
#[derive(Debug, Clone, PartialEq)]
pub struct Options {
    /// Stop after this many solutions; `None` runs the search to its end.
    pub max_solutions: Option<usize>,
    /// Checked at every node.
    pub time_limit: Option<Duration>,
    pub node_limit: Option<u64>,
    pub tray_rotations: TrayRotations,
    /// Hold the anchor piece to one sector of the tray. Only with [`TrayRotations::Once`].
    pub anchor: bool,
    /// Give up states with a cavity that cannot be filled.
    pub cavity_pruning: bool,
    /// Give up states with a run or a corner that the remaining pieces cannot close.
    pub closure_pruning: bool,
    /// Count a placement towards a corner only if the state it leads to is not
    /// a dead end by the pruning rules that are on. Off by default: it visits
    /// fewer nodes but, on most of the corpus, examines more states to do so.
    pub lookahead: bool,
    pub order: Order,
    /// For [`Order::Random`].
    pub seed: u64,
}

/// The order in which the candidates of a node are tried. It decides how soon
/// the first solution turns up, and nothing about what a whole search finds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Order {
    /// As [`Assembly::propose`] lists them: by piece, then by vertex.
    Generated,
    /// Placements that share more whole edges with placed pieces first. In a
    /// puzzle cut from a subdivision, neighbours share whole edges.
    MatchedEdges,
    /// A random order drawn from the seed.
    Random,
}

impl Default for Options {
    fn default() -> Options {
        Options {
            max_solutions: Some(1),
            time_limit: None,
            node_limit: None,
            tray_rotations: TrayRotations::Once,
            anchor: true,
            cavity_pruning: true,
            closure_pruning: true,
            lookahead: false,
            order: Order::MatchedEdges,
            seed: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Stats {
    /// Nodes expanded, the root included.
    pub nodes: u64,
    /// Nodes abandoned: no candidate for the corner, a dead end by a pruning
    /// rule, or every piece down with something left uncovered.
    pub backtracks: u64,
    /// Pieces put down as a branch of the search, counting every attempt.
    /// Placements tried while looking ahead are not counted.
    pub placements: u64,
    /// The largest number of pieces down at once.
    pub max_depth: u64,
    pub candidates: CandidateStats,
    /// Nodes abandoned because of a cavity. Counted in `backtracks` too.
    pub pruned_cavity: u64,
    /// Nodes abandoned because of a run or a corner. Counted in `backtracks` too.
    pub pruned_closure: u64,
    /// Candidates dropped for putting the anchor outside its sector.
    pub pruned_anchor: u64,
    /// Candidates dropped by looking one placement ahead.
    pub pruned_lookahead: u64,
    /// Assemblies found that were a turn of one already found.
    pub duplicates: u64,
    /// States whose corners did not link up into cavities, and so were not pruned.
    pub cavities_unknown: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Outcome {
    /// One pose per piece, in piece order.
    pub solutions: Vec<Vec<Pose>>,
    /// The search ran to its end: `solutions` is all it can find.
    pub exhausted: bool,
    pub stats: Stats,
    pub elapsed: Duration,
    pub first_solution: Option<Duration>,
    /// How many rotations map the tray onto itself.
    pub tray_order: usize,
    /// The piece held to one sector, if any was.
    pub anchor: Option<usize>,
}

/// Steps a question about areas may take before it is answered "perhaps".
const AREA_BUDGET: u32 = 20_000;
/// The same for the questions asked of every run and corner of every state.
const CLOSURE_BUDGET: u32 = 2_000;

/// Whether some of `areas[from..]`, largest first, add up to `need`. `rest[i]`
/// is the sum of `areas[i..]`. Running out of budget answers yes, which is the
/// answer that prunes nothing.
fn adds_up(
    areas: &[f64],
    rest: &[f64],
    from: usize,
    need: f64,
    tolerance: f64,
    budget: &mut u32,
) -> bool {
    if need.abs() <= tolerance {
        return true;
    }
    if from == areas.len() || rest[from] < need - tolerance {
        return false;
    }
    if *budget == 0 {
        return true;
    }
    *budget -= 1;
    (areas[from] <= need + tolerance
        && adds_up(areas, rest, from + 1, need - areas[from], tolerance, budget))
        || adds_up(areas, rest, from + 1, need, tolerance, budget)
}

/// The answer to "can these pieces supply this sum?".
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Supply {
    /// Yes, and these pieces do it.
    Yes(u64),
    No,
    /// The budget ran out. Treated as yes, which prunes nothing.
    Perhaps,
}

/// What is known about one sum, from the questions already asked about it.
#[derive(Default)]
struct Known {
    /// Sets of pieces that supply it.
    supplied_by: Vec<u64>,
    /// Sets of pieces that cannot.
    not_from: Vec<u64>,
    /// Sets of pieces for which the budget ran out.
    undecided: Vec<u64>,
}

/// Answers kept per sum, and sums kept in all, before the oldest are dropped.
const KNOWN_PER_SUM: usize = 8;
const KNOWN_SUMS: usize = 1 << 20;

/// One kind of number every piece has several of: its edge lengths, or its angles.
///
/// The same corners and runs are met again and again as a search moves through
/// neighbouring states, with one piece more or less to draw on. So answers are
/// remembered by the sum asked for: a set of pieces that supplied it still
/// does while they are all free, and a set that could not supply it still
/// cannot when pieces are taken away. Sets of pieces are bit masks, which is
/// why the memory is only used for up to 64 pieces.
struct Values {
    /// The distinct values of each piece.
    each: Vec<Vec<f64>>,
    least: Vec<f64>,
    most: Vec<f64>,
    known: RefCell<HashMap<u64, Known>>,
}

fn remember(list: &mut Vec<u64>, set: u64) {
    if list.len() == KNOWN_PER_SUM {
        list.remove(0);
    }
    list.push(set);
}

impl Values {
    fn new(all: impl Iterator<Item = Vec<f64>>, tolerance: f64) -> Values {
        // A rectangle has two lengths and one angle.
        let each: Vec<Vec<f64>> = all
            .map(|values| {
                let mut kept: Vec<f64> = Vec::new();
                for value in values {
                    if !kept.iter().any(|k| (k - value).abs() <= tolerance) {
                        kept.push(value);
                    }
                }
                kept
            })
            .collect();
        let fold = |start: f64, pick: fn(f64, f64) -> f64| -> Vec<f64> {
            each.iter()
                .map(|v| v.iter().copied().fold(start, pick))
                .collect()
        };
        Values {
            least: fold(f64::INFINITY, f64::min),
            most: fold(0.0, f64::max),
            each,
            known: RefCell::new(HashMap::new()),
        }
    }

    /// Whether taking at most one value from each of the pieces `free[from..]`
    /// can add up to `need`. `bounds[i]` holds the smallest value among those
    /// pieces and the sum of their largest.
    fn one_from_each(
        &self,
        free: &[usize],
        bounds: &[(f64, f64)],
        from: usize,
        need: f64,
        tolerance: f64,
        budget: &mut u32,
    ) -> Supply {
        if need.abs() <= tolerance {
            return Supply::Yes(0);
        }
        if from == free.len() {
            return Supply::No;
        }
        let (least, most) = bounds[from];
        if most < need - tolerance || least > need + tolerance {
            return Supply::No;
        }
        if *budget == 0 {
            return Supply::Perhaps;
        }
        *budget -= 1;
        let piece = free[from];
        for &value in &self.each[piece] {
            if value > need + tolerance {
                continue;
            }
            match self.one_from_each(free, bounds, from + 1, need - value, tolerance, budget) {
                Supply::Yes(set) => return Supply::Yes(set | 1 << (piece % 64)),
                Supply::Perhaps => return Supply::Perhaps,
                Supply::No => {}
            }
        }
        self.one_from_each(free, bounds, from + 1, need, tolerance, budget)
    }

    /// Whether `need` is a sum of one value each from some of the pieces
    /// `free`. An undecided question counts as yes.
    fn supply(&self, free: &[usize], need: f64, tolerance: f64) -> bool {
        if need.abs() <= tolerance {
            return true;
        }
        let remembering = self.each.len() <= 64;
        let set = free.iter().fold(0u64, |set, &p| set | 1 << (p % 64));
        let key = need.to_bits();
        if remembering {
            if let Some(known) = self.known.borrow().get(&key) {
                if known.supplied_by.iter().any(|&s| s & !set == 0)
                    || known.undecided.contains(&set)
                {
                    return true;
                }
                if known.not_from.iter().any(|&s| set & !s == 0) {
                    return false;
                }
            }
        }
        let mut bounds = vec![(f64::INFINITY, 0.0); free.len() + 1];
        for i in (0..free.len()).rev() {
            let (least, most) = bounds[i + 1];
            bounds[i] = (least.min(self.least[free[i]]), most + self.most[free[i]]);
        }
        let mut budget = CLOSURE_BUDGET;
        let answer = self.one_from_each(free, &bounds, 0, need, tolerance, &mut budget);
        if remembering {
            let mut known = self.known.borrow_mut();
            if known.len() >= KNOWN_SUMS {
                known.clear();
            }
            let entry = known.entry(key).or_default();
            match answer {
                Supply::Yes(by) => remember(&mut entry.supplied_by, by),
                Supply::No => remember(&mut entry.not_from, set),
                Supply::Perhaps => remember(&mut entry.undecided, set),
            }
        }
        answer != Supply::No
    }
}

/// SplitMix64: a small generator with a guaranteed stream, so that a seed means
/// the same search everywhere.
struct Random(u64);

impl Random {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn shuffle<T>(&mut self, items: &mut [T]) {
        for i in (1..items.len()).rev() {
            let j = (self.next() % (i as u64 + 1)) as usize;
            items.swap(i, j);
        }
    }
}

enum DeadEnd {
    Cavity,
    Closure,
}

fn distance(a: Vec2, b: Vec2) -> f64 {
    (b[0] - a[0]).hypot(b[1] - a[1])
}

struct Search<'a> {
    assembly: Assembly,
    options: &'a Options,
    symmetry: Symmetry,
    anchor: Option<usize>,
    centroids: Vec<Vec2>,
    areas: Vec<f64>,
    widths: Vec<f64>,
    lengths: Values,
    angles: Values,
    area_tolerance: f64,
    /// Slack for a sum of up to one length, or one angle, from every piece.
    length_slack: f64,
    angle_slack: f64,
    stats: Stats,
    solutions: Vec<Vec<Pose>>,
    started: Instant,
    first_solution: Option<Duration>,
    stopped: bool,
    random: Random,
}

impl Search<'_> {
    fn pruning(&self) -> bool {
        self.options.cavity_pruning || self.options.closure_pruning
    }

    /// The pieces not yet placed, leaving out `except`.
    fn free(&self, except: Option<usize>) -> Vec<usize> {
        (0..self.areas.len())
            .filter(|&p| Some(p) != except && self.assembly.pose(p).is_none())
            .collect()
    }

    /// Whether the anchor, placed so, has its centroid in the sector it is held to.
    fn in_sector(&self, candidate: &CandidatePlacement) -> bool {
        let tolerance = self.assembly.tolerance();
        let centre = self.symmetry.centre();
        let [x, y] = candidate.pose.apply(self.centroids[candidate.piece]);
        let (dx, dy) = (x - centre[0], y - centre[1]);
        let radius = dx.hypot(dy);
        if radius <= tolerance.length {
            return true;
        }
        let bearing = dy.atan2(dx).rem_euclid(TAU);
        let slack = tolerance.length / radius + tolerance.angle;
        bearing <= TAU / self.symmetry.tray_order() as f64 + slack || bearing >= TAU - slack
    }

    /// The cavities of the state as it stands, if pruning wants them and they can be traced.
    fn cavities(&mut self, corners: &[Corner]) -> Option<Vec<Cavity>> {
        if !self.pruning() {
            return None;
        }
        let cavities = self.assembly.cavities(corners);
        if cavities.is_none() {
            self.stats.cavities_unknown += 1;
        }
        cavities
    }

    /// Why the state as it stands cannot be completed, if the pruning rules can tell.
    fn dead_end(&self, corners: &[Corner], cavities: &[Cavity]) -> Option<DeadEnd> {
        let free = self.free(None);
        if self.options.cavity_pruning && !self.cavities_can_be_filled(&free, cavities) {
            Some(DeadEnd::Cavity)
        } else if self.options.closure_pruning
            && !self.closures_can_be_met(&free, corners, cavities)
        {
            Some(DeadEnd::Closure)
        } else {
            None
        }
    }

    /// Whether every cavity can still be filled, as far as areas and widths can tell.
    fn cavities_can_be_filled(&self, free: &[usize], cavities: &[Cavity]) -> bool {
        let length = self.assembly.tolerance().length;
        let mut largest_first = free.to_vec();
        largest_first.sort_by(|&a, &b| self.areas[b].total_cmp(&self.areas[a]));
        let mut has_a_place = vec![false; largest_first.len()];
        for cavity in cavities {
            let mut areas = Vec::with_capacity(largest_first.len());
            for (slot, &piece) in largest_first.iter().enumerate() {
                let fits = self.areas[piece] <= cavity.area + self.area_tolerance
                    && cavity
                        .width
                        .is_none_or(|width| self.widths[piece] <= width + length);
                if fits {
                    has_a_place[slot] = true;
                    areas.push(self.areas[piece]);
                }
            }
            let mut rest = vec![0.0; areas.len() + 1];
            for i in (0..areas.len()).rev() {
                rest[i] = rest[i + 1] + areas[i];
            }
            let mut budget = AREA_BUDGET;
            if !adds_up(
                &areas,
                &rest,
                0,
                cavity.area,
                self.area_tolerance,
                &mut budget,
            ) {
                return false;
            }
        }
        has_a_place.iter().all(|&placed| placed)
    }

    /// Whether every straight run between two convex corners, and every convex
    /// corner, can still be closed by the remaining pieces.
    fn closures_can_be_met(&self, free: &[usize], corners: &[Corner], cavities: &[Cavity]) -> bool {
        let tolerance = *self.assembly.tolerance();
        for corner in corners.iter().filter(|c| c.is_convex(&tolerance)) {
            if !self.angles.supply(free, corner.angle, self.angle_slack) {
                return false;
            }
        }
        for cavity in cavities {
            let n = cavity.corners.len();
            for i in 0..n {
                let (a, b) = (
                    &corners[cavity.corners[i]],
                    &corners[cavity.corners[(i + 1) % n]],
                );
                if a.is_convex(&tolerance)
                    && b.is_convex(&tolerance)
                    && !self
                        .lengths
                        .supply(free, distance(a.vertex, b.vertex), self.length_slack)
                {
                    return false;
                }
            }
        }
        true
    }

    /// Whether putting the candidate down leaves a state that is not a dead end.
    fn survives(&mut self, candidate: &CandidatePlacement) -> bool {
        self.assembly
            .place(candidate.piece, candidate.pose)
            .expect("a proposed piece is free");
        let corners = self.assembly.frontier();
        let alive = if self.assembly.all_placed() {
            corners.is_empty()
        } else {
            match self.cavities(&corners) {
                Some(cavities) => self.dead_end(&corners, &cavities).is_none(),
                None => true,
            }
        };
        self.assembly.undo();
        alive
    }

    /// The placements for the convex corner that has the fewest. Ties go to the
    /// first corner.
    ///
    /// With `lookahead`, a placement only counts if the state it leads to is
    /// not a dead end. The corners are then taken fewest candidates first, so
    /// that looking ahead can stop as soon as a corner cannot win.
    fn branch(&mut self, corners: &[Corner]) -> Vec<CandidatePlacement> {
        let tolerance = *self.assembly.tolerance();
        let mut lists: Vec<Vec<CandidatePlacement>> = Vec::new();
        for corner in corners.iter().filter(|c| c.is_convex(&tolerance)) {
            let mut candidates = self.assembly.propose(corner);
            if let Some(anchor) = self.anchor {
                let before = candidates.len();
                candidates.retain(|c| c.piece != anchor || self.in_sector(c));
                self.stats.pruned_anchor += (before - candidates.len()) as u64;
            }
            if candidates.is_empty() {
                return Vec::new();
            }
            lists.push(candidates);
        }
        // Shortest first; the sort keeps the order of the corners among equals.
        lists.sort_by_key(Vec::len);
        if !(self.options.lookahead && self.pruning()) {
            return lists.into_iter().next().unwrap_or_default();
        }

        let mut best: Option<Vec<CandidatePlacement>> = None;
        for list in lists {
            let limit = best.as_ref().map_or(usize::MAX, Vec::len);
            let mut alive = Vec::new();
            for candidate in list {
                if self.survives(&candidate) {
                    alive.push(candidate);
                    if alive.len() >= limit {
                        break;
                    }
                } else {
                    self.stats.pruned_lookahead += 1;
                }
            }
            if alive.len() < limit {
                let dead = alive.is_empty();
                best = Some(alive);
                if dead {
                    break;
                }
            }
        }
        best.unwrap_or_default()
    }

    /// How many edges of the candidate, placed, are whole edges of placed pieces.
    fn matched_edges(&self, candidate: &CandidatePlacement) -> usize {
        let length = self.assembly.tolerance().length;
        let near = |a: Vec2, b: Vec2| distance(a, b) <= length;
        let world = transform(
            &self.assembly.shape(candidate.piece).polygon,
            &candidate.pose,
        );
        let n = world.len();
        (0..n)
            .filter(|&i| {
                let (a0, a1) = (world[i], world[(i + 1) % n]);
                self.assembly.placed().iter().any(|&other| {
                    let polygon = self.assembly.world(other).expect("a placed piece");
                    let m = polygon.len();
                    // A neighbour's edge runs the other way.
                    (0..m).any(|j| near(a0, polygon[(j + 1) % m]) && near(a1, polygon[j]))
                })
            })
            .count()
    }

    fn record(&mut self) {
        let poses: Vec<Pose> = (0..self.areas.len())
            .map(|p| self.assembly.pose(p).expect("every piece is placed"))
            .collect();
        let poses = match self.options.tray_rotations {
            TrayRotations::All => poses,
            TrayRotations::Once => {
                if self.solutions.iter().any(|s| self.symmetry.same(s, &poses)) {
                    self.stats.duplicates += 1;
                    return;
                }
                self.symmetry.canonical(&poses)
            }
        };
        self.solutions.push(poses);
        if self.first_solution.is_none() {
            self.first_solution = Some(self.started.elapsed());
        }
        if self
            .options
            .max_solutions
            .is_some_and(|most| self.solutions.len() >= most)
        {
            self.stopped = true;
        }
    }

    fn out_of_budget(&self) -> bool {
        self.options
            .node_limit
            .is_some_and(|limit| self.stats.nodes >= limit)
            || self
                .options
                .time_limit
                .is_some_and(|limit| self.started.elapsed() >= limit)
    }

    fn expand(&mut self) {
        if self.out_of_budget() {
            self.stopped = true;
            return;
        }
        self.stats.nodes += 1;
        let depth = self.assembly.placed().len() as u64;
        self.stats.max_depth = self.stats.max_depth.max(depth);

        let corners = self.assembly.frontier();
        if self.assembly.all_placed() {
            if corners.is_empty() {
                self.record();
            } else {
                self.stats.backtracks += 1;
            }
            return;
        }
        let cavities = self.cavities(&corners);
        if let Some(reason) = cavities
            .as_deref()
            .and_then(|cavities| self.dead_end(&corners, cavities))
        {
            match reason {
                DeadEnd::Cavity => self.stats.pruned_cavity += 1,
                DeadEnd::Closure => self.stats.pruned_closure += 1,
            }
            self.stats.backtracks += 1;
            return;
        }
        let mut candidates = self.branch(&corners);
        if candidates.is_empty() {
            self.stats.backtracks += 1;
            return;
        }
        match self.options.order {
            Order::Generated => {}
            Order::Random => self.random.shuffle(&mut candidates),
            Order::MatchedEdges => {
                let mut scored: Vec<(usize, CandidatePlacement)> = candidates
                    .into_iter()
                    .map(|c| (self.matched_edges(&c), c))
                    .collect();
                // Stable: equal scores keep the order they were generated in.
                scored.sort_by(|a, b| b.0.cmp(&a.0));
                candidates = scored.into_iter().map(|(_, c)| c).collect();
            }
        }
        for candidate in candidates {
            self.assembly
                .place(candidate.piece, candidate.pose)
                .expect("a proposed piece is free");
            self.stats.placements += 1;
            self.expand();
            self.assembly.undo();
            if self.stopped {
                return;
            }
        }
    }
}

/// Search for assemblies of `shapes` in `target`.
///
/// The polygons are local, convex and counter-clockwise. If the shapes have
/// roofs, the roofs must be continuous across the assembly, within
/// `tolerance.height`.
pub fn solve(
    target: Vec<Vec2>,
    shapes: Vec<Shape>,
    tolerance: ContactTolerance,
    options: &Options,
) -> Result<Outcome, AssemblyError> {
    let started = Instant::now();
    let count = shapes.len();
    let areas: Vec<f64> = shapes.iter().map(|s| signed_area(&s.polygon)).collect();
    let centroids: Vec<Vec2> = shapes.iter().map(|s| centroid(&s.polygon)).collect();
    let perimeter: f64 = (0..target.len())
        .map(|i| distance(target[i], target[(i + 1) % target.len()]))
        .sum();
    let symmetry_shapes = shapes.clone();
    // Refuses anything that is not a convex counter-clockwise polygon.
    let assembly = Assembly::new(target, shapes, tolerance)?;
    let widths: Vec<f64> = symmetry_shapes
        .iter()
        .map(|s| least_width(&s.polygon))
        .collect();
    let symmetry = Symmetry::new(
        assembly.target(),
        &symmetry_shapes,
        assembly.graph(),
        &tolerance,
    );

    let anchored = options.anchor
        && options.tray_rotations == TrayRotations::Once
        && symmetry.tray_order() > 1;
    let anchor = anchored
        .then(|| {
            let classes = symmetry.classes();
            (0..count)
                .filter(|&p| classes.iter().filter(|&&c| c == classes[p]).count() == 1)
                .max_by(|&a, &b| areas[a].total_cmp(&areas[b]).then(b.cmp(&a)))
        })
        .flatten();

    let signature = |p: usize| assembly.graph().signatures(p);
    let edge_lengths: Vec<Vec<f64>> = (0..count)
        .map(|p| signature(p).iter().map(|e| e.length).collect())
        .collect();
    let vertex_angles: Vec<Vec<f64>> = (0..count)
        .map(|p| signature(p).iter().map(|e| e.angle_start).collect())
        .collect();

    let mut search = Search {
        lengths: Values::new(edge_lengths.into_iter(), tolerance.length),
        angles: Values::new(vertex_angles.into_iter(), tolerance.angle),
        assembly,
        options,
        anchor,
        centroids,
        areas,
        widths,
        // A boundary off by the length tolerance all the way round the target.
        area_tolerance: tolerance.length * perimeter,
        length_slack: tolerance.length * (count + 1) as f64,
        angle_slack: tolerance.angle * (count + 1) as f64,
        stats: Stats::default(),
        solutions: Vec::new(),
        started,
        first_solution: None,
        stopped: false,
        random: Random(options.seed),
        symmetry,
    };
    search.expand();
    search.stats.candidates = search.assembly.stats();
    Ok(Outcome {
        solutions: search.solutions,
        exhausted: !search.stopped,
        stats: search.stats,
        elapsed: started.elapsed(),
        first_solution: search.first_solution,
        tray_order: search.symmetry.tray_order(),
        anchor,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    use tiling_core::Roof;
    use tiling_geometry::EdgeGraph;
    use tiling_geometry::testing::{TOL, Tiling, tiling};

    fn rectangle(w: f64, h: f64) -> Vec<Vec2> {
        vec![
            [-w / 2.0, -h / 2.0],
            [w / 2.0, -h / 2.0],
            [w / 2.0, h / 2.0],
            [-w / 2.0, h / 2.0],
        ]
    }

    fn bare(polygons: &[Vec<Vec2>]) -> Vec<Shape> {
        polygons
            .iter()
            .map(|polygon| Shape {
                polygon: polygon.clone(),
                roof: None,
            })
            .collect()
    }

    fn tray(w: f64, h: f64) -> Vec<Vec2> {
        vec![[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]]
    }

    fn whole() -> Options {
        Options {
            max_solutions: None,
            ..Options::default()
        }
    }

    fn every_turn() -> Options {
        Options {
            tray_rotations: TrayRotations::All,
            ..whole()
        }
    }

    /// The search with nothing but the branching rule.
    fn plain(options: Options) -> Options {
        Options {
            anchor: false,
            cavity_pruning: false,
            closure_pruning: false,
            lookahead: false,
            order: Order::Generated,
            ..options
        }
    }

    fn run(target: &[Vec2], shapes: &[Shape], options: &Options) -> Outcome {
        solve(target.to_vec(), shapes.to_vec(), TOL, options).unwrap()
    }

    fn symmetry(target: &[Vec2], shapes: &[Shape]) -> Symmetry {
        Symmetry::new(target, shapes, &EdgeGraph::build(shapes, &TOL), &TOL)
    }

    /// Whether two lists hold the same assemblies, each once.
    fn same_sets(symmetry: &Symmetry, a: &[Vec<Pose>], b: &[Vec<Pose>]) -> bool {
        a.len() == b.len()
            && a.iter()
                .all(|x| b.iter().filter(|y| symmetry.same(x, y)).count() == 1)
    }

    /// Three strips side by side in a 5 by 3 tray, 1, 1.5 and 2.5 wide.
    fn three_strips() -> (Vec<Vec2>, Vec<Vec<Vec2>>) {
        (
            tray(5.0, 3.0),
            vec![
                rectangle(1.0, 3.0),
                rectangle(1.5, 3.0),
                rectangle(2.5, 3.0),
            ],
        )
    }

    /// The roof each strip has when the three, in that order from the left,
    /// lie under the plane `z = 10 + x / 2`.
    fn strips_under_a_slope() -> Vec<Shape> {
        let (_, polygons) = three_strips();
        // Centres at x = 0.5, 1.75 and 3.75.
        [0.5, 1.75, 3.75]
            .iter()
            .zip(polygons)
            .map(|(&cx, polygon)| Shape {
                polygon,
                roof: Some(Roof {
                    z0: 10.0 + cx / 2.0,
                    gx: 0.5,
                    gy: 0.0,
                }),
            })
            .collect()
    }

    #[test]
    fn three_strips_can_stand_in_any_order() {
        // 3! orders. The tray has a half turn, which pairs each order with its
        // reverse: 3 assemblies, 6 with the turns counted.
        let (target, polygons) = three_strips();
        let shapes = bare(&polygons);
        let all = run(&target, &shapes, &every_turn());
        assert!(all.exhausted);
        assert_eq!(all.solutions.len(), 6);
        let once = run(&target, &shapes, &whole());
        assert!(once.exhausted);
        assert_eq!((once.tray_order, once.solutions.len()), (2, 3));
        // The anchor is the widest strip, and it did some of the work.
        assert_eq!(once.anchor, Some(2));
        assert!(once.stats.pruned_anchor > 0);
        let symmetry = symmetry(&target, &shapes);
        for a in &all.solutions {
            let twins = once.solutions.iter().filter(|o| symmetry.same(a, o));
            assert_eq!(twins.count(), 1);
        }
    }

    #[test]
    fn roofs_leave_the_three_strips_one_order() {
        // Heights at the left and right edges, in the order the roofs were cut:
        // (10, 10.5), (10.5, 11.25), (11.25, 12.5). Two unturned strips meet
        // only where a right height equals a left one, which is the original
        // order. A strip turned half round shows its other edge, and no two
        // right heights or two left heights agree. So: the original, and the
        // whole of it turned with the tray.
        let (target, _) = three_strips();
        let shapes = strips_under_a_slope();
        let all = run(&target, &shapes, &every_turn());
        assert!(all.exhausted);
        assert_eq!(all.solutions.len(), 2);
        assert!(all.stats.candidates.rejected_roof > 0);
        let once = run(&target, &shapes, &whole());
        assert_eq!(once.solutions.len(), 1);
        let at = |x: f64| Pose {
            x,
            y: 1.5,
            theta: 0.0,
        };
        let original = [at(0.5), at(1.75), at(3.75)];
        assert!(symmetry(&target, &shapes).same(&once.solutions[0], &original));
    }

    #[test]
    fn a_roof_out_of_step_leaves_no_assembly() {
        let (target, _) = three_strips();
        let mut shapes = strips_under_a_slope();
        shapes[1].roof.as_mut().unwrap().z0 += 0.25;
        let outcome = run(&target, &shapes, &whole());
        assert!(outcome.exhausted);
        assert!(outcome.solutions.is_empty());
    }

    #[test]
    fn pieces_that_cannot_fill_the_tray_have_no_assembly() {
        let shapes = bare(&[rectangle(1.0, 3.0), rectangle(1.5, 3.0)]);
        for options in [whole(), plain(whole())] {
            let outcome = run(&tray(5.0, 3.0), &shapes, &options);
            assert!(outcome.exhausted && outcome.solutions.is_empty());
            assert!(outcome.stats.backtracks > 0);
            assert_eq!(outcome.first_solution, None);
        }
    }

    #[test]
    fn a_tray_the_pieces_cannot_add_up_to_is_a_dead_end_at_once() {
        // Areas 6, 3 and 3 against a tray of 15: no set of them is 15. With
        // pruning the root is the only node; without, pieces are tried first.
        let shapes = bare(&[
            rectangle(2.0, 3.0),
            rectangle(1.0, 3.0),
            rectangle(3.0, 1.0),
        ]);
        let pruned = run(&tray(5.0, 3.0), &shapes, &whole());
        assert!(pruned.exhausted && pruned.solutions.is_empty());
        assert_eq!(pruned.stats.nodes, 1);
        assert_eq!(pruned.stats.pruned_cavity, 1);
        let unpruned = run(&tray(5.0, 3.0), &shapes, &plain(whole()));
        assert!(unpruned.exhausted && unpruned.solutions.is_empty());
        assert!(unpruned.stats.nodes > 1);
        assert_eq!(unpruned.stats.pruned_cavity, 0);
    }

    #[test]
    fn a_run_no_edges_add_up_to_is_a_dead_end() {
        // Areas fit: 2 x 3 and 3 x 3 in a 5 x 3 tray... but as 6 x 1 and 3 x 3
        // they do not: the 6 x 1 bar is longer than any wall. Area pruning
        // sees nothing wrong (6 + 9 = 15); the bottom run of 5 is 3 + nothing.
        let shapes = bare(&[rectangle(6.0, 1.0), rectangle(3.0, 3.0)]);
        let only_closure = Options {
            cavity_pruning: false,
            lookahead: false,
            ..whole()
        };
        let outcome = run(&tray(5.0, 3.0), &shapes, &only_closure);
        assert!(outcome.exhausted && outcome.solutions.is_empty());
        assert_eq!((outcome.stats.nodes, outcome.stats.pruned_closure), (1, 1));
        let only_cavity = Options {
            closure_pruning: false,
            lookahead: false,
            ..whole()
        };
        let outcome = run(&tray(5.0, 3.0), &shapes, &only_cavity);
        assert!(outcome.exhausted && outcome.solutions.is_empty());
        assert_eq!(outcome.stats.pruned_closure, 0);
        assert!(outcome.stats.nodes > 1);
    }

    #[test]
    fn limits_stop_the_search_and_say_so() {
        let (target, polygons) = three_strips();
        let shapes = bare(&polygons);
        let one = run(&target, &shapes, &Options::default());
        assert_eq!(one.solutions.len(), 1);
        assert!(!one.exhausted, "stopped at the first solution");
        assert!(one.first_solution.is_some());

        let limited = Options {
            node_limit: Some(2),
            ..every_turn()
        };
        let stopped = run(&target, &shapes, &limited);
        assert!(!stopped.exhausted);
        assert_eq!(stopped.stats.nodes, 2);

        let no_time = Options {
            time_limit: Some(Duration::ZERO),
            ..whole()
        };
        let stopped = run(&target, &shapes, &no_time);
        assert!(!stopped.exhausted && stopped.solutions.is_empty());
        assert_eq!(stopped.stats.nodes, 0);
    }

    #[test]
    fn bad_input_is_refused() {
        let mut clockwise = rectangle(1.0, 3.0);
        clockwise.reverse();
        assert_eq!(
            solve(tray(5.0, 3.0), bare(&[clockwise]), TOL, &whole()).unwrap_err(),
            AssemblyError::NotConvex(Some(0))
        );
    }

    #[test]
    fn a_seed_fixes_a_random_order_and_the_order_changes_nothing_found() {
        let (target, polygons) = three_strips();
        let shapes = bare(&polygons);
        let symmetry = symmetry(&target, &shapes);
        let reference = run(&target, &shapes, &whole());
        let mut orders = Vec::new();
        for seed in 0..8 {
            let options = Options {
                order: Order::Random,
                seed,
                ..whole()
            };
            let first = run(&target, &shapes, &options);
            let again = run(&target, &shapes, &options);
            assert_eq!(first.solutions, again.solutions);
            assert!(same_sets(&symmetry, &first.solutions, &reference.solutions));
            orders.push(first.solutions);
        }
        assert!(
            orders.iter().any(|o| o != &orders[0]),
            "eight seeds, one order"
        );
    }

    #[test]
    fn sums_are_found_refused_and_remembered() {
        // Pieces 0, 1, 2 with values {1, 4}, {2}, {8}.
        let values = Values::new(
            vec![vec![1.0, 4.0, 1.0], vec![2.0], vec![8.0]].into_iter(),
            1e-9,
        );
        assert_eq!(values.each[0], vec![1.0, 4.0], "repeats are dropped");
        let all = [0, 1, 2];
        // 14 = 4 + 2 + 8; 5 is 1 + 4, but both are piece 0's.
        assert!(values.supply(&all, 14.0, 1e-9));
        assert!(!values.supply(&all, 5.0, 1e-9));
        assert!(values.supply(&all, 6.0, 1e-9));
        assert!(!values.supply(&[0, 2], 6.0, 1e-9), "6 needs piece 1");
        assert!(!values.supply(&all, 15.0, 1e-9), "more than all of them");
        assert!(values.supply(&[], 0.0, 1e-9));
        assert!(!values.supply(&[], 1.0, 1e-9));
        // What was learnt about 6: pieces 0 and 1 supply it, pieces 0 and 2 cannot.
        {
            let known = values.known.borrow();
            let six = &known[&6.0f64.to_bits()];
            assert_eq!(six.supplied_by, vec![0b011]);
            assert_eq!(six.not_from, vec![0b101]);
        }
        assert!(values.supply(&all, 6.0, 1e-9));
        assert!(
            !values.supply(&[2], 6.0, 1e-9),
            "part of a set that could not"
        );
    }

    #[test]
    fn areas_add_up_or_do_not() {
        let areas = [5.0, 3.0, 2.0];
        let rest = [10.0, 5.0, 2.0, 0.0];
        let ask = |need: f64| adds_up(&areas, &rest, 0, need, 1e-9, &mut 1000);
        assert!(ask(7.0) && ask(10.0) && ask(0.0) && ask(5.0));
        assert!(!ask(4.0) && !ask(11.0) && !ask(1.0));
        // Out of budget, the answer is the one that prunes nothing.
        assert!(adds_up(&areas, &rest, 0, 4.0, 1e-9, &mut 0));
    }

    /// The pieces of a tiling, each with the roof it has under one plane over the whole target.
    fn under_a_plane(tiling: &Tiling, a: f64, b: f64) -> Vec<Shape> {
        tiling
            .local
            .iter()
            .zip(&tiling.poses)
            .map(|(polygon, pose)| {
                let (s, c) = pose.theta.sin_cos();
                Shape {
                    polygon: polygon.clone(),
                    roof: Some(Roof {
                        z0: 20.0 + a * pose.x + b * pose.y,
                        // The plane's gradient turned back into the piece's frame.
                        gx: c * a + s * b,
                        gy: -s * a + c * b,
                    }),
                }
            })
            .collect()
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(64))]

        #[test]
        fn the_search_finds_the_tiling_it_was_cut_from(tiling in tiling()) {
            let shapes = bare(&tiling.local);
            let outcome = run(&tiling.target, &shapes, &whole());
            prop_assert!(outcome.exhausted);
            prop_assert_eq!(outcome.stats.cavities_unknown, 0);
            let symmetry = symmetry(&tiling.target, &shapes);
            let hits = outcome.solutions.iter().filter(|s| symmetry.same(s, &tiling.poses)).count();
            prop_assert_eq!(hits, 1);
        }

        /// Pruning, lookahead, the anchor and the order are about work. What is
        /// found with all of them is what is found with none.
        #[test]
        fn the_rules_change_the_work_and_not_what_is_found(tiling in tiling(), seed in any::<u64>()) {
            let shapes = bare(&tiling.local);
            let symmetry = symmetry(&tiling.target, &shapes);
            let reference = run(&tiling.target, &shapes, &plain(whole()));
            prop_assert!(reference.exhausted);
            let variants = [
                whole(),
                Options { lookahead: false, ..whole() },
                Options { closure_pruning: false, ..whole() },
                Options { cavity_pruning: false, ..whole() },
                Options { anchor: false, ..whole() },
                Options { order: Order::Random, seed, ..whole() },
            ];
            for options in &variants {
                let outcome = run(&tiling.target, &shapes, options);
                prop_assert!(outcome.exhausted);
                prop_assert!(
                    same_sets(&symmetry, &outcome.solutions, &reference.solutions),
                    "{} found against {} with {:?}",
                    outcome.solutions.len(), reference.solutions.len(), options
                );
            }
            // With every turn of the tray counted, each assembly is one of those.
            let all = run(&tiling.target, &shapes, &every_turn());
            prop_assert!(all.solutions.len() >= reference.solutions.len());
            for found in &all.solutions {
                let twins = reference.solutions.iter().filter(|r| symmetry.same(found, r)).count();
                prop_assert_eq!(twins, 1);
            }
        }

        #[test]
        fn roofs_under_one_plane_are_continuous_and_a_lifted_one_is_not(
            tiling in tiling(),
            a in -0.5f64..0.5,
            b in -0.5f64..0.5,
            lifted in any::<prop::sample::Index>(),
        ) {
            let shapes = under_a_plane(&tiling, a, b);
            let outcome = run(&tiling.target, &shapes, &whole());
            prop_assert!(outcome.exhausted);
            let same = symmetry(&tiling.target, &shapes);
            let hits = outcome.solutions.iter().filter(|s| same.same(s, &tiling.poses)).count();
            prop_assert_eq!(hits, 1);
            // Roofs can only rule assemblies out.
            let flat = run(&tiling.target, &bare(&tiling.local), &every_turn());
            let roofed = run(&tiling.target, &shapes, &every_turn());
            prop_assert!(roofed.solutions.len() <= flat.solutions.len());

            // One roof 1 mm too high: wherever that piece has a neighbour there is a step.
            let mut broken = shapes.clone();
            let which = lifted.index(broken.len());
            broken[which].roof.as_mut().unwrap().z0 += 1.0;
            let same = symmetry(&tiling.target, &broken);
            let outcome = run(&tiling.target, &broken, &whole());
            prop_assert!(outcome.exhausted);
            prop_assert!(!outcome.solutions.iter().any(|s| same.same(s, &tiling.poses)));
        }
    }
}
