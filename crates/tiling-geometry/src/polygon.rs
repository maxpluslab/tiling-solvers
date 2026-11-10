//! Convex polygons: validity, area, centroid, rigid motion, containment.
//!
//! The primitives take `&[Vec2]` so that the search can call them on scratch
//! buffers without allocating. [`ConvexPolygon`] is the checked form: holding
//! one means the vertices are strictly convex and counter-clockwise.

use std::ops::Deref;

use tiling_core::{Pose, Vec2};

/// A turn whose sine is below this is treated as no turn at all.
pub const MIN_TURN_SINE: f64 = 1e-9;
/// Edges shorter than this, in millimetres, are degenerate.
pub const MIN_EDGE_MM: f64 = 1e-9;
/// How far a full circuit of turns may differ from a full turn, in radians.
pub const WINDING_TOL: f64 = 1e-6;

/// Signed area of a simple polygon by the shoelace formula: positive when the
/// vertices run counter-clockwise. Fewer than three vertices give zero.
pub fn signed_area(polygon: &[Vec2]) -> f64 {
    let n = polygon.len();
    if n < 3 {
        return 0.0;
    }
    let mut twice = 0.0;
    for i in 0..n {
        let [x0, y0] = polygon[i];
        let [x1, y1] = polygon[(i + 1) % n];
        twice += x0 * y1 - x1 * y0;
    }
    twice / 2.0
}

/// Area centroid of a simple polygon with non-zero area.
pub fn centroid(polygon: &[Vec2]) -> Vec2 {
    let n = polygon.len();
    let (mut twice, mut cx, mut cy) = (0.0, 0.0, 0.0);
    for i in 0..n {
        let [x0, y0] = polygon[i];
        let [x1, y1] = polygon[(i + 1) % n];
        let cross = x0 * y1 - x1 * y0;
        twice += cross;
        cx += (x0 + x1) * cross;
        cy += (y0 + y1) * cross;
    }
    [cx / (3.0 * twice), cy / (3.0 * twice)]
}

/// Place a local polygon in the world: rotate by the pose's angle, then translate.
pub fn transform(polygon: &[Vec2], pose: &Pose) -> Vec<Vec2> {
    let (s, c) = pose.theta.sin_cos();
    polygon
        .iter()
        .map(|&[u, v]| [pose.x + c * u - s * v, pose.y + s * u + c * v])
        .collect()
}

/// Whether the vertices form a strictly convex counter-clockwise polygon:
/// every corner turns left, and the turns add up to one circuit, which
/// excludes star polygons whose corners all turn left.
pub fn is_convex_ccw(polygon: &[Vec2]) -> bool {
    let n = polygon.len();
    if n < 3
        || polygon
            .iter()
            .any(|p| !(p[0].is_finite() && p[1].is_finite()))
    {
        return false;
    }
    let mut turning = 0.0;
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let c = polygon[(i + 2) % n];
        let (ex, ey) = (b[0] - a[0], b[1] - a[1]);
        let (fx, fy) = (c[0] - b[0], c[1] - b[1]);
        let (le, lf) = (ex.hypot(ey), fx.hypot(fy));
        if le < MIN_EDGE_MM || lf < MIN_EDGE_MM {
            return false;
        }
        let cross = ex * fy - ey * fx;
        if cross <= MIN_TURN_SINE * le * lf {
            return false;
        }
        turning += cross.atan2(ex * fx + ey * fy);
    }
    (turning - std::f64::consts::TAU).abs() <= WINDING_TOL
}

/// Distance from a point to the segment `a`–`b`.
pub fn distance_to_segment(p: Vec2, a: Vec2, b: Vec2) -> f64 {
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    let length_squared = dx * dx + dy * dy;
    let t = if length_squared > 0.0 {
        (((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_squared).clamp(0.0, 1.0)
    } else {
        0.0
    };
    (p[0] - (a[0] + t * dx)).hypot(p[1] - (a[1] + t * dy))
}

/// Whether a point lies in a convex counter-clockwise polygon, boundary included.
pub fn contains_point(polygon: &[Vec2], p: Vec2) -> bool {
    let n = polygon.len();
    (0..n).all(|i| {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0.0
    })
}

/// How far a point lies outside a convex counter-clockwise polygon: its
/// Euclidean distance to the polygon, zero inside or on the boundary.
pub fn point_outside_depth(p: Vec2, container: &[Vec2]) -> f64 {
    if contains_point(container, p) {
        return 0.0;
    }
    let n = container.len();
    (0..n)
        .map(|i| distance_to_segment(p, container[i], container[(i + 1) % n]))
        .fold(f64::INFINITY, f64::min)
}

/// The largest distance by which any vertex of `polygon` lies outside the
/// convex `container`. Zero when the polygon is inside, since both are convex.
pub fn outside_depth(polygon: &[Vec2], container: &[Vec2]) -> f64 {
    polygon
        .iter()
        .map(|&p| point_outside_depth(p, container))
        .fold(0.0, f64::max)
}

/// The vertices given to [`ConvexPolygon::new`] were not strictly convex and
/// counter-clockwise.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NotConvex;

impl std::fmt::Display for NotConvex {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "the vertices are not a strictly convex counter-clockwise polygon"
        )
    }
}

impl std::error::Error for NotConvex {}

/// A strictly convex counter-clockwise polygon. It dereferences to its
/// vertices, so every primitive that takes `&[Vec2]` accepts it.
#[derive(Debug, Clone, PartialEq)]
pub struct ConvexPolygon(Vec<Vec2>);

impl ConvexPolygon {
    pub fn new(vertices: Vec<Vec2>) -> Result<ConvexPolygon, NotConvex> {
        if is_convex_ccw(&vertices) {
            Ok(ConvexPolygon(vertices))
        } else {
            Err(NotConvex)
        }
    }

    pub fn vertices(&self) -> &[Vec2] {
        &self.0
    }

    pub fn into_vertices(self) -> Vec<Vec2> {
        self.0
    }

    pub fn area(&self) -> f64 {
        signed_area(&self.0)
    }

    pub fn centroid(&self) -> Vec2 {
        centroid(&self.0)
    }

    /// The polygon moved by a pose. A rigid motion keeps it convex and
    /// counter-clockwise, so the result needs no second check.
    pub fn transformed(&self, pose: &Pose) -> ConvexPolygon {
        ConvexPolygon(transform(&self.0, pose))
    }
}

impl Deref for ConvexPolygon {
    type Target = [Vec2];

    fn deref(&self) -> &[Vec2] {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::{close, convex_polygon, pose};
    use proptest::prelude::*;
    use std::f64::consts::{FRAC_PI_2, PI};

    const SQUARE: [Vec2; 4] = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]];

    #[test]
    fn ccw_is_positive_and_cw_is_negative() {
        assert_eq!(signed_area(&SQUARE), 4.0);
        let mut cw = SQUARE;
        cw.reverse();
        assert_eq!(signed_area(&cw), -4.0);
    }

    #[test]
    fn degenerate_polygons_have_zero_area() {
        assert_eq!(signed_area(&[]), 0.0);
        assert_eq!(signed_area(&SQUARE[..2]), 0.0);
    }

    #[test]
    fn centroid_of_a_right_triangle_is_a_third_along_each_leg() {
        let [x, y] = centroid(&[[0.0, 0.0], [6.0, 0.0], [0.0, 3.0]]);
        assert!(close(x, 2.0, 1e-12) && close(y, 1.0, 1e-12));
    }

    #[test]
    fn transform_turns_then_shifts() {
        let pose = Pose {
            x: 10.0,
            y: 20.0,
            theta: FRAC_PI_2,
        };
        let moved = transform(&[[1.0, 0.0], [0.0, 1.0]], &pose);
        assert!(close(moved[0][0], 10.0, 1e-12) && close(moved[0][1], 21.0, 1e-12));
        assert!(close(moved[1][0], 9.0, 1e-12) && close(moved[1][1], 20.0, 1e-12));
    }

    #[test]
    fn convexity_accepts_and_refuses_the_same_shapes_as_the_python_models() {
        // The rows of tests/unit/test_models.py::test_a_piece_refuses_a_bad_polygon.
        assert!(is_convex_ccw(&SQUARE));
        let mut clockwise = SQUARE;
        clockwise.reverse();
        assert!(!is_convex_ccw(&clockwise));
        assert!(!is_convex_ccw(&SQUARE[..2]));
        let reflex = [
            [-3.0, -3.0],
            [3.0, -3.0],
            [0.0, -1.0],
            [3.0, 3.0],
            [-3.0, 3.0],
        ];
        assert!(!is_convex_ccw(&reflex));
        let collinear = [
            [-1.0, -1.0],
            [0.0, -1.0],
            [1.0, -1.0],
            [1.0, 1.0],
            [-1.0, 1.0],
        ];
        assert!(!is_convex_ccw(&collinear));
        let repeated = [
            [-1.0, -1.0],
            [1.0, -1.0],
            [1.0, -1.0],
            [1.0, 1.0],
            [-1.0, 1.0],
        ];
        assert!(!is_convex_ccw(&repeated));
        assert!(!is_convex_ccw(&[[0.0, 0.0], [1.0, 0.0], [f64::NAN, 1.0]]));
        // A pentagram turns left at every vertex but goes round twice.
        let pentagram: Vec<Vec2> = (0..5)
            .map(|k| {
                let angle = 2.0 * PI * f64::from(k) * 2.0 / 5.0;
                [angle.cos(), angle.sin()]
            })
            .collect();
        assert!(!is_convex_ccw(&pentagram));
    }

    #[test]
    fn distance_to_a_segment_uses_the_nearest_end_beyond_it() {
        let (a, b) = ([0.0, 0.0], [10.0, 0.0]);
        assert!(close(distance_to_segment([5.0, 3.0], a, b), 3.0, 1e-12));
        assert!(close(distance_to_segment([13.0, 4.0], a, b), 5.0, 1e-12));
        assert!(close(distance_to_segment([-3.0, -4.0], a, b), 5.0, 1e-12));
        assert!(close(distance_to_segment([3.0, 4.0], a, a), 5.0, 1e-12));
    }

    #[test]
    fn containment_includes_the_boundary() {
        assert!(contains_point(&SQUARE, [1.0, 1.0]));
        assert!(contains_point(&SQUARE, [2.0, 1.0]));
        assert!(contains_point(&SQUARE, [0.0, 0.0]));
        assert!(!contains_point(&SQUARE, [2.0 + 1e-9, 1.0]));
    }

    #[test]
    fn outside_depth_is_euclidean_beyond_a_corner() {
        // 3 right and 4 up from the corner: 5 away. The largest distance past one wall is 4.
        assert!(close(point_outside_depth([5.0, 6.0], &SQUARE), 5.0, 1e-12));
        assert!(close(point_outside_depth([5.0, 1.0], &SQUARE), 3.0, 1e-12));
        assert_eq!(point_outside_depth([1.0, 1.0], &SQUARE), 0.0);
        assert_eq!(point_outside_depth([2.0, 2.0], &SQUARE), 0.0);
    }

    #[test]
    fn outside_depth_of_a_polygon_is_that_of_its_worst_vertex() {
        let shifted: Vec<Vec2> = SQUARE.iter().map(|p| [p[0] + 0.5, p[1]]).collect();
        assert!(close(outside_depth(&shifted, &SQUARE), 0.5, 1e-12));
        assert_eq!(outside_depth(&SQUARE, &SQUARE), 0.0);
    }

    #[test]
    fn a_convex_polygon_is_checked_on_construction() {
        let polygon = ConvexPolygon::new(SQUARE.to_vec()).unwrap();
        assert_eq!(polygon.vertices(), &SQUARE);
        assert_eq!(polygon.area(), 4.0);
        assert_eq!(polygon.len(), 4);
        let mut clockwise = SQUARE.to_vec();
        clockwise.reverse();
        assert_eq!(ConvexPolygon::new(clockwise), Err(NotConvex));
    }

    proptest! {
        #[test]
        fn generated_polygons_are_convex_and_centred(polygon in convex_polygon()) {
            prop_assert!(is_convex_ccw(&polygon));
            prop_assert!(signed_area(&polygon) > 0.0);
            let [cx, cy] = centroid(&polygon);
            prop_assert!(cx.hypot(cy) < 1e-9);
            let mut reversed = polygon.clone();
            reversed.reverse();
            prop_assert!(!is_convex_ccw(&reversed));
        }

        #[test]
        fn a_pose_moves_a_polygon_rigidly(polygon in convex_polygon(), pose in pose()) {
            let moved = transform(&polygon, &pose);
            prop_assert!(is_convex_ccw(&moved));
            prop_assert!(close(signed_area(&moved), signed_area(&polygon), 1e-6));
            // The polygon is centred, so its centroid lands on the translation.
            let [cx, cy] = centroid(&moved);
            prop_assert!((cx - pose.x).hypot(cy - pose.y) < 1e-9);
            for (p, q) in polygon.iter().zip(&moved) {
                prop_assert!((pose.apply(*p)[0] - q[0]).abs() < 1e-12);
                prop_assert!((pose.apply(*p)[1] - q[1]).abs() < 1e-12);
            }
        }

        #[test]
        fn a_polygon_contains_its_centroid_and_its_edge_midpoints(polygon in convex_polygon(), pose in pose()) {
            let moved = transform(&polygon, &pose);
            prop_assert!(contains_point(&moved, [pose.x, pose.y]));
            prop_assert_eq!(point_outside_depth([pose.x, pose.y], &moved), 0.0);
            // Its own vertices are on the boundary: at most rounding outside.
            prop_assert!(outside_depth(&moved, &moved) < 1e-9);
        }

        #[test]
        fn outside_depth_follows_a_shift_along_an_edge_normal(polygon in convex_polygon(), d in 0.01f64..50.0, pick in 0usize..8) {
            // Push the midpoint of an edge straight out by d: it is then exactly d outside.
            let n = polygon.len();
            let a = polygon[pick % n];
            let b = polygon[(pick + 1) % n];
            let length = (b[0] - a[0]).hypot(b[1] - a[1]);
            let normal = [(b[1] - a[1]) / length, -(b[0] - a[0]) / length];
            let p = [(a[0] + b[0]) / 2.0 + d * normal[0], (a[1] + b[1]) / 2.0 + d * normal[1]];
            prop_assert!(close(point_outside_depth(p, &polygon), d, 1e-9));
            prop_assert!(!contains_point(&polygon, p));
        }
    }
}
