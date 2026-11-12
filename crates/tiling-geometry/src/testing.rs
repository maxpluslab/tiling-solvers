//! Proptest strategies and helpers for tests, here and in the crates built on
//! this one, which reach them through the `testing` feature.

use std::f64::consts::{PI, TAU};

use proptest::prelude::*;
use tiling_core::{Pose, Roof, Vec2};

use crate::contact::ContactTolerance;
use crate::polygon::{centroid, distance_to_segment, is_convex_ccw};

/// Coincidence bounds for tests on exact constructions.
pub const TOL: ContactTolerance = ContactTolerance {
    length: 1e-7,
    angle: 1e-7,
    slope: 1e-7,
    height: 1e-7,
};

pub fn close(a: f64, b: f64, tolerance: f64) -> bool {
    (a - b).abs() <= tolerance
}

/// Strictly convex counter-clockwise polygons with 3 to 8 vertices, centred on
/// their area centroid, a few to a few tens of millimetres across.
///
/// Vertices lie on a circle at angles kept at least 0.3 rad apart, which is
/// convex by construction; an axis stretch then varies the shape. The same
/// construction as `tests/support/strategies.py`.
pub fn convex_polygon() -> impl Strategy<Value = Vec<Vec2>> {
    (3usize..=8)
        .prop_flat_map(|n| {
            (
                prop::collection::vec(0.05f64..1.0, n),
                5.0f64..40.0,
                0.4f64..1.0,
                0.0f64..TAU,
            )
        })
        .prop_map(|(weights, radius, stretch, start)| {
            let n = weights.len();
            let spare = TAU - 0.3 * n as f64;
            let total: f64 = weights.iter().sum();
            let mut gaps: Vec<f64> = weights.iter().map(|w| 0.3 + w * spare / total).collect();
            if gaps.iter().any(|&gap| gap > 0.9 * PI) {
                // A gap near a half turn would put the centre almost on an edge.
                gaps = vec![TAU / n as f64; n];
            }
            let mut angle = start;
            let mut points = Vec::with_capacity(n);
            for gap in gaps {
                points.push([radius * angle.cos(), stretch * radius * angle.sin()]);
                angle += gap;
            }
            let [cx, cy] = centroid(&points);
            points.iter().map(|p| [p[0] - cx, p[1] - cy]).collect()
        })
}

pub fn pose() -> impl Strategy<Value = Pose> {
    (-100.0f64..100.0, -100.0f64..100.0, -PI..PI).prop_map(|(x, y, theta)| Pose { x, y, theta })
}

/// Poses close enough together that two polygons often meet.
pub fn pose_near() -> impl Strategy<Value = Pose> {
    (-40.0f64..40.0, -40.0f64..40.0, -PI..PI).prop_map(|(x, y, theta)| Pose { x, y, theta })
}

pub fn point() -> impl Strategy<Value = Vec2> {
    (-100.0f64..100.0, -100.0f64..100.0).prop_map(|(x, y)| [x, y])
}

pub fn roof() -> impl Strategy<Value = Roof> {
    (5.0f64..50.0, -1.0f64..1.0, -1.0f64..1.0).prop_map(|(z0, gx, gy)| Roof { z0, gx, gy })
}

/// A convex target cut into convex pieces, with the pieces also given the way
/// a solver receives them: in local coordinates about the centroid, each turned
/// by its own angle.
#[derive(Debug, Clone)]
pub struct Tiling {
    pub target: Vec<Vec2>,
    /// The pieces where they belong.
    pub world: Vec<Vec<Vec2>>,
    pub local: Vec<Vec<Vec2>>,
    /// `transform(local[i], poses[i])` is `world[i]`.
    pub poses: Vec<Pose>,
}

/// Cut a convex polygon by the chord from a point on edge `first` to a point on edge `second`.
fn cut(polygon: &[Vec2], first: usize, second: usize, t: f64, u: f64) -> [Vec<Vec2>; 2] {
    let n = polygon.len();
    let on = |edge: usize, s: f64| {
        let (p, q) = (polygon[edge], polygon[(edge + 1) % n]);
        [p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])]
    };
    let (a, b) = (on(first, t), on(second, u));
    let mut one = vec![a];
    one.extend_from_slice(&polygon[first + 1..=second]);
    one.push(b);
    let mut two = vec![b];
    two.extend_from_slice(&polygon[second + 1..]);
    two.extend_from_slice(&polygon[..=first]);
    two.push(a);
    [one, two]
}

/// Sides of at least 1.5 mm and corners between about 14 and 166 degrees:
/// far from anything a tolerance could confuse.
fn well_shaped(polygon: &[Vec2]) -> bool {
    let n = polygon.len();
    is_convex_ccw(polygon)
        && (0..n).all(|i| {
            let (a, b, c) = (polygon[i], polygon[(i + 1) % n], polygon[(i + 2) % n]);
            let (ex, ey) = (b[0] - a[0], b[1] - a[1]);
            let (fx, fy) = (c[0] - b[0], c[1] - b[1]);
            let turn = (ex * fy - ey * fx).atan2(ex * fx + ey * fy);
            ex.hypot(ey) >= 1.5 && turn > 0.25 && turn < PI - 0.25
        })
}

/// Tilings of 2 to 6 pieces, made by cutting a convex polygon along chords.
///
/// A chord ends in the middle of two edges, so the pieces do not meet edge to
/// edge: each cut leaves T-junctions on the neighbours across those edges, and
/// on the target's own boundary.
pub fn tiling() -> impl Strategy<Value = Tiling> {
    let cuts = prop::collection::vec(
        (
            any::<prop::sample::Index>(),
            any::<prop::sample::Index>(),
            any::<prop::sample::Index>(),
            0.3f64..0.7,
            0.3f64..0.7,
        ),
        1..=5,
    );
    let turns = prop::collection::vec(-PI..PI, 6);
    (convex_polygon(), pose(), cuts, turns)
        .prop_map(|(polygon, at, cuts, turns)| {
            // Larger than a single piece, so that the cuts leave room.
            let target: Vec<Vec2> = polygon
                .iter()
                .map(|p| at.apply([3.0 * p[0], 3.0 * p[1]]))
                .collect();
            let mut world = vec![target.clone()];
            for (which, first, second, t, u) in cuts {
                let index = which.index(world.len());
                let n = world[index].len();
                let (i, j) = (first.index(n), second.index(n));
                if i == j {
                    continue;
                }
                let [one, two] = cut(&world[index], i.min(j), i.max(j), t, u);
                if well_shaped(&one) && well_shaped(&two) {
                    world[index] = one;
                    world.push(two);
                }
            }
            handed_out(target, world, &turns)
        })
        .prop_filter("at least one cut succeeded", |t| t.world.len() >= 2)
}

/// The pieces of a tiling as a solver receives them: each about its centroid,
/// turned by its own angle.
fn handed_out(target: Vec<Vec2>, world: Vec<Vec<Vec2>>, turns: &[f64]) -> Tiling {
    let mut local = Vec::new();
    let mut poses = Vec::new();
    for (piece, &turn) in world.iter().zip(turns) {
        let [cx, cy] = centroid(piece);
        let back = Pose {
            x: 0.0,
            y: 0.0,
            theta: -turn,
        };
        local.push(
            piece
                .iter()
                .map(|p| back.apply([p[0] - cx, p[1] - cy]))
                .collect(),
        );
        poses.push(Pose {
            x: cx,
            y: cy,
            theta: turn,
        });
    }
    Tiling {
        target,
        world,
        local,
        poses,
    }
}

/// The two sides of a convex polygon cut by the line through `at` in direction
/// `angle`, or `None` if the line does not pass through its interior.
fn split(polygon: &[Vec2], at: Vec2, angle: f64) -> Option<[Vec<Vec2>; 2]> {
    let (s, c) = angle.sin_cos();
    let side: Vec<f64> = polygon
        .iter()
        .map(|p| (p[1] - at[1]) * c - (p[0] - at[0]) * s)
        .collect();
    if side.iter().all(|&v| v > 0.0) || side.iter().all(|&v| v < 0.0) {
        return None;
    }
    let (mut left, mut right) = (Vec::new(), Vec::new());
    let n = polygon.len();
    for i in 0..n {
        let (p, q) = (polygon[i], polygon[(i + 1) % n]);
        let (a, b) = (side[i], side[(i + 1) % n]);
        if a > 0.0 {
            left.push(p)
        } else {
            right.push(p)
        }
        if (a > 0.0) != (b > 0.0) {
            let t = a / (a - b);
            let crossing = [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])];
            left.push(crossing);
            right.push(crossing);
        }
    }
    Some([left, right])
}

/// Tilings of 2 to 8 pieces that meet edge to edge: a convex polygon cut by
/// up to three whole lines, so that the pieces are the cells of a line
/// arrangement. Every cell a line crosses is cut, and a line whose cuts would
/// leave a badly shaped piece is not drawn at all.
pub fn line_tiling() -> impl Strategy<Value = Tiling> {
    let lines = prop::collection::vec((-15.0f64..15.0, -15.0f64..15.0, 0.0f64..PI), 1..=3);
    let turns = prop::collection::vec(-PI..PI, 8);
    (convex_polygon(), pose(), lines, turns)
        .prop_map(|(polygon, at, lines, turns)| {
            let target: Vec<Vec2> = polygon
                .iter()
                .map(|p| at.apply([3.0 * p[0], 3.0 * p[1]]))
                .collect();
            let middle = centroid(&target);
            let mut world = vec![target.clone()];
            for (dx, dy, angle) in lines {
                let through = [middle[0] + dx, middle[1] + dy];
                let mut cut = Vec::new();
                let mut drawn = true;
                for cell in &world {
                    match split(cell, through, angle) {
                        Some([one, two]) if well_shaped(&one) && well_shaped(&two) => {
                            cut.push(one);
                            cut.push(two);
                        }
                        Some(_) => drawn = false,
                        None => cut.push(cell.clone()),
                    }
                }
                if drawn && cut.len() <= 8 {
                    world = cut;
                }
            }
            handed_out(target, world, &turns)
        })
        .prop_filter("at least one line was drawn", |t| t.world.len() >= 2)
}

/// Whether placed pieces meet edge to edge, decided by twin edges: every piece
/// edge either lies on the target's boundary or is, reversed, exactly one edge
/// of exactly one other piece. For pieces that cover the target this is the
/// same as no vertex lying strictly inside another piece's edge, which is how
/// the candidate generator decides it; the two are written differently so that
/// one can check the other.
pub fn is_edge_to_edge(target: &[Vec2], world: &[Vec<Vec2>], tolerance: f64) -> bool {
    let near = |a: Vec2, b: Vec2| (a[0] - b[0]).hypot(a[1] - b[1]) <= tolerance;
    let m = target.len();
    let on_boundary = |a: Vec2, b: Vec2| {
        (0..m).any(|j| {
            let (s, e) = (target[j], target[(j + 1) % m]);
            distance_to_segment(a, s, e) <= tolerance && distance_to_segment(b, s, e) <= tolerance
        })
    };
    world.iter().enumerate().all(|(p, piece)| {
        let n = piece.len();
        (0..n).all(|i| {
            let (a, b) = (piece[i], piece[(i + 1) % n]);
            if on_boundary(a, b) {
                return true;
            }
            let twins: usize = world
                .iter()
                .enumerate()
                .filter(|&(q, _)| q != p)
                .map(|(_, other)| {
                    let k = other.len();
                    (0..k)
                        .filter(|&j| near(a, other[(j + 1) % k]) && near(b, other[j]))
                        .count()
                })
                .sum();
            twins == 1
        })
    })
}
