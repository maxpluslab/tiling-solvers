//! Proptest strategies and helpers shared by this crate's tests.

use std::f64::consts::{PI, TAU};

use proptest::prelude::*;
use tiling_core::{Pose, Roof, Vec2};

use crate::polygon::centroid;

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
