//! Geometry shared by all solvers.
//!
//! Solvers reuse these primitives; the solution validator on the Python side
//! deliberately does not, so that one bug cannot affect both search and checking.

use tiling_core::Vec2;

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

#[cfg(test)]
mod tests {
    use super::*;
    use tiling_core::Pose;

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
    fn area_is_invariant_under_a_pose() {
        let pose = Pose {
            x: -31.0,
            y: 7.5,
            theta: 1.234,
        };
        let moved: Vec<Vec2> = SQUARE.iter().map(|&p| pose.apply(p)).collect();
        assert!((signed_area(&moved) - 4.0).abs() < 1e-9);
    }
}
