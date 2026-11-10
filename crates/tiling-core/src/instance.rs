//! The puzzle instance as a solver receives it.
//!
//! These types mirror `python/maxplus_solvers/models.py`, whose JSON form is
//! `schemas/instance-v1.json`. Python owns parsing and the geometric checks on
//! polygons; an instance arrives here already validated, and [`PuzzleInstance::check`]
//! repeats only the structural rules that a Rust caller could break.
//!
//! There is no field for reference poses, and none for construction data: the
//! tropical-aware regime is named so that results can be labelled, but its extra
//! data stays in Python until a Rust solver needs it. Rules are not represented
//! either, because format version 1 has a single rule set: translation and
//! continuous rotation, no flipping.

use std::collections::HashSet;
use std::fmt;

use crate::Vec2;

/// How much a solver is told. Results from different regimes are not comparable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Regime {
    /// Polygons only.
    Footprint,
    /// Polygons and roof planes.
    Relief,
    /// Construction data as well.
    TropicalAware,
}

impl Regime {
    /// The name used in instance files and results.
    pub fn as_str(self) -> &'static str {
        match self {
            Regime::Footprint => "footprint",
            Regime::Relief => "relief",
            Regime::TropicalAware => "tropical-aware",
        }
    }

    pub fn parse(name: &str) -> Option<Regime> {
        match name {
            "footprint" => Some(Regime::Footprint),
            "relief" => Some(Regime::Relief),
            "tropical-aware" => Some(Regime::TropicalAware),
            _ => None,
        }
    }

    /// Whether pieces carry roofs in this regime.
    pub fn has_roofs(self) -> bool {
        self != Regime::Footprint
    }
}

/// The top plane `z = z0 + gx*u + gy*v` in piece-local coordinates, in
/// millimetres above the underside.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Roof {
    pub z0: f64,
    pub gx: f64,
    pub gy: f64,
}

impl Roof {
    pub fn height_at(&self, local: Vec2) -> f64 {
        self.z0 + self.gx * local[0] + self.gy * local[1]
    }
}

/// A convex piece: counter-clockwise polygon in local coordinates about its
/// area centroid. The id is opaque.
#[derive(Debug, Clone, PartialEq)]
pub struct Piece {
    pub id: String,
    pub polygon: Vec<Vec2>,
    pub roof: Option<Roof>,
}

/// The source puzzle's scale-relative tolerances, as published: lengths as
/// fractions of the span, the area error as a fraction of the target area, the
/// roof mismatch as a fraction of the relief height.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ValidationConstants {
    pub contact_noise: f64,
    pub overlap_depth: f64,
    pub outside_depth: f64,
    pub area_error: f64,
    pub edge_angle_deg: f64,
    pub edge_min_overlap: f64,
    pub roof_mismatch: Option<f64>,
}

/// Absolute tolerances for one solve, in mm, mm² and radians.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TolerancePolicy {
    pub contact_noise_mm: f64,
    pub overlap_depth_mm: f64,
    pub outside_depth_mm: f64,
    pub area_error_mm2: f64,
    pub edge_angle_rad: f64,
    pub edge_min_overlap_mm: f64,
    pub roof_mismatch_mm: Option<f64>,
}

impl TolerancePolicy {
    /// Scale the published constants: lengths by the span, the area error by the
    /// target area, the roof mismatch by the relief height. The target area is a
    /// parameter because this crate has no geometry.
    pub fn from_constants(
        constants: &ValidationConstants,
        span_mm: f64,
        target_area_mm2: f64,
        relief_mm: Option<f64>,
    ) -> TolerancePolicy {
        TolerancePolicy {
            contact_noise_mm: constants.contact_noise * span_mm,
            overlap_depth_mm: constants.overlap_depth * span_mm,
            outside_depth_mm: constants.outside_depth * span_mm,
            area_error_mm2: constants.area_error * target_area_mm2,
            edge_angle_rad: constants.edge_angle_deg.to_radians(),
            edge_min_overlap_mm: constants.edge_min_overlap * span_mm,
            roof_mismatch_mm: match (constants.roof_mismatch, relief_mm) {
                (Some(fraction), Some(relief)) => Some(fraction * relief),
                _ => None,
            },
        }
    }
}

/// A puzzle as a solver sees it. It carries no answer.
#[derive(Debug, Clone, PartialEq)]
pub struct PuzzleInstance {
    pub id: String,
    pub regime: Regime,
    pub target: Vec<Vec2>,
    pub pieces: Vec<Piece>,
    pub span_mm: f64,
    pub relief_mm: Option<f64>,
    pub validation: ValidationConstants,
}

/// A structural rule an instance breaks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InstanceError {
    NoPieces,
    TooFewVertices { piece: Option<String> },
    DuplicateId(String),
    RoofMismatchesRegime { piece: String },
    ReliefDataMismatchesRegime,
}

impl fmt::Display for InstanceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            InstanceError::NoPieces => write!(f, "the instance has no pieces"),
            InstanceError::TooFewVertices { piece: None } => {
                write!(f, "the target has fewer than 3 vertices")
            }
            InstanceError::TooFewVertices { piece: Some(id) } => {
                write!(f, "piece {id} has fewer than 3 vertices")
            }
            InstanceError::DuplicateId(id) => write!(f, "piece id {id} is used twice"),
            InstanceError::RoofMismatchesRegime { piece } => {
                write!(f, "piece {piece} has a roof exactly when it should not")
            }
            InstanceError::ReliefDataMismatchesRegime => {
                write!(
                    f,
                    "relief height and roof tolerance must be present exactly in the roofed regimes"
                )
            }
        }
    }
}

impl std::error::Error for InstanceError {}

impl PuzzleInstance {
    /// The structural rules of `schemas/instance-v1.json`: there are pieces, ids
    /// are unique, and roofs and relief data are present exactly when the regime
    /// has roofs. Convexity, orientation and centring are checked in Python.
    pub fn check(&self) -> Result<(), InstanceError> {
        if self.target.len() < 3 {
            return Err(InstanceError::TooFewVertices { piece: None });
        }
        if self.pieces.is_empty() {
            return Err(InstanceError::NoPieces);
        }
        let roofed = self.regime.has_roofs();
        let mut seen = HashSet::new();
        for piece in &self.pieces {
            if piece.polygon.len() < 3 {
                return Err(InstanceError::TooFewVertices {
                    piece: Some(piece.id.clone()),
                });
            }
            if !seen.insert(piece.id.as_str()) {
                return Err(InstanceError::DuplicateId(piece.id.clone()));
            }
            if piece.roof.is_some() != roofed {
                return Err(InstanceError::RoofMismatchesRegime {
                    piece: piece.id.clone(),
                });
            }
        }
        if self.relief_mm.is_some() != roofed || self.validation.roof_mismatch.is_some() != roofed {
            return Err(InstanceError::ReliefDataMismatchesRegime);
        }
        Ok(())
    }

    /// The browser player's tolerances for this instance.
    pub fn tolerances(&self, target_area_mm2: f64) -> TolerancePolicy {
        TolerancePolicy::from_constants(
            &self.validation,
            self.span_mm,
            target_area_mm2,
            self.relief_mm,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const STRIP: [Vec2; 4] = [[-36.0, -72.0], [36.0, -72.0], [36.0, 72.0], [-36.0, 72.0]];

    /// The same two-strip puzzle as `tests/support/documents.py`.
    fn relief() -> PuzzleInstance {
        let piece = |id: &str, gx: f64| Piece {
            id: id.to_string(),
            polygon: STRIP.to_vec(),
            roof: Some(Roof {
                z0: 20.0,
                gx,
                gy: 0.0,
            }),
        };
        PuzzleInstance {
            id: "strips".to_string(),
            regime: Regime::Relief,
            target: vec![[-72.0, -72.0], [72.0, -72.0], [72.0, 72.0], [-72.0, 72.0]],
            pieces: vec![piece("p00", 0.25), piece("p01", -0.25)],
            span_mm: 144.0,
            relief_mm: Some(35.0),
            validation: ValidationConstants {
                contact_noise: 1e-6,
                overlap_depth: 0.006,
                outside_depth: 0.006,
                area_error: 0.012,
                edge_angle_deg: 3.0,
                edge_min_overlap: 0.02,
                roof_mismatch: Some(0.05),
            },
        }
    }

    fn footprint() -> PuzzleInstance {
        let mut instance = relief();
        instance.regime = Regime::Footprint;
        instance.relief_mm = None;
        instance.validation.roof_mismatch = None;
        for piece in &mut instance.pieces {
            piece.roof = None;
        }
        instance
    }

    #[test]
    fn regime_names_round_trip_and_match_the_schema() {
        for (regime, name) in [
            (Regime::Footprint, "footprint"),
            (Regime::Relief, "relief"),
            (Regime::TropicalAware, "tropical-aware"),
        ] {
            assert_eq!(regime.as_str(), name);
            assert_eq!(Regime::parse(name), Some(regime));
        }
        assert_eq!(Regime::parse("flat"), None);
        assert!(!Regime::Footprint.has_roofs());
        assert!(Regime::Relief.has_roofs() && Regime::TropicalAware.has_roofs());
    }

    #[test]
    fn roof_is_a_plane_in_local_coordinates() {
        let roof = Roof {
            z0: 5.0,
            gx: 0.5,
            gy: -0.25,
        };
        // 5 + 0.5*2 - 0.25*4
        assert!((roof.height_at([2.0, 4.0]) - 5.0).abs() < 1e-12);
    }

    #[test]
    fn tolerances_match_the_published_rev2_values() {
        // The same numbers as tests/unit/test_models.py, from the source's puzzle-rules.md.
        let policy = relief().tolerances(144.0 * 144.0);
        assert!((policy.overlap_depth_mm - 0.864).abs() < 1e-12);
        assert!((policy.outside_depth_mm - 0.864).abs() < 1e-12);
        assert!((policy.area_error_mm2 - 248.832).abs() < 1e-9);
        assert!((policy.roof_mismatch_mm.unwrap() - 1.75).abs() < 1e-12);
        assert!((policy.contact_noise_mm - 1.44e-4).abs() < 1e-15);
        assert!((policy.edge_min_overlap_mm - 2.88).abs() < 1e-12);
        assert!((policy.edge_angle_rad - std::f64::consts::PI / 60.0).abs() < 1e-15);
    }

    #[test]
    fn a_footprint_puzzle_has_no_roof_tolerance() {
        assert_eq!(footprint().tolerances(144.0 * 144.0).roof_mismatch_mm, None);
    }

    #[test]
    fn well_formed_instances_pass() {
        assert_eq!(relief().check(), Ok(()));
        assert_eq!(footprint().check(), Ok(()));
        let mut aware = relief();
        aware.regime = Regime::TropicalAware;
        assert_eq!(aware.check(), Ok(()));
    }

    #[test]
    fn structural_faults_are_reported() {
        let mut empty = footprint();
        empty.pieces.clear();
        assert_eq!(empty.check(), Err(InstanceError::NoPieces));

        let mut duplicate = footprint();
        duplicate.pieces[1].id = "p00".to_string();
        assert_eq!(
            duplicate.check(),
            Err(InstanceError::DuplicateId("p00".to_string()))
        );

        let mut thin = footprint();
        thin.pieces[0].polygon.truncate(2);
        assert_eq!(
            thin.check(),
            Err(InstanceError::TooFewVertices {
                piece: Some("p00".to_string())
            })
        );

        let mut no_target = footprint();
        no_target.target.truncate(2);
        assert_eq!(
            no_target.check(),
            Err(InstanceError::TooFewVertices { piece: None })
        );
    }

    #[test]
    fn roofs_and_relief_data_follow_the_regime() {
        let mut roof_in_footprint = footprint();
        roof_in_footprint.pieces[0].roof = relief().pieces[0].roof;
        assert_eq!(
            roof_in_footprint.check(),
            Err(InstanceError::RoofMismatchesRegime {
                piece: "p00".to_string()
            })
        );

        let mut missing_roof = relief();
        missing_roof.pieces[1].roof = None;
        assert_eq!(
            missing_roof.check(),
            Err(InstanceError::RoofMismatchesRegime {
                piece: "p01".to_string()
            })
        );

        let mut relief_height_in_footprint = footprint();
        relief_height_in_footprint.relief_mm = Some(35.0);
        assert_eq!(
            relief_height_in_footprint.check(),
            Err(InstanceError::ReliefDataMismatchesRegime)
        );

        let mut no_roof_tolerance = relief();
        no_roof_tolerance.validation.roof_mismatch = None;
        assert_eq!(
            no_roof_tolerance.check(),
            Err(InstanceError::ReliefDataMismatchesRegime)
        );
    }
}
