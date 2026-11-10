//! Separating-axis test for convex polygons.

use tiling_core::Vec2;

/// Extent of a polygon along a unit axis, as `(min, max)`.
fn extent(polygon: &[Vec2], axis: Vec2) -> (f64, f64) {
    polygon
        .iter()
        .map(|p| axis[0] * p[0] + axis[1] * p[1])
        .fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), d| {
            (lo.min(d), hi.max(d))
        })
}

/// Separating-axis measure for two convex counter-clockwise polygons.
///
/// Positive: the penetration depth, the length of the shortest translation
/// that separates them. For convex polygons that translation is along an edge
/// normal of one of them, so trying each normal is enough. Zero or negative:
/// touching or apart, and the magnitude is the widest gap along any edge normal.
///
/// This is the definition the independent validator uses. It is not the shared
/// extent along the axis, which understates the depth when one polygon's extent
/// lies wholly inside the other's.
pub fn penetration_depth(a: &[Vec2], b: &[Vec2]) -> f64 {
    let mut best = f64::INFINITY;
    for polygon in [a, b] {
        let n = polygon.len();
        for i in 0..n {
            let p = polygon[i];
            let q = polygon[(i + 1) % n];
            let length = (q[0] - p[0]).hypot(q[1] - p[1]);
            let normal = [(q[1] - p[1]) / length, -(q[0] - p[0]) / length];
            let (min_a, max_a) = extent(a, normal);
            let (min_b, max_b) = extent(b, normal);
            // How far b must move along this axis, either way, to clear a.
            best = best.min((max_a - min_b).min(max_b - min_a));
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clip::intersection_area;
    use crate::polygon::transform;
    use crate::testing::{close, convex_polygon, pose, pose_near};
    use proptest::prelude::*;

    const UNIT: [Vec2; 4] = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]];

    fn shifted(polygon: &[Vec2], dx: f64, dy: f64) -> Vec<Vec2> {
        polygon.iter().map(|p| [p[0] + dx, p[1] + dy]).collect()
    }

    #[test]
    fn two_unit_squares() {
        // The rows of tests/unit/test_validation.py::test_penetration_depth_of_two_unit_squares.
        for (dx, dy, expected) in [
            (0.7, 0.0, 0.3),  // overlap 0.3 wide: slide 0.3 to separate
            (0.7, 0.9, 0.1),  // 0.3 by 0.1: the short way out is 0.1
            (1.0, 0.0, 0.0),  // sharing an edge
            (1.0, 1.0, 0.0),  // sharing a corner
            (1.5, 0.0, -0.5), // half a unit apart
            (0.0, 0.0, 1.0),  // coincident
        ] {
            let other = shifted(&UNIT, dx, dy);
            assert!(close(penetration_depth(&UNIT, &other), expected, 1e-12));
            assert!(close(penetration_depth(&other, &UNIT), expected, 1e-12));
        }
    }

    #[test]
    fn a_small_square_inside_a_large_one_is_as_deep_as_the_way_out() {
        // A unit square 3 from the left of a 10 by 10: the shared extent is 1, leaving takes 4.
        let big = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]];
        let small = shifted(&UNIT, 3.0, 4.5);
        assert!(close(penetration_depth(&big, &small), 4.0, 1e-12));
        assert!(close(penetration_depth(&small, &big), 4.0, 1e-12));
    }

    #[test]
    fn the_slanted_axis_is_used() {
        // A corner 0.1/sqrt(2) through the hypotenuse x + y = 2.
        let triangle = [[0.0, 0.0], [2.0, 0.0], [0.0, 2.0]];
        let square = shifted(&UNIT, 0.95, 0.95);
        let expected = 0.1 / 2f64.sqrt();
        assert!(close(
            penetration_depth(&triangle, &square),
            expected,
            1e-12
        ));
    }

    proptest! {
        #[test]
        fn depth_is_symmetric(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            prop_assert!(close(penetration_depth(&a, &b), penetration_depth(&b, &a), 1e-9));
        }

        #[test]
        fn depth_survives_a_common_rigid_motion(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near(), motion in pose()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let (c, d) = (transform(&a, &motion), transform(&b, &motion));
            prop_assert!(close(penetration_depth(&a, &b), penetration_depth(&c, &d), 1e-7));
        }

        #[test]
        fn positive_depth_means_shared_area(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let depth = penetration_depth(&a, &b);
            prop_assume!(depth.abs() > 1e-6);
            prop_assert_eq!(depth > 0.0, intersection_area(&a, &b) > 0.0);
        }

        #[test]
        fn sliding_by_the_depth_separates_and_by_less_does_not(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let depth = penetration_depth(&a, &b);
            prop_assume!(depth > 1e-6);
            let mut cleared = f64::INFINITY;
            let mut still = f64::INFINITY;
            for polygon in [&a, &b] {
                let n = polygon.len();
                for i in 0..n {
                    let (p, q) = (polygon[i], polygon[(i + 1) % n]);
                    let length = (q[0] - p[0]).hypot(q[1] - p[1]);
                    let normal = [(q[1] - p[1]) / length, -(q[0] - p[0]) / length];
                    for sign in [1.0, -1.0] {
                        let slide = |by: f64| shifted(&b, sign * normal[0] * by, sign * normal[1] * by);
                        cleared = cleared.min(intersection_area(&a, &slide(depth)));
                        still = still.min(intersection_area(&a, &slide(0.9 * depth)));
                    }
                }
            }
            prop_assert!(cleared < 1e-6, "sliding by the depth left {cleared} shared");
            prop_assert!(still > 0.0, "a shorter slide already separated them");
        }
    }
}
