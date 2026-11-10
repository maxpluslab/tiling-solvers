//! Edges of a polygon, and the signature that decides which edges can mate.
//!
//! A signature holds what a rigid motion cannot change: the edge's length, the
//! interior angles at its two ends, and, for a roofed piece, the roof heights at
//! the ends and the roof's slope along and across the edge. Two edges can lie
//! flush against each other only if their signatures are compatible, so the
//! candidate generator compares signatures before it does any polygon work.

use tiling_core::{Roof, Vec2};

/// One side of a polygon, from `start` to `end` in the polygon's direction.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Edge {
    pub start: Vec2,
    pub end: Vec2,
}

impl Edge {
    pub fn length(&self) -> f64 {
        (self.end[0] - self.start[0]).hypot(self.end[1] - self.start[1])
    }

    /// Unit vector from `start` to `end`.
    pub fn direction(&self) -> Vec2 {
        let length = self.length();
        [
            (self.end[0] - self.start[0]) / length,
            (self.end[1] - self.start[1]) / length,
        ]
    }

    /// Unit normal pointing out of a counter-clockwise polygon.
    pub fn outward_normal(&self) -> Vec2 {
        let [dx, dy] = self.direction();
        [dy, -dx]
    }
}

/// The sides of a polygon in order: edge `i` runs from vertex `i` to vertex `i + 1`.
pub fn edges(polygon: &[Vec2]) -> Vec<Edge> {
    let n = polygon.len();
    (0..n)
        .map(|i| Edge {
            start: polygon[i],
            end: polygon[(i + 1) % n],
        })
        .collect()
}

/// What stays the same about an edge wherever its piece is placed.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EdgeSignature {
    /// Length in millimetres.
    pub length: f64,
    /// Interior angle of the polygon at the edge's start, in radians.
    pub angle_start: f64,
    /// Interior angle of the polygon at the edge's end, in radians.
    pub angle_end: f64,
    /// Roof height at the start and at the end, for a roofed piece.
    pub height_start: Option<f64>,
    pub height_end: Option<f64>,
    /// Roof slope along the edge, from start to end, in mm per mm.
    pub slope_along: Option<f64>,
    /// Roof slope along the outward normal, in mm per mm.
    pub slope_across: Option<f64>,
}

/// Interior angle at vertex `i` of a convex counter-clockwise polygon.
fn interior_angle(polygon: &[Vec2], i: usize) -> f64 {
    let n = polygon.len();
    let a = polygon[(i + n - 1) % n];
    let b = polygon[i];
    let c = polygon[(i + 1) % n];
    let (ex, ey) = (b[0] - a[0], b[1] - a[1]);
    let (fx, fy) = (c[0] - b[0], c[1] - b[1]);
    let turn = (ex * fy - ey * fx).atan2(ex * fx + ey * fy);
    std::f64::consts::PI - turn
}

/// Signatures of every edge of a piece, in edge order. `polygon` and `roof`
/// are in the same coordinates, normally the piece's local ones.
pub fn edge_signatures(polygon: &[Vec2], roof: Option<&Roof>) -> Vec<EdgeSignature> {
    let n = polygon.len();
    edges(polygon)
        .iter()
        .enumerate()
        .map(|(i, edge)| {
            let [dx, dy] = edge.direction();
            let [nx, ny] = edge.outward_normal();
            EdgeSignature {
                length: edge.length(),
                angle_start: interior_angle(polygon, i),
                angle_end: interior_angle(polygon, (i + 1) % n),
                height_start: roof.map(|r| r.height_at(edge.start)),
                height_end: roof.map(|r| r.height_at(edge.end)),
                slope_along: roof.map(|r| r.gx * dx + r.gy * dy),
                slope_across: roof.map(|r| r.gx * nx + r.gy * ny),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::polygon::transform;
    use crate::testing::{close, convex_polygon, pose, roof};
    use proptest::prelude::*;
    use std::f64::consts::{FRAC_PI_2, FRAC_PI_4, PI};
    use tiling_core::Pose;

    #[test]
    fn edges_follow_the_vertices_and_close_the_polygon() {
        let triangle = [[0.0, 0.0], [4.0, 0.0], [0.0, 3.0]];
        let sides = edges(&triangle);
        assert_eq!(sides.len(), 3);
        assert_eq!((sides[2].start, sides[2].end), ([0.0, 3.0], [0.0, 0.0]));
        assert!(close(sides[1].length(), 5.0, 1e-12));
        // The bottom edge runs along +x; outside is below it.
        assert_eq!(sides[0].direction(), [1.0, 0.0]);
        assert_eq!(sides[0].outward_normal(), [0.0, -1.0]);
        // The hypotenuse faces up and to the right: (3, 4) / 5.
        let [nx, ny] = sides[1].outward_normal();
        assert!(close(nx, 0.6, 1e-12) && close(ny, 0.8, 1e-12));
    }

    #[test]
    fn signature_of_a_right_isosceles_triangle() {
        let triangle = [[0.0, 0.0], [2.0, 0.0], [0.0, 2.0]];
        let signatures = edge_signatures(&triangle, None);
        assert!(close(signatures[0].length, 2.0, 1e-12));
        assert!(close(signatures[0].angle_start, FRAC_PI_2, 1e-12));
        assert!(close(signatures[0].angle_end, FRAC_PI_4, 1e-12));
        assert!(close(signatures[1].length, 8f64.sqrt(), 1e-12));
        assert!(close(signatures[1].angle_start, FRAC_PI_4, 1e-12));
        assert!(close(signatures[1].angle_end, FRAC_PI_4, 1e-12));
        assert_eq!(signatures[0].height_start, None);
        assert_eq!(signatures[0].slope_along, None);
    }

    #[test]
    fn signature_of_a_roofed_square() {
        // z = 10 + 0.5 x on the square [-1, 1]^2: 9.5 on the left side, 10.5 on the right.
        let square = [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]];
        let plane = Roof {
            z0: 10.0,
            gx: 0.5,
            gy: 0.0,
        };
        let signatures = edge_signatures(&square, Some(&plane));
        // Bottom edge, left to right: climbs 1 mm over 2 mm, level across.
        assert_eq!(signatures[0].height_start, Some(9.5));
        assert_eq!(signatures[0].height_end, Some(10.5));
        assert_eq!(signatures[0].slope_along, Some(0.5));
        assert_eq!(signatures[0].slope_across, Some(0.0));
        // Right edge, going up: level along, rising outwards.
        assert_eq!(signatures[1].height_start, Some(10.5));
        assert_eq!(signatures[1].height_end, Some(10.5));
        assert_eq!(signatures[1].slope_along, Some(0.0));
        assert_eq!(signatures[1].slope_across, Some(0.5));
        // Left edge, going down: falling outwards.
        assert_eq!(signatures[3].slope_across, Some(-0.5));
    }

    proptest! {
        #[test]
        fn lengths_and_angles_add_up(polygon in convex_polygon()) {
            let signatures = edge_signatures(&polygon, None);
            let n = polygon.len();
            let angle_sum: f64 = signatures.iter().map(|s| s.angle_start).sum();
            prop_assert!(close(angle_sum, (n as f64 - 2.0) * PI, 1e-9));
            for (i, signature) in signatures.iter().enumerate() {
                prop_assert!(signature.angle_start > 0.0 && signature.angle_start < PI);
                // The end of one edge is the start of the next.
                prop_assert_eq!(signature.angle_end, signatures[(i + 1) % n].angle_start);
            }
        }

        #[test]
        fn heights_and_slope_agree_along_every_edge(polygon in convex_polygon(), plane in roof()) {
            let signatures = edge_signatures(&polygon, Some(&plane));
            let n = polygon.len();
            for (i, s) in signatures.iter().enumerate() {
                let rise = s.height_end.unwrap() - s.height_start.unwrap();
                prop_assert!(close(rise, s.slope_along.unwrap() * s.length, 1e-9));
                prop_assert_eq!(s.height_end, signatures[(i + 1) % n].height_start);
                // The two components are the whole gradient.
                let steepness = s.slope_along.unwrap().hypot(s.slope_across.unwrap());
                prop_assert!(close(steepness, plane.gx.hypot(plane.gy), 1e-12));
            }
        }

        #[test]
        fn a_signature_does_not_depend_on_where_the_piece_is(polygon in convex_polygon(), plane in roof(), motion in pose()) {
            // Turn the piece about its origin and the roof gradient with it; z0 belongs to the origin.
            let turn = Pose { x: 0.0, y: 0.0, theta: motion.theta };
            let turned = transform(&polygon, &turn);
            let [gx, gy] = turn.apply([plane.gx, plane.gy]);
            let turned_roof = Roof { z0: plane.z0, gx, gy };
            let before = edge_signatures(&polygon, Some(&plane));
            let after = edge_signatures(&turned, Some(&turned_roof));
            for (b, a) in before.iter().zip(&after) {
                prop_assert!(close(b.length, a.length, 1e-9));
                prop_assert!(close(b.angle_start, a.angle_start, 1e-9));
                prop_assert!(close(b.angle_end, a.angle_end, 1e-9));
                prop_assert!(close(b.height_start.unwrap(), a.height_start.unwrap(), 1e-9));
                prop_assert!(close(b.height_end.unwrap(), a.height_end.unwrap(), 1e-9));
                prop_assert!(close(b.slope_along.unwrap(), a.slope_along.unwrap(), 1e-9));
                prop_assert!(close(b.slope_across.unwrap(), a.slope_across.unwrap(), 1e-9));
            }
        }
    }
}
