//! Intersection of convex polygons by Sutherland–Hodgman clipping.

use tiling_core::Vec2;

use crate::polygon::signed_area;

/// Keep the part of `subject` to the left of the directed line `a` → `b`.
fn clip_left(subject: &[Vec2], a: Vec2, b: Vec2) -> Vec<Vec2> {
    let side = |p: Vec2| (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    let n = subject.len();
    let mut out = Vec::with_capacity(n + 1);
    for i in 0..n {
        let p = subject[i];
        let q = subject[(i + 1) % n];
        let (fp, fq) = (side(p), side(q));
        if fp >= 0.0 {
            out.push(p);
        }
        if (fp > 0.0 && fq < 0.0) || (fp < 0.0 && fq > 0.0) {
            let t = fp / (fp - fq);
            out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
        }
    }
    out
}

/// The intersection of two convex counter-clockwise polygons, itself convex
/// and counter-clockwise. Empty when they share no area; polygons that only
/// touch may yield a degenerate sliver of zero area.
pub fn intersection(subject: &[Vec2], clipper: &[Vec2]) -> Vec<Vec2> {
    let mut out = subject.to_vec();
    let n = clipper.len();
    for i in 0..n {
        if out.len() < 3 {
            return Vec::new();
        }
        out = clip_left(&out, clipper[i], clipper[(i + 1) % n]);
    }
    if out.len() < 3 { Vec::new() } else { out }
}

/// Area shared by two convex counter-clockwise polygons. Never negative.
pub fn intersection_area(a: &[Vec2], b: &[Vec2]) -> f64 {
    signed_area(&intersection(a, b)).max(0.0)
}

/// Area of `polygon` that lies outside the convex `container`.
pub fn outside_area(polygon: &[Vec2], container: &[Vec2]) -> f64 {
    (signed_area(polygon) - intersection_area(polygon, container)).max(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::polygon::{outside_depth, transform};
    use crate::testing::{close, convex_polygon, pose, pose_near};
    use proptest::prelude::*;

    const SQUARE: [Vec2; 4] = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]];

    fn shifted(polygon: &[Vec2], dx: f64, dy: f64) -> Vec<Vec2> {
        polygon.iter().map(|p| [p[0] + dx, p[1] + dy]).collect()
    }

    #[test]
    fn overlapping_squares_share_a_rectangle() {
        // Shifted by (1.5, 0.5): the shared part is 0.5 by 1.5.
        let other = shifted(&SQUARE, 1.5, 0.5);
        assert!(close(intersection_area(&SQUARE, &other), 0.75, 1e-12));
        assert!(close(outside_area(&other, &SQUARE), 4.0 - 0.75, 1e-12));
    }

    #[test]
    fn a_square_and_a_diamond_share_an_octagon() {
        // Diamond |x-1| + |y-1| <= 1.5 cuts four corner triangles of legs 0.5 off the square.
        let diamond = [[1.0, -0.5], [2.5, 1.0], [1.0, 2.5], [-0.5, 1.0]];
        let shared = intersection(&SQUARE, &diamond);
        assert_eq!(shared.len(), 8);
        assert!(close(signed_area(&shared), 4.0 - 4.0 * 0.125, 1e-12));
    }

    #[test]
    fn disjoint_and_touching_polygons_share_no_area() {
        assert_eq!(intersection_area(&SQUARE, &shifted(&SQUARE, 5.0, 0.0)), 0.0);
        assert!(intersection(&SQUARE, &shifted(&SQUARE, 5.0, 0.0)).is_empty());
        assert_eq!(intersection_area(&SQUARE, &shifted(&SQUARE, 2.0, 0.0)), 0.0);
        assert_eq!(intersection_area(&SQUARE, &shifted(&SQUARE, 2.0, 2.0)), 0.0);
    }

    #[test]
    fn a_polygon_inside_another_is_its_own_intersection() {
        let inner = [[0.5, 0.5], [1.5, 0.5], [1.0, 1.5]];
        assert!(close(intersection_area(&SQUARE, &inner), 0.5, 1e-12));
        assert!(close(intersection_area(&inner, &SQUARE), 0.5, 1e-12));
        assert_eq!(outside_area(&inner, &SQUARE), 0.0);
    }

    proptest! {
        #[test]
        fn a_polygon_meets_itself_in_itself(a in convex_polygon(), pa in pose()) {
            let a = transform(&a, &pa);
            prop_assert!(close(intersection_area(&a, &a), signed_area(&a), 1e-7));
            prop_assert!(outside_area(&a, &a) < 1e-7);
        }

        #[test]
        fn intersection_is_symmetric_and_no_larger_than_either(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let shared = intersection_area(&a, &b);
            prop_assert!(close(shared, intersection_area(&b, &a), 1e-7));
            prop_assert!(shared <= signed_area(&a).min(signed_area(&b)) + 1e-7);
            prop_assert!(shared >= 0.0);
        }

        #[test]
        fn the_intersection_lies_in_both_polygons(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let shared = intersection(&a, &b);
            prop_assume!(!shared.is_empty());
            prop_assert!(outside_depth(&shared, &a) < 1e-9);
            prop_assert!(outside_depth(&shared, &b) < 1e-9);
            // Convex and counter-clockwise, up to slivers too thin to have a strict turn.
            prop_assert!(signed_area(&shared) >= 0.0);
        }

        #[test]
        fn area_survives_a_common_rigid_motion(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near(), motion in pose()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let (c, d) = (transform(&a, &motion), transform(&b, &motion));
            prop_assert!(close(intersection_area(&a, &b), intersection_area(&c, &d), 1e-6));
        }

        #[test]
        fn inside_and_outside_parts_add_up(a in convex_polygon(), b in convex_polygon(), pa in pose_near(), pb in pose_near()) {
            let (a, b) = (transform(&a, &pa), transform(&b, &pb));
            let total = intersection_area(&a, &b) + outside_area(&a, &b);
            prop_assert!(close(total, signed_area(&a), 1e-7));
        }
    }
}
