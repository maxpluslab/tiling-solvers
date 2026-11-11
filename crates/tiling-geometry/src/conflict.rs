//! Which of a finite set of placements cannot be in one assembly together.
//!
//! A solver that chooses among placements listed in advance, CP-SAT for one,
//! needs to be told which pairs exclude each other. Two placements conflict
//! when they overlap by more than the length tolerance, or, if both have
//! roofs, when their roofs step by more than the height tolerance along an
//! edge stretch they share.
//!
//! Overlap is common: on the corpus about a third of all pairs conflict.
//! Listing them one by one would be millions of constraints for a few
//! thousand placements. Most are stated more compactly through *probes*: fixed
//! points of the target. Placements that all hold one probe well inside them
//! overlap one another, so "at most one of these" says in one constraint what
//! would otherwise take a pair for every two of them. The probes are a grid,
//! and then, for each overlap the grid missed, a point in the middle of what
//! the two placements share. Conflicts that no probe can witness, overlaps a
//! few tolerances thin and roof steps, are listed as pairs.
//!
//! Every clique holds only conflicting placements, and every conflicting pair
//! is in a clique or in the pair list. Both are tested against a pair-by-pair
//! comparison.
//!
//! The probes also say something no pair can: that the target is to be
//! covered. A probe inside the target lies in some piece of any assembly, so
//! of the placements that reach a probe an assembly holds at least one. These
//! *covers* follow from the rest when the areas of the pieces add up to the
//! target's, so they exclude nothing; they hand a solver that knows no
//! geometry the reason a half-built choice cannot be completed.

use tiling_core::{Pose, Roof, Vec2};

use crate::clip::intersection;
use crate::contact::ContactTolerance;
use crate::polygon::centroid;
use crate::relief::seam_step;
use crate::sat::penetration_depth;

/// A placement as the conflict test sees it.
#[derive(Debug, Clone, PartialEq)]
pub struct Placed {
    /// The placed polygon, in world coordinates.
    pub world: Vec<Vec2>,
    /// The roof and the pose that placed it, for pieces with roofs.
    pub roof: Option<(Roof, Pose)>,
}

/// Why two placements cannot be in one assembly.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Conflict {
    Overlap,
    RoofStep,
}

/// The conflicts among a set of placements, in a form a constraint solver takes.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Conflicts {
    /// Sets of placements of which an assembly holds at most one. Indices
    /// into the placements, ascending within a set.
    pub cliques: Vec<Vec<u32>>,
    /// Conflicting pairs that no clique holds, lower index first.
    pub pairs: Vec<(u32, u32)>,
    /// Sets of placements of which an assembly that covers the target holds
    /// at least one: for each probe inside the target, the placements that
    /// reach it, boundary included.
    pub covers: Vec<Vec<u32>>,
    /// How many pairs overlap, whether a clique states it or the pair list.
    pub overlapping: u64,
    /// How many pairs fit side by side and are kept apart by their roofs alone.
    pub roof_steps: u64,
}

/// Whether, and why, two placements exclude each other.
pub fn conflict(a: &Placed, b: &Placed, tolerance: &ContactTolerance) -> Option<Conflict> {
    if penetration_depth(&a.world, &b.world) > tolerance.length {
        return Some(Conflict::Overlap);
    }
    let (Some((roof_a, pose_a)), Some((roof_b, pose_b))) = (&a.roof, &b.roof) else {
        return None;
    };
    let step = seam_step(
        &a.world,
        roof_a,
        pose_a,
        &b.world,
        roof_b,
        pose_b,
        tolerance.length,
    );
    (step > tolerance.height).then_some(Conflict::RoofStep)
}

fn bounds(polygon: &[Vec2]) -> [f64; 4] {
    let mut b = [
        f64::INFINITY,
        f64::INFINITY,
        f64::NEG_INFINITY,
        f64::NEG_INFINITY,
    ];
    for p in polygon {
        b[0] = b[0].min(p[0]);
        b[1] = b[1].min(p[1]);
        b[2] = b[2].max(p[0]);
        b[3] = b[3].max(p[1]);
    }
    b
}

/// Whether `point` is inside the convex counter-clockwise `polygon`, at least
/// `margin` from every edge.
fn well_inside(polygon: &[Vec2], point: Vec2, margin: f64) -> bool {
    let n = polygon.len();
    (0..n).all(|i| {
        let (a, b) = (polygon[i], polygon[(i + 1) % n]);
        let (ex, ey) = (b[0] - a[0], b[1] - a[1]);
        let cross = ex * (point[1] - a[1]) - ey * (point[0] - a[0]);
        cross >= margin * ex.hypot(ey)
    })
}

/// Offsets of the probe grid within a cell. Irrational, so that probes do not
/// fall on the lines a tiling of a square tray tends to have: halves, thirds,
/// the diagonals.
const OFFSET: Vec2 = [0.381_966_011_250_105, 0.618_033_988_749_895];

/// The conflicts among `placed`, using `grid` probes along each side of the
/// target's bounding box.
///
/// More probes state more of the overlaps as cliques and fewer as pairs, at
/// the cost of more and smaller cliques. With `targeted`, an overlap the grid
/// missed gets a probe of its own where one fits; without, it is listed as a
/// pair. The answer says the same thing for any grid, either way.
pub fn conflicts(
    target: &[Vec2],
    placed: &[Placed],
    tolerance: &ContactTolerance,
    grid: usize,
    targeted: bool,
) -> Conflicts {
    let count = placed.len();
    let grid = grid.max(1);
    let frame = bounds(target);
    let step = [
        (frame[2] - frame[0]) / grid as f64,
        (frame[3] - frame[1]) / grid as f64,
    ];
    let probe = |i: usize, j: usize| {
        [
            frame[0] + (i as f64 + OFFSET[0]) * step[0],
            frame[1] + (j as f64 + OFFSET[1]) * step[1],
        ]
    };
    // Two polygons that hold a point this far inside them overlap by more than
    // the tolerance: each holds the disc of this radius about the point.
    let margin = 16.0 * tolerance.length;

    let words = (grid * grid).div_ceil(64);
    let boxes: Vec<[f64; 4]> = placed.iter().map(|p| bounds(&p.world)).collect();
    let mut holds = vec![0u64; count * words];
    let mut at_probe: Vec<Vec<u32>> = vec![Vec::new(); grid * grid];
    let mut reaching: Vec<Vec<u32>> = vec![Vec::new(); grid * grid];
    for (index, piece) in placed.iter().enumerate() {
        let b = &boxes[index];
        let cells = |low: f64, high: f64, origin: f64, size: f64| {
            if size <= 0.0 {
                return 0..0;
            }
            let first = ((low - origin) / size).floor().max(0.0) as usize;
            let last = (((high - origin) / size).ceil().max(0.0) as usize).min(grid);
            first.min(last)..last
        };
        for i in cells(b[0], b[2], frame[0], step[0]) {
            for j in cells(b[1], b[3], frame[1], step[1]) {
                let cell = i * grid + j;
                if well_inside(&piece.world, probe(i, j), margin) {
                    holds[index * words + cell / 64] |= 1 << (cell % 64);
                    at_probe[cell].push(index as u32);
                }
                // On the boundary, or outside by no more than the tolerance, still counts.
                if well_inside(&piece.world, probe(i, j), -tolerance.length) {
                    reaching[cell].push(index as u32);
                }
            }
        }
    }
    let mut cliques: Vec<Vec<u32>> = at_probe.into_iter().filter(|c| c.len() >= 2).collect();
    cliques.sort();
    cliques.dedup();
    // Only probes that an assembly must cover: those inside the target.
    let mut covers: Vec<Vec<u32>> = (0..grid * grid)
        .filter(|&cell| well_inside(target, probe(cell / grid, cell % grid), margin))
        .map(|cell| std::mem::take(&mut reaching[cell]))
        .collect();
    covers.sort();
    covers.dedup();

    let shares_a_probe =
        |a: usize, b: usize| (0..words).any(|w| holds[a * words + w] & holds[b * words + w] != 0);
    let mut found = Conflicts {
        cliques,
        covers,
        ..Conflicts::default()
    };
    // Probes added where the grid saw nothing: for each placement, the ones it
    // holds, ascending.
    let mut extra: Vec<Vec<u32>> = vec![Vec::new(); count];
    let mut extras = 0u32;
    let shares_an_extra = |extra: &[Vec<u32>], a: usize, b: usize| {
        let (mut i, mut j) = (0, 0);
        while i < extra[a].len() && j < extra[b].len() {
            match extra[a][i].cmp(&extra[b][j]) {
                std::cmp::Ordering::Less => i += 1,
                std::cmp::Ordering::Greater => j += 1,
                std::cmp::Ordering::Equal => return true,
            }
        }
        false
    };
    for a in 0..count {
        for b in a + 1..count {
            let (p, q) = (&boxes[a], &boxes[b]);
            let slack = tolerance.length;
            if p[2] + slack < q[0]
                || q[2] + slack < p[0]
                || p[3] + slack < q[1]
                || q[3] + slack < p[1]
            {
                continue;
            }
            // Holding one probe well inside is overlap enough; no need to measure it.
            if shares_a_probe(a, b) || shares_an_extra(&extra, a, b) {
                found.overlapping += 1;
                continue;
            }
            match conflict(&placed[a], &placed[b], tolerance) {
                Some(Conflict::Overlap) => {
                    found.overlapping += 1;
                    // A probe in the middle of what the two share. Whatever else
                    // holds it joins them in one clique, and so do many of the
                    // overlaps still to come.
                    let shared = intersection(&placed[a].world, &placed[b].world);
                    let middle = if targeted && shared.len() >= 3 {
                        centroid(&shared)
                    } else {
                        [f64::NAN, f64::NAN]
                    };
                    if well_inside(&placed[a].world, middle, margin)
                        && well_inside(&placed[b].world, middle, margin)
                    {
                        let members: Vec<u32> = (0..count)
                            .filter(|&k| {
                                let r = &boxes[k];
                                r[0] <= middle[0]
                                    && middle[0] <= r[2]
                                    && r[1] <= middle[1]
                                    && middle[1] <= r[3]
                                    && well_inside(&placed[k].world, middle, margin)
                            })
                            .map(|k| k as u32)
                            .collect();
                        for &k in &members {
                            extra[k as usize].push(extras);
                        }
                        extras += 1;
                        found.cliques.push(members);
                    } else {
                        found.pairs.push((a as u32, b as u32));
                    }
                }
                Some(Conflict::RoofStep) => {
                    found.roof_steps += 1;
                    found.pairs.push((a as u32, b as u32));
                }
                None => {}
            }
        }
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::polygon::transform;
    use crate::testing::{TOL, convex_polygon, pose_near};
    use proptest::prelude::*;

    fn block(x0: f64, y0: f64, x1: f64, y1: f64) -> Placed {
        Placed {
            world: vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            roof: None,
        }
    }

    fn level(mut placed: Placed, height: f64) -> Placed {
        placed.roof = Some((
            Roof {
                z0: height,
                gx: 0.0,
                gy: 0.0,
            },
            Pose {
                x: 0.0,
                y: 0.0,
                theta: 0.0,
            },
        ));
        placed
    }

    fn tray() -> Vec<Vec2> {
        vec![[0.0, 0.0], [8.0, 0.0], [8.0, 8.0], [0.0, 8.0]]
    }

    /// Every pair the answer excludes, from its cliques and its pairs.
    fn excluded(found: &Conflicts) -> Vec<(u32, u32)> {
        let mut all = found.pairs.clone();
        for clique in &found.cliques {
            for (k, &a) in clique.iter().enumerate() {
                for &b in &clique[k + 1..] {
                    all.push((a, b));
                }
            }
        }
        all.sort_unstable();
        all.dedup();
        all
    }

    #[test]
    fn blocks_side_by_side_do_not_conflict_and_blocks_that_overlap_do() {
        // Left half, right half, and the middle half that overlaps both by 2.
        let placed = [
            block(0.0, 0.0, 4.0, 8.0),
            block(4.0, 0.0, 8.0, 8.0),
            block(2.0, 0.0, 6.0, 8.0),
        ];
        assert_eq!(conflict(&placed[0], &placed[1], &TOL), None);
        assert_eq!(
            conflict(&placed[0], &placed[2], &TOL),
            Some(Conflict::Overlap)
        );
        for grid in [1, 2, 7, 48] {
            let found = conflicts(&tray(), &placed, &TOL, grid, true);
            assert_eq!(excluded(&found), [(0, 2), (1, 2)], "grid {grid}");
            assert_eq!((found.overlapping, found.roof_steps), (2, 0));
        }
    }

    #[test]
    fn one_probe_states_many_overlaps_at_once() {
        // Four blocks that all hold the middle of the tray: six overlapping pairs.
        let placed = [
            block(0.0, 0.0, 5.0, 5.0),
            block(3.0, 0.0, 8.0, 5.0),
            block(0.0, 3.0, 5.0, 8.0),
            block(3.0, 3.0, 8.0, 8.0),
        ];
        // With one probe, at (3.06, 4.94), inside all four.
        let found = conflicts(&tray(), &placed, &TOL, 1, true);
        assert_eq!(found.cliques, [vec![0, 1, 2, 3]]);
        assert!(found.pairs.is_empty());
        assert_eq!(found.overlapping, 6);
    }

    #[test]
    fn every_probe_in_the_target_names_the_placements_that_reach_it() {
        // Left half, right half, and a block over the lower left quarter.
        let placed = [
            block(0.0, 0.0, 4.0, 8.0),
            block(4.0, 0.0, 8.0, 8.0),
            block(0.0, 0.0, 4.0, 4.0),
        ];
        // Four probes: (1.53, 2.47), (1.53, 6.47), (5.53, 2.47), (5.53, 6.47).
        let found = conflicts(&tray(), &placed, &TOL, 2, true);
        assert_eq!(found.covers, [vec![0], vec![0, 2], vec![1]]);
        // A probe nothing reaches still asks to be covered: no choice can.
        let found = conflicts(&tray(), &placed[..1], &TOL, 2, true);
        assert_eq!(found.covers, [vec![], vec![0]]);
        // A probe outside the target asks for nothing. The tray's lower left
        // triangle holds only the first of the four.
        let triangle = vec![[0.0, 0.0], [8.0, 0.0], [0.0, 8.0]];
        let found = conflicts(&triangle, &placed, &TOL, 2, true);
        assert_eq!(found.covers, [vec![0, 2]]);
    }

    #[test]
    fn an_overlap_the_grid_misses_gets_a_probe_of_its_own() {
        // The two halves pushed 0.01 into each other, and a third block across
        // the seam. The grid's probes are 2 apart and miss the sliver the
        // halves share; the probe put in its middle, at (4.005, 4), is inside
        // the third block as well.
        let placed = [
            block(0.0, 0.0, 4.01, 8.0),
            block(4.0, 0.0, 8.0, 8.0),
            block(3.0, 3.0, 5.0, 5.0),
        ];
        let found = conflicts(&tray(), &placed, &TOL, 4, true);
        assert!(found.cliques.contains(&vec![0, 1, 2]));
        assert!(found.pairs.is_empty());
        assert_eq!(excluded(&found), [(0, 1), (0, 2), (1, 2)]);
        assert_eq!(found.overlapping, 3);
        // Not asked for, the probe is not made, and the halves are a pair. So are
        // the left half and the third block: the grid's probe in the block,
        // at about (4.76, 3.24), is right of the left half.
        let plain = conflicts(&tray(), &placed, &TOL, 4, false);
        assert_eq!(plain.pairs, [(0, 1), (0, 2)]);
        assert_eq!(excluded(&plain), [(0, 1), (0, 2), (1, 2)]);
    }

    #[test]
    fn an_overlap_too_thin_for_any_probe_is_listed_as_a_pair() {
        // Ten tolerances of overlap: more than the tolerance, so a conflict,
        // and less than the margin a probe needs on either side.
        let placed = [
            block(0.0, 0.0, 4.0 + 10.0 * TOL.length, 8.0),
            block(4.0, 0.0, 8.0, 8.0),
        ];
        let found = conflicts(&tray(), &placed, &TOL, 4, true);
        assert!(found.cliques.is_empty());
        assert_eq!(found.pairs, [(0, 1)]);
    }

    #[test]
    fn roofs_at_different_heights_keep_neighbours_apart() {
        let low = level(block(0.0, 0.0, 4.0, 8.0), 1.0);
        let same = level(block(4.0, 0.0, 8.0, 8.0), 1.0);
        let high = level(block(4.0, 0.0, 8.0, 8.0), 1.5);
        assert_eq!(conflict(&low, &same, &TOL), None);
        assert_eq!(conflict(&low, &high, &TOL), Some(Conflict::RoofStep));
        // Without a roof on one of them there is nothing to compare.
        assert_eq!(conflict(&low, &block(4.0, 0.0, 8.0, 8.0), &TOL), None);
        // Blocks that only meet at a corner share no edge, whatever their roofs.
        let corner = level(block(4.0, 8.0, 8.0, 12.0), 9.0);
        assert_eq!(conflict(&low, &corner, &TOL), None);
        let found = conflicts(&tray(), &[low, same, high], &TOL, 8, true);
        // The two right halves overlap entirely; the high one also steps against the left.
        assert_eq!(excluded(&found), [(0, 2), (1, 2)]);
        assert_eq!((found.overlapping, found.roof_steps), (1, 1));
    }

    proptest! {
        /// The cliques and pairs together exclude exactly the pairs that
        /// conflict when compared one by one, whatever the grid.
        #[test]
        fn cliques_and_pairs_say_what_a_pairwise_comparison_says(
            pieces in prop::collection::vec((convex_polygon(), pose_near()), 2..12),
            grid in 1usize..40,
            targeted in any::<bool>(),
        ) {
            let placed: Vec<Placed> = pieces
                .iter()
                .map(|(polygon, pose)| Placed { world: transform(polygon, pose), roof: None })
                .collect();
            let target = vec![[-80.0, -80.0], [80.0, -80.0], [80.0, 80.0], [-80.0, 80.0]];
            let found = conflicts(&target, &placed, &TOL, grid, targeted);
            let mut expected = Vec::new();
            for a in 0..placed.len() {
                for b in a + 1..placed.len() {
                    if conflict(&placed[a], &placed[b], &TOL).is_some() {
                        expected.push((a as u32, b as u32));
                    }
                }
            }
            prop_assert_eq!(excluded(&found), expected.clone());
            prop_assert_eq!(found.overlapping as usize, expected.len());
            // A cover is asked for at each distinct set of placements a probe meets;
            // the probes nothing reaches all ask for the same empty one.
            prop_assert!(found.covers.iter().filter(|c| c.is_empty()).count() <= 1);
            // A pair is not listed if a clique already states it.
            for pair in &found.pairs {
                prop_assert!(!found.cliques.iter().any(|c| c.contains(&pair.0) && c.contains(&pair.1)));
            }
        }
    }
}
