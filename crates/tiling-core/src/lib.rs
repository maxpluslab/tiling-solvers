//! Shared domain types for the tiling solvers.
//!
//! Units are millimetres and radians. Polygons are convex and counter-clockwise.

mod instance;

pub use instance::{
    InstanceError, Piece, PuzzleInstance, Regime, Roof, TolerancePolicy, ValidationConstants,
};

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

    /// Map a point from world to piece-local coordinates: the inverse of [`Pose::apply`].
    pub fn to_local(&self, p: Vec2) -> Vec2 {
        let (s, c) = self.theta.sin_cos();
        let (dx, dy) = (p[0] - self.x, p[1] - self.y);
        [c * dx + s * dy, -s * dx + c * dy]
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

    #[test]
    fn to_local_undoes_a_quarter_turn() {
        let pose = Pose {
            x: 10.0,
            y: 20.0,
            theta: std::f64::consts::FRAC_PI_2,
        };
        let [u, v] = pose.to_local([10.0, 21.0]);
        assert!((u - 1.0).abs() < 1e-12);
        assert!(v.abs() < 1e-12);
    }
}

#[cfg(test)]
mod properties {
    use super::*;
    use proptest::prelude::*;

    const TOL: f64 = 1e-9;

    fn pose() -> impl Strategy<Value = Pose> {
        (-200.0..200.0, -200.0..200.0, -10.0..10.0).prop_map(|(x, y, theta)| Pose { x, y, theta })
    }

    fn point() -> impl Strategy<Value = Vec2> {
        (-200.0..200.0, -200.0..200.0).prop_map(|(x, y)| [x, y])
    }

    fn distance(a: Vec2, b: Vec2) -> f64 {
        (a[0] - b[0]).hypot(a[1] - b[1])
    }

    proptest! {
        #[test]
        fn a_pose_preserves_distances(pose in pose(), a in point(), b in point()) {
            let moved = distance(pose.apply(a), pose.apply(b));
            prop_assert!((moved - distance(a, b)).abs() < TOL);
        }

        #[test]
        fn to_local_inverts_apply(pose in pose(), p in point()) {
            prop_assert!(distance(pose.to_local(pose.apply(p)), p) < TOL);
            prop_assert!(distance(pose.apply(pose.to_local(p)), p) < TOL);
        }

        #[test]
        fn a_pose_preserves_orientation(pose in pose(), a in point(), b in point(), c in point()) {
            // Signed area of a triangle is unchanged: rotations do not mirror.
            let area = |p: Vec2, q: Vec2, r: Vec2| {
                ((q[0] - p[0]) * (r[1] - p[1]) - (r[0] - p[0]) * (q[1] - p[1])) / 2.0
            };
            let before = area(a, b, c);
            let after = area(pose.apply(a), pose.apply(b), pose.apply(c));
            prop_assert!((before - after).abs() < 1e-6);
        }

        #[test]
        fn a_full_turn_changes_nothing(pose in pose(), p in point()) {
            let turned = Pose { theta: pose.theta + std::f64::consts::TAU, ..pose };
            prop_assert!(distance(turned.apply(p), pose.apply(p)) < TOL);
        }

        #[test]
        fn the_local_origin_lands_on_the_translation(pose in pose()) {
            prop_assert!(distance(pose.apply([0.0, 0.0]), [pose.x, pose.y]) < TOL);
        }
    }
}
