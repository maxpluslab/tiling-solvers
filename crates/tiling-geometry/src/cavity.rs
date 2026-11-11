//! Cavities: the separate parts of the uncovered region, traced from its corners.
//!
//! The uncovered region is still never built by clipping. Its boundary is
//! followed from corner to corner: a corner's first side runs along a fixed
//! edge with the region on its left, and it ends at the next corner on that
//! ray whose own wedge closes looking back along it. Following these links
//! from any corner comes round to it again, and the corners passed are the
//! outline of one cavity, counter-clockwise.
//!
//! A search only ever puts a piece down against the tray or against a placed
//! piece, so what is covered hangs together with the tray wall, and a cavity
//! has no holes: its outline is a single loop. A piece set down in the open,
//! touching nothing, would make a hole, whose outline runs the other way round
//! and has negative area; [`cavities`] declines to answer for such a state.
//!
//! Where the region touches itself at a point, that point carries one corner
//! for each side, and the two sides come out as two cavities. A convex piece
//! cannot reach through such a point, so they are filled separately.
//!
//! A search uses cavities to give up early: the pieces that go into a cavity
//! have exactly its area, and none of them is wider than a convex cavity is.

use std::f64::consts::{PI, TAU};

use tiling_core::Vec2;

use crate::contact::{ContactTolerance, Corner};

/// One connected part of the uncovered region.
#[derive(Debug, Clone, PartialEq)]
pub struct Cavity {
    /// Indices into the corner list, counter-clockwise round the cavity.
    pub corners: Vec<usize>,
    /// Square millimetres.
    pub area: f64,
    /// The cavity's least width, if it is convex: no piece wider than this
    /// fits into it. `None` for a cavity with a reflex corner.
    pub width: Option<f64>,
}

/// Difference between two directions, in `[0, π]`.
fn turn_between(a: f64, b: f64) -> f64 {
    let d = (a - b).rem_euclid(TAU);
    d.min(TAU - d)
}

/// The corner that follows `from` along the boundary: the nearest one on the
/// ray of its first side whose wedge closes looking back down the ray.
fn next_corner(corners: &[Corner], from: usize, tolerance: &ContactTolerance) -> Option<usize> {
    let corner = &corners[from];
    let (s, c) = corner.direction.sin_cos();
    let back = corner.direction + PI;
    let mut best: Option<(f64, usize)> = None;
    for (index, other) in corners.iter().enumerate() {
        if index == from {
            continue;
        }
        let (dx, dy) = (
            other.vertex[0] - corner.vertex[0],
            other.vertex[1] - corner.vertex[1],
        );
        let along = dx * c + dy * s;
        let off = (dy * c - dx * s).abs();
        if along <= tolerance.length || off > tolerance.length + tolerance.angle * along {
            continue;
        }
        if turn_between(other.direction + other.angle, back) > tolerance.angle {
            continue;
        }
        if best.is_none_or(|(nearest, _)| along < nearest) {
            best = Some((along, index));
        }
    }
    best.map(|(_, index)| index)
}

/// Least width of a convex counter-clockwise polygon: over its edges, the
/// farthest any vertex lies from the edge's line. A convex polygon fits inside
/// another only if it is no wider than this.
pub fn least_width(outline: &[Vec2]) -> f64 {
    let n = outline.len();
    let mut least = f64::INFINITY;
    for i in 0..n {
        let (p, q) = (outline[i], outline[(i + 1) % n]);
        let length = (q[0] - p[0]).hypot(q[1] - p[1]);
        let reach = outline
            .iter()
            .map(|v| ((q[0] - p[0]) * (v[1] - p[1]) - (q[1] - p[1]) * (v[0] - p[0])) / length)
            .fold(0.0, f64::max);
        least = least.min(reach);
    }
    least
}

/// The cavities whose corners are `corners`, as [`crate::free_corners`] lists them.
///
/// `None` if the corners do not link up into closed loops, or if some loop is
/// the outline of a hole. Neither happens for pieces placed corner to corner,
/// each against the tray or an earlier piece, and a caller that prunes on
/// cavities must treat `None` as "nothing known" rather than as a dead end.
pub fn cavities(corners: &[Corner], tolerance: &ContactTolerance) -> Option<Vec<Cavity>> {
    let found = outlines(corners, tolerance)?;
    found.iter().all(|c| c.area > 0.0).then_some(found)
}

/// Every closed loop of the boundary. A hole's loop runs clockwise and its
/// area is negative.
fn outlines(corners: &[Corner], tolerance: &ContactTolerance) -> Option<Vec<Cavity>> {
    let count = corners.len();
    let mut next = Vec::with_capacity(count);
    let mut entered = vec![false; count];
    for from in 0..count {
        let to = next_corner(corners, from, tolerance)?;
        if entered[to] {
            return None;
        }
        entered[to] = true;
        next.push(to);
    }

    let mut seen = vec![false; count];
    let mut found = Vec::new();
    for start in 0..count {
        if seen[start] {
            continue;
        }
        let mut loop_corners = Vec::new();
        let mut at = start;
        while !seen[at] {
            seen[at] = true;
            loop_corners.push(at);
            at = next[at];
        }
        let outline: Vec<Vec2> = loop_corners.iter().map(|&i| corners[i].vertex).collect();
        let n = outline.len();
        let twice: f64 = (0..n)
            .map(|i| {
                let (p, q) = (outline[i], outline[(i + 1) % n]);
                p[0] * q[1] - q[0] * p[1]
            })
            .sum();
        let convex = loop_corners
            .iter()
            .all(|&i| corners[i].is_convex(tolerance));
        found.push(Cavity {
            corners: loop_corners,
            area: twice / 2.0,
            width: convex.then(|| least_width(&outline)),
        });
    }
    Some(found)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contact::free_corners;
    use crate::polygon::signed_area;
    use crate::testing::{TOL, Tiling, close, tiling};
    use proptest::prelude::*;

    const TRAY: [Vec2; 4] = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]];

    fn rectangle(x0: f64, y0: f64, x1: f64, y1: f64) -> Vec<Vec2> {
        vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    }

    fn of(placed: &[Vec<Vec2>]) -> Vec<Cavity> {
        let listed: Vec<(usize, &[Vec2])> = placed
            .iter()
            .enumerate()
            .map(|(i, p)| (i, p.as_slice()))
            .collect();
        let corners = free_corners(&TRAY, &listed, &TOL);
        cavities(&corners, &TOL).expect("the corners link up")
    }

    #[test]
    fn the_empty_tray_is_one_convex_cavity() {
        let found = of(&[]);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].corners.len(), 4);
        assert!(close(found[0].area, 16.0, 1e-12));
        assert!(close(found[0].width.unwrap(), 4.0, 1e-12));
    }

    #[test]
    fn a_block_in_a_corner_leaves_an_l() {
        // 16 - 2 = 14, with a reflex corner at (2, 1): no width.
        let found = of(&[rectangle(0.0, 0.0, 2.0, 1.0)]);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].corners.len(), 6);
        assert!(close(found[0].area, 14.0, 1e-12));
        assert_eq!(found[0].width, None);
    }

    #[test]
    fn a_strip_across_the_tray_leaves_two_cavities() {
        // The strip 1 <= y <= 2 leaves 4 x 1 below and 4 x 2 above.
        let mut found = of(&[rectangle(0.0, 1.0, 4.0, 2.0)]);
        found.sort_by(|a, b| a.area.total_cmp(&b.area));
        assert_eq!(found.len(), 2);
        assert!(close(found[0].area, 4.0, 1e-12) && close(found[1].area, 8.0, 1e-12));
        assert!(close(found[0].width.unwrap(), 1.0, 1e-12));
        assert!(close(found[1].width.unwrap(), 2.0, 1e-12));
    }

    #[test]
    fn cavities_that_touch_at_a_point_are_separate() {
        // Two blocks meeting corner to corner at the centre leave two 2 x 2 squares.
        let found = of(&[rectangle(0.0, 0.0, 2.0, 2.0), rectangle(2.0, 2.0, 4.0, 4.0)]);
        assert_eq!(found.len(), 2);
        for cavity in &found {
            assert_eq!(cavity.corners.len(), 4);
            assert!(close(cavity.area, 4.0, 1e-12));
            assert!(close(cavity.width.unwrap(), 2.0, 1e-12));
        }
    }

    #[test]
    fn a_piece_in_the_open_makes_a_hole_and_no_answer() {
        let block = [rectangle(1.0, 1.0, 2.0, 2.0)];
        let listed: Vec<(usize, &[Vec2])> = vec![(0, block[0].as_slice())];
        let corners = free_corners(&TRAY, &listed, &TOL);
        // The tray's outline, 16, and the block's the other way round, -1.
        let mut loops = outlines(&corners, &TOL).unwrap();
        loops.sort_by(|a, b| a.area.total_cmp(&b.area));
        assert!(close(loops[0].area, -1.0, 1e-12) && close(loops[1].area, 16.0, 1e-12));
        assert_eq!(cavities(&corners, &TOL), None);
    }

    #[test]
    fn a_covered_tray_has_no_cavity() {
        assert!(of(&[rectangle(0.0, 0.0, 4.0, 4.0)]).is_empty());
    }

    #[test]
    fn the_width_of_a_triangle_is_its_least_height() {
        // A 3-4-5 triangle: heights 4, 3 and 12/5 onto the hypotenuse.
        let outline = [[0.0, 0.0], [3.0, 0.0], [0.0, 4.0]];
        assert!(close(least_width(&outline), 2.4, 1e-12));
    }

    #[test]
    fn corners_that_do_not_close_are_refused() {
        let listed: Vec<(usize, &[Vec2])> = Vec::new();
        let mut corners = free_corners(&TRAY, &listed, &TOL);
        corners.pop();
        assert_eq!(cavities(&corners, &TOL), None);
    }

    proptest! {
        /// Whatever part of a tiling is down, the cavities have the area of the
        /// pieces still missing, and each corner belongs to exactly one.
        #[test]
        fn cavities_have_the_area_of_the_missing_pieces(tiling in tiling(), mask in any::<u32>()) {
            let Tiling { target, world, .. } = &tiling;
            let placed: Vec<(usize, &[Vec2])> = world
                .iter()
                .enumerate()
                .filter(|(p, _)| mask >> p & 1 == 1)
                .map(|(p, polygon)| (p, polygon.as_slice()))
                .collect();
            let corners = free_corners(target, &placed, &TOL);
            // Any subset may be down here, so a piece can stand in the open and make a
            // hole. The loops are then still right, with the hole's area negative.
            let found = outlines(&corners, &TOL);
            prop_assert!(found.is_some(), "the corners link up");
            let found = found.unwrap();
            let holes = found.iter().filter(|c| c.area <= 0.0).count();
            prop_assert_eq!(cavities(&corners, &TOL).is_some(), holes == 0);
            let missing: f64 = world
                .iter()
                .enumerate()
                .filter(|(p, _)| mask >> p & 1 == 0)
                .map(|(_, polygon)| signed_area(polygon))
                .sum();
            let total: f64 = found.iter().map(|c| c.area).sum();
            prop_assert!(close(total, missing, 1e-6), "{total} uncovered, {missing} missing");
            let mut uses = vec![0; corners.len()];
            for cavity in &found {
                prop_assert!(cavity.area.abs() > 1e-6);
                for &corner in &cavity.corners {
                    uses[corner] += 1;
                }
            }
            prop_assert!(uses.iter().all(|&n| n == 1));
        }
    }
}
