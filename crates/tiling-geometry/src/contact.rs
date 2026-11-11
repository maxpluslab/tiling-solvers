//! Contacts: where the uncovered part of the target has corners, and the pose
//! that puts a piece into one.
//!
//! The uncovered region is never built as a polygon. Its corners are found
//! locally: every corner lies at a vertex of the target or of a placed piece,
//! and around such a point each polygon that touches it covers a known range of
//! directions. What the ranges leave open is a free wedge, and a free wedge is
//! a corner of the uncovered region.
//!
//! A piece is put into a corner by a contact: one of its edges lies flush
//! against the edge that bounds the wedge, starting at the corner. That fixes
//! the rotation and both components of the translation, with no angular grid.

use std::f64::consts::{PI, TAU};

use tiling_core::{Pose, Vec2};

use crate::polygon::{contains_point, distance_to_segment};

/// How close counts as coincident. The search is for exact assemblies, so
/// these are noise bounds, far tighter than the tolerances a finished assembly
/// is judged by.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ContactTolerance {
    /// Millimetres.
    pub length: f64,
    /// Radians.
    pub angle: f64,
    /// Roof slope, in mm per mm.
    pub slope: f64,
    /// Roof height, in millimetres: how large a step between two roofs still
    /// counts as none.
    pub height: f64,
}

/// An edge of the target or of a piece. Edge `i` runs from vertex `i` to vertex `i + 1`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum EdgeRef {
    Tray { edge: usize },
    Piece { piece: usize, edge: usize },
}

/// A corner of the uncovered region: a free wedge at `vertex`, opening
/// counter-clockwise from `direction` through `angle`.
///
/// The ray from `vertex` along `direction` runs along `source`, an edge of the
/// target or of a placed piece, with the uncovered region on its left.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Corner {
    pub vertex: Vec2,
    /// Radians, in `[0, 2π)`.
    pub direction: f64,
    /// Radians, in `(0, 2π]`.
    pub angle: f64,
    pub source: EdgeRef,
}

impl Corner {
    /// Whether the wedge is narrower than a half turn. Only such a corner
    /// forces a piece to have a vertex in it.
    pub fn is_convex(&self, tolerance: &ContactTolerance) -> bool {
        self.angle < PI - tolerance.angle
    }
}

/// A range of directions around a point that some polygon occupies.
struct Cover {
    start: f64,
    width: f64,
    /// The edge along the direction where the range ends.
    source: EdgeRef,
}

enum Site {
    Vertex(usize),
    Edge(usize),
    Inside,
    Outside,
}

/// Whether two points are within `tolerance` of each other.
fn near(a: Vec2, b: Vec2, tolerance: f64) -> bool {
    let (dx, dy) = (a[0] - b[0], a[1] - b[1]);
    dx * dx + dy * dy <= tolerance * tolerance
}

fn locate(polygon: &[Vec2], p: Vec2, tolerance: f64) -> Site {
    let n = polygon.len();
    for (i, v) in polygon.iter().enumerate() {
        if near(*v, p, tolerance) {
            return Site::Vertex(i);
        }
    }
    for i in 0..n {
        if distance_to_segment(p, polygon[i], polygon[(i + 1) % n]) <= tolerance {
            return Site::Edge(i);
        }
    }
    if contains_point(polygon, p) {
        Site::Inside
    } else {
        Site::Outside
    }
}

fn heading(from: Vec2, to: Vec2) -> f64 {
    (to[1] - from[1]).atan2(to[0] - from[0])
}

/// The directions around a point on a polygon's boundary that point into the
/// polygon: from `start` counter-clockwise through `width`, and the edge that
/// lies along the far side.
fn interior_range(polygon: &[Vec2], site: &Site) -> Option<(f64, f64, usize)> {
    let n = polygon.len();
    match *site {
        Site::Vertex(i) => {
            let v = polygon[i];
            let start = heading(v, polygon[(i + 1) % n]);
            let end = heading(v, polygon[(i + n - 1) % n]);
            Some((start, (end - start).rem_euclid(TAU), (i + n - 1) % n))
        }
        Site::Edge(i) => Some((heading(polygon[i], polygon[(i + 1) % n]), PI, i)),
        Site::Inside | Site::Outside => None,
    }
}

/// The free wedges left by a set of covered ranges, as `(start, width, source)`.
fn free_wedges(mut covers: Vec<Cover>, tolerance: f64) -> Vec<(f64, f64, EdgeRef)> {
    if covers.is_empty() {
        return Vec::new();
    }
    for cover in &mut covers {
        cover.start = cover.start.rem_euclid(TAU);
    }
    covers.sort_by(|a, b| a.start.total_cmp(&b.start));

    // Merge ranges that overlap or abut, keeping the source of the farthest end.
    let mut merged: Vec<(f64, f64, EdgeRef)> = Vec::new();
    for cover in &covers {
        let end = cover.start + cover.width;
        match merged.last_mut() {
            Some(last) if cover.start <= last.1 + tolerance => {
                if end > last.1 {
                    last.1 = end;
                    last.2 = cover.source;
                }
            }
            _ => merged.push((cover.start, end, cover.source)),
        }
    }
    // The last range may run past a full turn into the first ones.
    while merged.len() > 1 {
        let first = merged[0];
        let last = merged.last_mut().expect("more than one range");
        if last.1 - TAU < first.0 - tolerance {
            break;
        }
        if first.1 + TAU > last.1 {
            last.1 = first.1 + TAU;
            last.2 = first.2;
        }
        merged.remove(0);
    }

    let count = merged.len();
    let mut wedges = Vec::new();
    for i in 0..count {
        let (_, end, source) = merged[i];
        let next_start = if i + 1 < count {
            merged[i + 1].0
        } else {
            merged[0].0 + TAU
        };
        let width = next_start - end;
        if width > tolerance {
            wedges.push((end.rem_euclid(TAU), width, source));
        }
    }
    wedges
}

/// Every corner of the part of `target` that the placed pieces leave uncovered.
/// A point where the boundary runs straight on is not a corner.
///
/// `placed` gives each placed piece's index and its polygon in the world. The
/// pieces are taken to lie inside the target without overlapping. Corners come
/// in a fixed order: by point, target vertices first and then the pieces as
/// given, and counter-clockwise around each point.
pub fn free_corners(
    target: &[Vec2],
    placed: &[(usize, &[Vec2])],
    tolerance: &ContactTolerance,
) -> Vec<Corner> {
    // Every vertex once, in the order given: a vertex is dropped if an earlier
    // one is within the tolerance. Looking along x keeps this from comparing
    // every pair.
    let all: Vec<Vec2> = target
        .iter()
        .chain(placed.iter().flat_map(|(_, polygon)| polygon.iter()))
        .copied()
        .collect();
    let mut by_x: Vec<usize> = (0..all.len()).collect();
    by_x.sort_by(|&a, &b| all[a][0].total_cmp(&all[b][0]));
    let mut repeated = vec![false; all.len()];
    for (rank, &i) in by_x.iter().enumerate() {
        for &j in &by_x[rank + 1..] {
            if all[j][0] - all[i][0] > tolerance.length {
                break;
            }
            if near(all[i], all[j], tolerance.length) {
                repeated[i.max(j)] = true;
            }
        }
    }
    let points: Vec<Vec2> = (0..all.len())
        .filter(|&i| !repeated[i])
        .map(|i| all[i])
        .collect();

    // A point outside a piece's box, grown by the tolerance, is outside the piece.
    let boxes: Vec<[f64; 4]> = placed
        .iter()
        .map(|(_, polygon)| {
            let mut b = [
                f64::INFINITY,
                f64::INFINITY,
                f64::NEG_INFINITY,
                f64::NEG_INFINITY,
            ];
            for q in polygon.iter() {
                b[0] = b[0].min(q[0] - tolerance.length);
                b[1] = b[1].min(q[1] - tolerance.length);
                b[2] = b[2].max(q[0] + tolerance.length);
                b[3] = b[3].max(q[1] + tolerance.length);
            }
            b
        })
        .collect();

    let mut corners = Vec::new();
    'points: for &p in &points {
        let mut covers = Vec::new();
        // The target covers everything that is not its interior.
        let site = locate(target, p, tolerance.length);
        match interior_range(target, &site) {
            Some((start, width, _)) => {
                let edge = match site {
                    Site::Vertex(i) | Site::Edge(i) => i,
                    Site::Inside | Site::Outside => unreachable!("a range has a boundary site"),
                };
                covers.push(Cover {
                    start: start + width,
                    width: TAU - width,
                    source: EdgeRef::Tray { edge },
                });
            }
            None if matches!(site, Site::Outside) => continue 'points,
            None => {}
        }
        for (&(piece, polygon), b) in placed.iter().zip(&boxes) {
            if p[0] < b[0] || p[0] > b[2] || p[1] < b[1] || p[1] > b[3] {
                continue;
            }
            let site = locate(polygon, p, tolerance.length);
            match interior_range(polygon, &site) {
                Some((start, width, edge)) => covers.push(Cover {
                    start,
                    width,
                    source: EdgeRef::Piece { piece, edge },
                }),
                None if matches!(site, Site::Inside) => continue 'points,
                None => {}
            }
        }
        for (direction, angle, source) in free_wedges(covers, tolerance.angle) {
            // A half turn left open is the middle of a straight run, not a corner.
            if (angle - PI).abs() <= tolerance.angle {
                continue;
            }
            corners.push(Corner {
                vertex: p,
                direction,
                angle,
                source,
            });
        }
    }
    corners
}

/// The pose that puts vertex `vertex` of a local polygon at `at`, with the edge
/// that leaves that vertex pointing along `direction`.
pub fn pose_at_corner(polygon: &[Vec2], vertex: usize, at: Vec2, direction: f64) -> Pose {
    let v = polygon[vertex];
    let next = polygon[(vertex + 1) % polygon.len()];
    let theta = direction - heading(v, next);
    // Keep the angle in (-π, π] so that equal placements have equal poses.
    let theta = PI - (PI - theta).rem_euclid(TAU);
    let (s, c) = theta.sin_cos();
    Pose {
        x: at[0] - (c * v[0] - s * v[1]),
        y: at[1] - (s * v[0] + c * v[1]),
        theta,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::polygon::transform;
    use crate::testing::{TOL, close, convex_polygon, pose};
    use proptest::prelude::*;
    use std::f64::consts::FRAC_PI_2;

    const TRAY: [Vec2; 4] = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]];

    fn rectangle(x0: f64, y0: f64, x1: f64, y1: f64) -> Vec<Vec2> {
        vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    }

    /// Corners as `(x, y, direction in quarter turns, angle in quarter turns, source)`.
    fn summary(corners: &[Corner]) -> Vec<(f64, f64, f64, f64, EdgeRef)> {
        corners
            .iter()
            .map(|c| {
                let round = |v: f64| (v * 1e6).round() / 1e6;
                (
                    round(c.vertex[0]),
                    round(c.vertex[1]),
                    round(c.direction / FRAC_PI_2),
                    round(c.angle / FRAC_PI_2),
                    c.source,
                )
            })
            .collect()
    }

    #[test]
    fn an_empty_square_has_its_four_corners() {
        // At each vertex the wedge opens from the edge that leaves it.
        let corners = free_corners(&TRAY, &[], &TOL);
        assert_eq!(
            summary(&corners),
            vec![
                (0.0, 0.0, 0.0, 1.0, EdgeRef::Tray { edge: 0 }),
                (4.0, 0.0, 1.0, 1.0, EdgeRef::Tray { edge: 1 }),
                (4.0, 4.0, 2.0, 1.0, EdgeRef::Tray { edge: 2 }),
                (0.0, 4.0, 3.0, 1.0, EdgeRef::Tray { edge: 3 }),
            ]
        );
        assert!(corners.iter().all(|c| c.is_convex(&TOL)));
    }

    #[test]
    fn a_piece_in_a_corner_leaves_an_l_shape() {
        // A 2 by 1 block in the bottom left. The L has six corners:
        // (2,0) and (0,1) on the walls, (2,1) reflex, and the three other tray corners.
        let block = rectangle(0.0, 0.0, 2.0, 1.0);
        let corners = free_corners(&TRAY, &[(7, &block)], &TOL);
        let piece = |edge| EdgeRef::Piece { piece: 7, edge };
        assert_eq!(
            summary(&corners),
            vec![
                (4.0, 0.0, 1.0, 1.0, EdgeRef::Tray { edge: 1 }),
                (4.0, 4.0, 2.0, 1.0, EdgeRef::Tray { edge: 2 }),
                (0.0, 4.0, 3.0, 1.0, EdgeRef::Tray { edge: 3 }),
                // From (2,0) the free boundary runs east along the tray's bottom edge.
                (2.0, 0.0, 0.0, 1.0, EdgeRef::Tray { edge: 0 }),
                // At (2,1) it turns down the block's right side, edge 1 reversed: reflex.
                (2.0, 1.0, 3.0, 3.0, piece(1)),
                // From (0,1) it runs east along the block's top, edge 2 reversed.
                (0.0, 1.0, 0.0, 1.0, piece(2)),
            ]
        );
        let convex: Vec<bool> = corners.iter().map(|c| c.is_convex(&TOL)).collect();
        assert_eq!(convex, vec![true, true, true, true, false, true]);
    }

    #[test]
    fn a_vertex_in_the_middle_of_an_edge_is_a_corner_only_if_something_is_left_open() {
        // Two blocks side by side along the bottom: (2,0) is covered on both sides,
        // and (2,1) is in the middle of a straight run, which is no corner.
        let left = rectangle(0.0, 0.0, 2.0, 1.0);
        let right = rectangle(2.0, 0.0, 4.0, 1.0);
        let corners = free_corners(&TRAY, &[(0, &left), (1, &right)], &TOL);
        let at: Vec<(f64, f64)> = summary(&corners).iter().map(|c| (c.0, c.1)).collect();
        assert_eq!(at, vec![(4.0, 4.0), (0.0, 4.0), (0.0, 1.0), (4.0, 1.0)]);

        // A taller neighbour makes (2,1) a corner again: a T-junction on its left side.
        let tall = rectangle(2.0, 0.0, 4.0, 3.0);
        let corners = free_corners(&TRAY, &[(0, &left), (1, &tall)], &TOL);
        let junction: Vec<_> = summary(&corners)
            .into_iter()
            .filter(|c| (c.0, c.1) == (2.0, 1.0))
            .collect();
        // Open from north round to west: it leaves up the tall block's left side, edge 3 reversed.
        assert_eq!(
            junction,
            vec![(2.0, 1.0, 1.0, 1.0, EdgeRef::Piece { piece: 1, edge: 3 })]
        );
    }

    #[test]
    fn a_covered_target_has_no_corners() {
        let halves = [rectangle(0.0, 0.0, 2.0, 4.0), rectangle(2.0, 0.0, 4.0, 4.0)];
        let placed: Vec<(usize, &[Vec2])> = halves.iter().map(|h| &h[..]).enumerate().collect();
        assert!(free_corners(&TRAY, &placed, &TOL).is_empty());
    }

    #[test]
    fn a_hole_has_corners_of_its_own() {
        // Four blocks around a 2 by 2 hole in the middle of the tray.
        let ring = [
            rectangle(0.0, 0.0, 3.0, 1.0),
            rectangle(3.0, 0.0, 4.0, 3.0),
            rectangle(1.0, 3.0, 4.0, 4.0),
            rectangle(0.0, 1.0, 1.0, 4.0),
        ];
        let placed: Vec<(usize, &[Vec2])> = ring.iter().map(|r| &r[..]).enumerate().collect();
        let corners = free_corners(&TRAY, &placed, &TOL);
        let mut at: Vec<(f64, f64)> = summary(&corners).iter().map(|c| (c.0, c.1)).collect();
        at.sort_by(|a, b| a.partial_cmp(b).unwrap());
        assert_eq!(at, vec![(1.0, 1.0), (1.0, 3.0), (3.0, 1.0), (3.0, 3.0)]);
        assert!(corners.iter().all(|c| c.is_convex(&TOL)));
        assert!(corners.iter().all(|c| close(c.angle, FRAC_PI_2, 1e-9)));
    }

    #[test]
    fn a_pose_at_a_corner_puts_the_vertex_there_and_the_edge_along_the_ray() {
        // A 3-4-5 triangle, its right angle put at (10, 20) with the long leg pointing north.
        let triangle = [[0.0, 0.0], [4.0, 0.0], [0.0, 3.0]];
        let pose = pose_at_corner(&triangle, 0, [10.0, 20.0], FRAC_PI_2);
        let world = transform(&triangle, &pose);
        let expected = [[10.0, 20.0], [10.0, 24.0], [7.0, 20.0]];
        for (p, q) in world.iter().zip(&expected) {
            assert!(close(p[0], q[0], 1e-12) && close(p[1], q[1], 1e-12));
        }
        assert!(close(pose.theta, FRAC_PI_2, 1e-12));
    }

    proptest! {
        #[test]
        fn a_pose_at_a_corner_is_exact_for_any_polygon(
            polygon in convex_polygon(), at in pose(), pick in 0usize..8,
        ) {
            let vertex = pick % polygon.len();
            let direction = at.theta.rem_euclid(TAU);
            let placed = pose_at_corner(&polygon, vertex, [at.x, at.y], direction);
            prop_assert!(placed.theta > -PI - 1e-12 && placed.theta <= PI + 1e-12);
            let world = transform(&polygon, &placed);
            let (v, next) = (world[vertex], world[(vertex + 1) % world.len()]);
            prop_assert!((v[0] - at.x).hypot(v[1] - at.y) < 1e-9);
            let turned = (heading(v, next) - direction).rem_euclid(TAU);
            prop_assert!(turned < 1e-9 || TAU - turned < 1e-9);
        }

        #[test]
        fn an_empty_target_has_one_convex_corner_per_vertex(polygon in convex_polygon(), at in pose()) {
            let target = transform(&polygon, &at);
            let corners = free_corners(&target, &[], &TOL);
            prop_assert_eq!(corners.len(), target.len());
            let total: f64 = corners.iter().map(|c| c.angle).sum();
            prop_assert!(close(total, (target.len() as f64 - 2.0) * PI, 1e-9));
            for (i, corner) in corners.iter().enumerate() {
                prop_assert!(corner.is_convex(&TOL));
                prop_assert_eq!(corner.vertex, target[i]);
                prop_assert_eq!(corner.source, EdgeRef::Tray { edge: i });
            }
        }

        #[test]
        fn a_target_filled_by_itself_has_no_corners(polygon in convex_polygon(), at in pose()) {
            let target = transform(&polygon, &at);
            prop_assert!(free_corners(&target, &[(0, &target)], &TOL).is_empty());
        }
    }
}
