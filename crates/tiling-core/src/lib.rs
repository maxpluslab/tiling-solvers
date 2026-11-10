//! Shared domain types for the tiling solvers.
//!
//! Units are millimetres and radians. Polygons are convex and counter-clockwise.

/// Version of the Rust workspace, as reported to Python.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// A point or vector in the plane, in millimetres.
pub type Vec2 = [f64; 2];

/// Rigid placement of a piece: rotate its local polygon counter-clockwise by
/// `theta` radians about the local origin, then translate by `(x, y)`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Pose {
    pub x: f64,
    pub y: f64,
    pub theta: f64,
}

impl Pose {
    pub const IDENTITY: Pose = Pose {
        x: 0.0,
        y: 0.0,
        theta: 0.0,
    };

    /// Map a point from piece-local to world coordinates.
    pub fn apply(&self, p: Vec2) -> Vec2 {
        let (s, c) = self.theta.sin_cos();
        [self.x + c * p[0] - s * p[1], self.y + s * p[0] + c * p[1]]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quarter_turn_then_translate() {
        let pose = Pose {
            x: 10.0,
            y: 20.0,
            theta: std::f64::consts::FRAC_PI_2,
        };
        let [x, y] = pose.apply([1.0, 0.0]);
        assert!((x - 10.0).abs() < 1e-12);
        assert!((y - 21.0).abs() < 1e-12);
    }
}
