//! Geometry shared by all solvers.
//!
//! Everything here is for convex polygons, in millimetres and radians, with
//! `f64` and explicit tolerances. Results are numerical evidence, not proofs.
//!
//! Solvers reuse these primitives; the solution validator on the Python side
//! deliberately does not, so that one bug cannot affect both search and checking.
//! The two are compared in `tests/corpus/test_native_agrees_with_validator.py`.
//!
//! | Module | Contents |
//! | --- | --- |
//! | [`polygon`] | validity, area, centroid, rigid motion, containment, outside depth |
//! | [`sat`] | separating-axis penetration depth |
//! | [`clip`] | intersection and its area |
//! | [`edges`] | edges and the signatures that decide which edges can mate |
//! | [`relief`] | roof heights of placed pieces and roof continuity along an edge |

pub mod clip;
pub mod edges;
pub mod polygon;
pub mod relief;
pub mod sat;

#[cfg(test)]
mod testing;

pub use clip::{intersection, intersection_area, outside_area};
pub use edges::{Edge, EdgeSignature, edge_signatures, edges};
pub use polygon::{
    ConvexPolygon, NotConvex, centroid, contains_point, distance_to_segment, is_convex_ccw,
    outside_depth, point_outside_depth, signed_area, transform,
};
pub use relief::{roof_height, seam_mismatch, tangential_gradient_mismatch, world_gradient};
pub use sat::penetration_depth;
