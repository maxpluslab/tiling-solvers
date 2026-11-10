//! Roof planes of placed pieces, and whether two roofs meet along an edge.
//!
//! Both roofs are affine, so along a straight segment their height difference
//! is affine too: it is largest at an end, and comparing the two ends bounds
//! the mismatch on the whole segment. Equivalently, two roofs that agree along
//! a segment with direction `v` satisfy `(g1 - g2) . v = 0`. The gradients
//! themselves need not be equal: a ridge or a valley is exactly where they
//! differ, across the edge.

use tiling_core::{Pose, Roof, Vec2};

/// Height of a placed piece's roof above a world point.
pub fn roof_height(roof: &Roof, pose: &Pose, world: Vec2) -> f64 {
    roof.height_at(pose.to_local(world))
}

/// The roof gradient of a placed piece in world coordinates: the local
/// gradient turned by the pose's angle.
pub fn world_gradient(roof: &Roof, pose: &Pose) -> Vec2 {
    let (s, c) = pose.theta.sin_cos();
    [c * roof.gx - s * roof.gy, s * roof.gx + c * roof.gy]
}

/// The largest height difference between two placed roofs along the world
/// segment `p0`–`p1`. Exact in form: the difference is affine along the
/// segment, so it peaks at one of the two ends.
pub fn seam_mismatch(
    roof_a: &Roof,
    pose_a: &Pose,
    roof_b: &Roof,
    pose_b: &Pose,
    p0: Vec2,
    p1: Vec2,
) -> f64 {
    let at = |p: Vec2| (roof_height(roof_a, pose_a, p) - roof_height(roof_b, pose_b, p)).abs();
    at(p0).max(at(p1))
}

/// `(g_a - g_b) . v` for the unit direction `v` of the world segment `p0`–`p1`:
/// how fast the two roofs drift apart along it, in mm per mm. Zero is necessary
/// for the roofs to agree along the segment, and it needs no polygon work, so
/// the search tests it first.
pub fn tangential_gradient_mismatch(
    roof_a: &Roof,
    pose_a: &Pose,
    roof_b: &Roof,
    pose_b: &Pose,
    p0: Vec2,
    p1: Vec2,
) -> f64 {
    let length = (p1[0] - p0[0]).hypot(p1[1] - p0[1]);
    let v = [(p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length];
    let ga = world_gradient(roof_a, pose_a);
    let gb = world_gradient(roof_b, pose_b);
    (ga[0] - gb[0]) * v[0] + (ga[1] - gb[1]) * v[1]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::{close, point, pose, roof};
    use proptest::prelude::*;
    use std::f64::consts::{FRAC_PI_2, PI};

    /// The local roof of a piece placed at `pose` whose top is the world plane
    /// `z = c + a x + b y`.
    fn roof_from_world_plane(c: f64, a: f64, b: f64, pose: &Pose) -> Roof {
        let (s, co) = pose.theta.sin_cos();
        Roof {
            z0: c + a * pose.x + b * pose.y,
            // The world gradient turned back by the pose's angle.
            gx: co * a + s * b,
            gy: -s * a + co * b,
        }
    }

    // The two strips of tests/support/documents.py: both 20 mm high at their
    // centres, rising towards the seam at x = 0 with slopes of 0.25.
    const LEFT: Roof = Roof {
        z0: 20.0,
        gx: 0.25,
        gy: 0.0,
    };
    const RIGHT: Roof = Roof {
        z0: 20.0,
        gx: -0.25,
        gy: 0.0,
    };
    const LEFT_POSE: Pose = Pose {
        x: -36.0,
        y: 0.0,
        theta: 0.0,
    };
    const RIGHT_POSE: Pose = Pose {
        x: 36.0,
        y: 0.0,
        theta: 0.0,
    };
    const SEAM: (Vec2, Vec2) = ([0.0, -72.0], [0.0, 72.0]);

    #[test]
    fn height_follows_the_piece() {
        // 20 + 0.25 * 36 at the seam, wherever along it.
        assert!(close(
            roof_height(&LEFT, &LEFT_POSE, [0.0, 17.0]),
            29.0,
            1e-12
        ));
        // Turned a quarter, the slope runs along world y instead.
        let turned = Pose {
            theta: FRAC_PI_2,
            ..LEFT_POSE
        };
        assert!(close(
            roof_height(&LEFT, &turned, [-36.0, 4.0]),
            21.0,
            1e-12
        ));
        let [gx, gy] = world_gradient(&LEFT, &turned);
        assert!(close(gx, 0.0, 1e-12) && close(gy, 0.25, 1e-12));
    }

    #[test]
    fn a_ridge_is_continuous_though_the_gradients_differ() {
        let mismatch = seam_mismatch(&LEFT, &LEFT_POSE, &RIGHT, &RIGHT_POSE, SEAM.0, SEAM.1);
        assert!(close(mismatch, 0.0, 1e-12));
        let drift =
            tangential_gradient_mismatch(&LEFT, &LEFT_POSE, &RIGHT, &RIGHT_POSE, SEAM.0, SEAM.1);
        assert!(close(drift, 0.0, 1e-12));
        assert_ne!(
            world_gradient(&LEFT, &LEFT_POSE),
            world_gradient(&RIGHT, &RIGHT_POSE)
        );
    }

    #[test]
    fn a_half_turned_strip_steps_by_eighteen() {
        // As in tests/unit/test_validation.py: 20 - 9 = 11 against 29.
        let turned = Pose {
            theta: PI,
            ..RIGHT_POSE
        };
        let mismatch = seam_mismatch(&LEFT, &LEFT_POSE, &RIGHT, &turned, SEAM.0, SEAM.1);
        assert!(close(mismatch, 18.0, 1e-9));
        // The step is constant along the seam, so the tangential test alone cannot see it.
        let drift =
            tangential_gradient_mismatch(&LEFT, &LEFT_POSE, &RIGHT, &turned, SEAM.0, SEAM.1);
        assert!(close(drift, 0.0, 1e-12));
    }

    #[test]
    fn a_tilt_along_the_seam_shows_at_its_ends_and_in_the_gradient_test() {
        // 0.01 mm per mm along the seam: nothing at the middle, 0.72 mm at either end.
        let tilted = Roof { gy: 0.01, ..RIGHT };
        let mismatch = seam_mismatch(&LEFT, &LEFT_POSE, &tilted, &RIGHT_POSE, SEAM.0, SEAM.1);
        assert!(close(mismatch, 0.72, 1e-12));
        let drift =
            tangential_gradient_mismatch(&LEFT, &LEFT_POSE, &tilted, &RIGHT_POSE, SEAM.0, SEAM.1);
        assert!(close(drift, -0.01, 1e-12));
    }

    proptest! {
        #[test]
        fn pieces_cut_from_one_plane_agree_everywhere(
            c in 5.0f64..50.0, a in -1.0f64..1.0, b in -1.0f64..1.0,
            pose_a in pose(), pose_b in pose(), p0 in point(), p1 in point(),
        ) {
            prop_assume!((p1[0] - p0[0]).hypot(p1[1] - p0[1]) > 1e-3);
            let roof_a = roof_from_world_plane(c, a, b, &pose_a);
            let roof_b = roof_from_world_plane(c, a, b, &pose_b);
            prop_assert!(close(roof_height(&roof_a, &pose_a, p0), c + a * p0[0] + b * p0[1], 1e-9));
            prop_assert!(seam_mismatch(&roof_a, &pose_a, &roof_b, &pose_b, p0, p1) < 1e-9);
            prop_assert!(tangential_gradient_mismatch(&roof_a, &pose_a, &roof_b, &pose_b, p0, p1).abs() < 1e-9);
        }

        #[test]
        fn the_ends_bound_the_mismatch_along_the_segment(
            roof_a in roof(), roof_b in roof(), pose_a in pose(), pose_b in pose(),
            p0 in point(), p1 in point(), t in 0.0f64..1.0,
        ) {
            let within = [p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])];
            let here = (roof_height(&roof_a, &pose_a, within) - roof_height(&roof_b, &pose_b, within)).abs();
            prop_assert!(here <= seam_mismatch(&roof_a, &pose_a, &roof_b, &pose_b, p0, p1) + 1e-9);
        }

        #[test]
        fn the_gradient_test_is_the_change_in_mismatch_per_millimetre(
            roof_a in roof(), roof_b in roof(), pose_a in pose(), pose_b in pose(),
            p0 in point(), p1 in point(),
        ) {
            let length = (p1[0] - p0[0]).hypot(p1[1] - p0[1]);
            prop_assume!(length > 1e-3);
            let gap = |p: Vec2| roof_height(&roof_a, &pose_a, p) - roof_height(&roof_b, &pose_b, p);
            let drift = tangential_gradient_mismatch(&roof_a, &pose_a, &roof_b, &pose_b, p0, p1);
            prop_assert!(close(gap(p1) - gap(p0), drift * length, 1e-7));
        }

        #[test]
        fn ridges_pass_the_gradient_test(
            c in 5.0f64..50.0, a in -1.0f64..1.0, b in -1.0f64..1.0, kink in -1.0f64..1.0,
            pose_a in pose(), pose_b in pose(), p0 in point(), p1 in point(),
        ) {
            // Add to one side a plane that vanishes on the line through p0 and p1.
            let length = (p1[0] - p0[0]).hypot(p1[1] - p0[1]);
            prop_assume!(length > 1e-3);
            let normal = [(p1[1] - p0[1]) / length, -(p1[0] - p0[0]) / length];
            let (a2, b2) = (a + kink * normal[0], b + kink * normal[1]);
            let c2 = c - kink * (normal[0] * p0[0] + normal[1] * p0[1]);
            let roof_a = roof_from_world_plane(c, a, b, &pose_a);
            let roof_b = roof_from_world_plane(c2, a2, b2, &pose_b);
            prop_assert!(seam_mismatch(&roof_a, &pose_a, &roof_b, &pose_b, p0, p1) < 1e-7);
            prop_assert!(tangential_gradient_mismatch(&roof_a, &pose_a, &roof_b, &pose_b, p0, p1).abs() < 1e-9);
        }
    }
}
