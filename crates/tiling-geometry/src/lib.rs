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
//! | [`contact`] | corners of the uncovered region, and the pose that fills one |
//! | [`graph`] | which edges may mate, which pieces are interchangeable |
//! | [`cavity`] | the separate parts of the uncovered region, their areas and widths |
//! | [`conflict`] | which of a finite set of placements exclude one another |
//! | [`assembly`] | reversible partial assembly: `frontier`, `propose`, `check_placement` |

pub mod assembly;
pub mod cavity;
pub mod clip;
pub mod conflict;
pub mod contact;
pub mod edges;
pub mod graph;
pub mod polygon;
pub mod relief;
pub mod sat;

#[cfg(any(test, feature = "testing"))]
pub mod testing;

pub use assembly::{Assembly, AssemblyError, CandidatePlacement, CandidateStats, PlacementCheck};
pub use cavity::{Cavity, cavities, least_width};
pub use clip::{intersection, intersection_area, outside_area};
pub use conflict::{Conflict, Conflicts, Placed, conflict, conflicts};
pub use contact::{ContactTolerance, Corner, EdgeRef, free_corners, pose_at_corner};
pub use edges::{Edge, EdgeSignature, edge_signatures, edges};
pub use graph::{EdgeGraph, Meeting, Shape, rotation_order};
pub use polygon::{
    ConvexPolygon, NotConvex, centroid, contains_point, distance_to_segment, is_convex_ccw,
    outside_depth, point_outside_depth, signed_area, transform,
};
pub use relief::{
    roof_height, seam_mismatch, seam_step, tangential_gradient_mismatch, world_gradient,
};
pub use sat::penetration_depth;
