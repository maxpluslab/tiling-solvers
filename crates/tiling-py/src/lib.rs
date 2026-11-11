//! Python bindings, importable as `maxplus_solvers._native`.
//!
//! This crate only converts types and forwards calls. Geometry belongs in
//! `tiling-geometry` and search in `tiling-search`.
//!
//! Conventions on the Python side: a polygon is a sequence of `(x, y)` pairs,
//! a pose is `(x, y, theta)` and a roof is `(z0, gx, gy)`. Polygons are taken
//! to be convex and counter-clockwise, as everywhere else; only `is_convex_ccw`
//! checks it. A polygon with fewer than three vertices is refused.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use tiling_core::{Pose, Roof, Vec2};

type Point = (f64, f64);
type PoseArg = (f64, f64, f64);
type RoofArg = (f64, f64, f64);

fn checked(polygon: Vec<[f64; 2]>) -> PyResult<Vec<Vec2>> {
    if polygon.len() < 3 {
        return Err(PyValueError::new_err(format!(
            "a polygon needs at least 3 vertices, got {}",
            polygon.len()
        )));
    }
    Ok(polygon)
}

fn pose_of((x, y, theta): PoseArg) -> Pose {
    Pose { x, y, theta }
}

fn roof_of((z0, gx, gy): RoofArg) -> Roof {
    Roof { z0, gx, gy }
}

fn points(polygon: Vec<Vec2>) -> Vec<Point> {
    polygon.into_iter().map(|[x, y]| (x, y)).collect()
}

/// Version of the Rust workspace.
#[pyfunction]
fn version() -> &'static str {
    tiling_core::VERSION
}

/// Signed area of a polygon given as `[x, y]` pairs: positive when counter-clockwise.
#[pyfunction]
fn signed_area(polygon: Vec<[f64; 2]>) -> f64 {
    tiling_geometry::signed_area(&polygon)
}

/// Area centroid of a polygon.
#[pyfunction]
fn centroid(polygon: Vec<[f64; 2]>) -> PyResult<Point> {
    let [x, y] = tiling_geometry::centroid(&checked(polygon)?);
    Ok((x, y))
}

/// Whether the vertices form a strictly convex counter-clockwise polygon.
#[pyfunction]
fn is_convex_ccw(polygon: Vec<[f64; 2]>) -> bool {
    tiling_geometry::is_convex_ccw(&polygon)
}

/// A local polygon placed in the world: rotated by `theta`, then moved by `(x, y)`.
#[pyfunction]
fn transform(polygon: Vec<[f64; 2]>, pose: PoseArg) -> PyResult<Vec<Point>> {
    Ok(points(tiling_geometry::transform(
        &checked(polygon)?,
        &pose_of(pose),
    )))
}

/// Whether a point lies in a convex polygon, boundary included.
#[pyfunction]
fn contains_point(polygon: Vec<[f64; 2]>, point: [f64; 2]) -> PyResult<bool> {
    Ok(tiling_geometry::contains_point(&checked(polygon)?, point))
}

/// Distance from a point to a convex polygon: zero inside or on the boundary.
#[pyfunction]
fn point_outside_depth(point: [f64; 2], container: Vec<[f64; 2]>) -> PyResult<f64> {
    Ok(tiling_geometry::point_outside_depth(
        point,
        &checked(container)?,
    ))
}

/// The largest distance by which a vertex of `polygon` lies outside `container`.
#[pyfunction]
fn outside_depth(polygon: Vec<[f64; 2]>, container: Vec<[f64; 2]>) -> PyResult<f64> {
    Ok(tiling_geometry::outside_depth(
        &checked(polygon)?,
        &checked(container)?,
    ))
}

/// Separating-axis measure: positive is the penetration depth, the shortest
/// separating translation; zero or negative means touching or apart.
#[pyfunction]
fn penetration_depth(a: Vec<[f64; 2]>, b: Vec<[f64; 2]>) -> PyResult<f64> {
    Ok(tiling_geometry::penetration_depth(
        &checked(a)?,
        &checked(b)?,
    ))
}

/// The intersection of two convex polygons; empty when they share no area.
#[pyfunction]
fn intersection(a: Vec<[f64; 2]>, b: Vec<[f64; 2]>) -> PyResult<Vec<Point>> {
    Ok(points(tiling_geometry::intersection(
        &checked(a)?,
        &checked(b)?,
    )))
}

/// Area shared by two convex polygons.
#[pyfunction]
fn intersection_area(a: Vec<[f64; 2]>, b: Vec<[f64; 2]>) -> PyResult<f64> {
    Ok(tiling_geometry::intersection_area(
        &checked(a)?,
        &checked(b)?,
    ))
}

/// Area of `polygon` outside the convex `container`.
#[pyfunction]
fn outside_area(polygon: Vec<[f64; 2]>, container: Vec<[f64; 2]>) -> PyResult<f64> {
    Ok(tiling_geometry::outside_area(
        &checked(polygon)?,
        &checked(container)?,
    ))
}

/// What stays the same about an edge wherever its piece is placed.
///
/// Edge `i` runs from vertex `i` to vertex `i + 1`. Angles are the polygon's
/// interior angles at the two ends. The roof fields are `None` without a roof;
/// slopes are in mm per mm, along the edge and along its outward normal.
#[pyclass(frozen, get_all, module = "maxplus_solvers._native")]
struct EdgeSignature {
    length: f64,
    angle_start: f64,
    angle_end: f64,
    height_start: Option<f64>,
    height_end: Option<f64>,
    slope_along: Option<f64>,
    slope_across: Option<f64>,
}

#[pymethods]
impl EdgeSignature {
    fn __repr__(&self) -> String {
        let optional = |v: Option<f64>| v.map_or_else(|| "None".to_owned(), |x| format!("{x:?}"));
        format!(
            "EdgeSignature(length={:?}, angle_start={:?}, angle_end={:?}, height_start={}, \
             height_end={}, slope_along={}, slope_across={})",
            self.length,
            self.angle_start,
            self.angle_end,
            optional(self.height_start),
            optional(self.height_end),
            optional(self.slope_along),
            optional(self.slope_across)
        )
    }
}

/// Signatures of every edge of a piece, in edge order.
#[pyfunction]
#[pyo3(signature = (polygon, roof=None))]
fn edge_signatures(polygon: Vec<[f64; 2]>, roof: Option<RoofArg>) -> PyResult<Vec<EdgeSignature>> {
    let roof = roof.map(roof_of);
    Ok(
        tiling_geometry::edge_signatures(&checked(polygon)?, roof.as_ref())
            .into_iter()
            .map(|s| EdgeSignature {
                length: s.length,
                angle_start: s.angle_start,
                angle_end: s.angle_end,
                height_start: s.height_start,
                height_end: s.height_end,
                slope_along: s.slope_along,
                slope_across: s.slope_across,
            })
            .collect(),
    )
}

/// Height of a placed piece's roof above a world point.
#[pyfunction]
fn roof_height(roof: RoofArg, pose: PoseArg, point: [f64; 2]) -> f64 {
    tiling_geometry::roof_height(&roof_of(roof), &pose_of(pose), point)
}

/// The roof gradient of a placed piece in world coordinates.
#[pyfunction]
fn world_gradient(roof: RoofArg, pose: PoseArg) -> Point {
    let [gx, gy] = tiling_geometry::world_gradient(&roof_of(roof), &pose_of(pose));
    (gx, gy)
}

/// The largest height difference between two placed roofs along a world segment.
#[pyfunction]
fn seam_mismatch(
    roof_a: RoofArg,
    pose_a: PoseArg,
    roof_b: RoofArg,
    pose_b: PoseArg,
    p0: [f64; 2],
    p1: [f64; 2],
) -> f64 {
    tiling_geometry::seam_mismatch(
        &roof_of(roof_a),
        &pose_of(pose_a),
        &roof_of(roof_b),
        &pose_of(pose_b),
        p0,
        p1,
    )
}

/// `(g_a - g_b) . v` along a world segment with unit direction `v`, in mm per mm.
/// The two ends must differ.
#[pyfunction]
fn tangential_gradient_mismatch(
    roof_a: RoofArg,
    pose_a: PoseArg,
    roof_b: RoofArg,
    pose_b: PoseArg,
    p0: [f64; 2],
    p1: [f64; 2],
) -> PyResult<f64> {
    if p0 == p1 {
        return Err(PyValueError::new_err("the segment has no direction"));
    }
    Ok(tiling_geometry::tangential_gradient_mismatch(
        &roof_of(roof_a),
        &pose_of(pose_a),
        &roof_of(roof_b),
        &pose_of(pose_b),
        p0,
        p1,
    ))
}

fn edge_parts(edge: tiling_geometry::EdgeRef) -> (Option<usize>, usize) {
    match edge {
        tiling_geometry::EdgeRef::Tray { edge } => (None, edge),
        tiling_geometry::EdgeRef::Piece { piece, edge } => (Some(piece), edge),
    }
}

fn edge_of(piece: Option<usize>, edge: usize) -> tiling_geometry::EdgeRef {
    match piece {
        None => tiling_geometry::EdgeRef::Tray { edge },
        Some(piece) => tiling_geometry::EdgeRef::Piece { piece, edge },
    }
}

/// A corner of the uncovered region: a free wedge at `(x, y)` that opens
/// counter-clockwise from `direction` through `angle`.
///
/// The wedge's first side runs along an edge of the tray (`source_piece` is
/// `None`) or of a placed piece. `convex` says the wedge is narrower than a
/// half turn, which is what makes its proposals complete.
#[pyclass(frozen, get_all, module = "maxplus_solvers._native")]
struct Corner {
    x: f64,
    y: f64,
    direction: f64,
    angle: f64,
    convex: bool,
    source_piece: Option<usize>,
    source_edge: usize,
}

#[pymethods]
impl Corner {
    fn __repr__(&self) -> String {
        let source = match self.source_piece {
            None => format!("tray edge {}", self.source_edge),
            Some(piece) => format!("piece {piece} edge {}", self.source_edge),
        };
        format!(
            "Corner(x={:?}, y={:?}, direction={:?}, angle={:?}, convex={}, source={source})",
            self.x,
            self.y,
            self.direction,
            self.angle,
            if self.convex { "True" } else { "False" }
        )
    }
}

/// A placement that fills a corner and fits: piece `piece` at `(x, y, theta)`,
/// its vertex `vertex` at the corner and the edge leaving that vertex flush
/// against the contact edge (`contact_piece` is `None` for the tray).
#[pyclass(frozen, get_all, module = "maxplus_solvers._native")]
struct Candidate {
    piece: usize,
    x: f64,
    y: f64,
    theta: f64,
    vertex: usize,
    contact_piece: Option<usize>,
    contact_edge: usize,
}

#[pymethods]
impl Candidate {
    /// The pose as `(x, y, theta)`.
    #[getter]
    fn pose(&self) -> PoseArg {
        (self.x, self.y, self.theta)
    }

    fn __repr__(&self) -> String {
        format!(
            "Candidate(piece={}, x={:?}, y={:?}, theta={:?}, vertex={})",
            self.piece, self.x, self.y, self.theta, self.vertex
        )
    }
}

/// What a placement would do: how far it reaches outside the target, how deep
/// it enters a placed piece and which one, and whether both are within the
/// assembly's length tolerance.
#[pyclass(frozen, get_all, module = "maxplus_solvers._native")]
struct PlacementCheck {
    outside_mm: f64,
    overlap_mm: f64,
    blocker: Option<usize>,
    fits: bool,
}

/// A reversible partial assembly and the candidate interface over it.
///
/// Pieces are local polygons, numbered as given. `roofs`, if present, gives one
/// `(z0, gx, gy)` per piece. The tolerances say how close counts as coincident.
#[pyclass(module = "maxplus_solvers._native")]
struct Assembly {
    inner: tiling_geometry::Assembly,
}

impl Assembly {
    fn piece_index(&self, piece: usize) -> PyResult<usize> {
        if piece < self.inner.piece_count() {
            Ok(piece)
        } else {
            Err(PyValueError::new_err(format!("there is no piece {piece}")))
        }
    }

    fn edge_index(&self, piece: usize, edge: usize) -> PyResult<usize> {
        let count = self.inner.shape(self.piece_index(piece)?).polygon.len();
        if edge < count {
            Ok(edge)
        } else {
            Err(PyValueError::new_err(format!(
                "piece {piece} has no edge {edge}"
            )))
        }
    }

    fn fixed_edge(&self, piece: Option<usize>, edge: usize) -> PyResult<tiling_geometry::EdgeRef> {
        match piece {
            None if edge < self.inner.target().len() => {}
            None => {
                return Err(PyValueError::new_err(format!(
                    "the tray has no edge {edge}"
                )));
            }
            Some(piece) => {
                self.edge_index(piece, edge)?;
            }
        }
        Ok(edge_of(piece, edge))
    }
}

#[pymethods]
impl Assembly {
    #[new]
    #[pyo3(signature = (target, pieces, roofs=None, *, length_tol, angle_tol, slope_tol))]
    fn new(
        target: Vec<[f64; 2]>,
        pieces: Vec<Vec<[f64; 2]>>,
        roofs: Option<Vec<RoofArg>>,
        length_tol: f64,
        angle_tol: f64,
        slope_tol: f64,
    ) -> PyResult<Assembly> {
        if let Some(roofs) = &roofs {
            if roofs.len() != pieces.len() {
                return Err(PyValueError::new_err(format!(
                    "{} roofs for {} pieces",
                    roofs.len(),
                    pieces.len()
                )));
            }
        }
        let shapes = pieces
            .into_iter()
            .enumerate()
            .map(|(i, polygon)| tiling_geometry::Shape {
                polygon,
                roof: roofs.as_ref().map(|r| roof_of(r[i])),
            })
            .collect();
        let tolerance = tiling_geometry::ContactTolerance {
            length: length_tol,
            angle: angle_tol,
            slope: slope_tol,
        };
        tiling_geometry::Assembly::new(target, shapes, tolerance)
            .map(|inner| Assembly { inner })
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    #[getter]
    fn piece_count(&self) -> usize {
        self.inner.piece_count()
    }

    /// Number of piece edges, the nodes of the compatibility graph besides the tray's.
    #[getter]
    fn edge_count(&self) -> usize {
        self.inner.graph().edge_count()
    }

    /// Number of arcs between piece edges in the compatibility graph.
    #[getter]
    fn arc_count(&self) -> usize {
        self.inner.graph().arc_count()
    }

    #[getter]
    fn all_placed(&self) -> bool {
        self.inner.all_placed()
    }

    /// Placed pieces, oldest first.
    fn placed(&self) -> Vec<usize> {
        self.inner.placed().to_vec()
    }

    /// The pose of a placed piece, or `None`.
    fn pose(&self, piece: usize) -> PyResult<Option<PoseArg>> {
        Ok(self
            .inner
            .pose(self.piece_index(piece)?)
            .map(|p| (p.x, p.y, p.theta)))
    }

    /// For each piece, the lowest-numbered piece congruent to it, roof included.
    fn classes(&self) -> Vec<usize> {
        (0..self.inner.piece_count())
            .map(|p| self.inner.graph().class(p))
            .collect()
    }

    /// For each piece, how many rotations map it onto itself, roof included.
    fn symmetry(&self) -> Vec<usize> {
        (0..self.inner.piece_count())
            .map(|p| self.inner.graph().symmetry(p))
            .collect()
    }

    /// Whether edge `edge` of `piece` may lie flush against a fixed edge: an
    /// edge of the tray (`fixed_piece` is `None`) or of another piece.
    fn compatible(
        &self,
        fixed_piece: Option<usize>,
        fixed_edge: usize,
        piece: usize,
        edge: usize,
    ) -> PyResult<bool> {
        let fixed = self.fixed_edge(fixed_piece, fixed_edge)?;
        self.edge_index(piece, edge)?;
        Ok(self.inner.graph().compatible(fixed, piece, edge))
    }

    /// Put a piece down. Whether it fits is `check_placement`'s question.
    fn place(&mut self, piece: usize, pose: PoseArg) -> PyResult<()> {
        self.inner
            .place(piece, pose_of(pose))
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    /// Take back the most recent placement; returns the piece, or `None` if nothing is placed.
    fn undo(&mut self) -> Option<usize> {
        self.inner.undo()
    }

    /// Every corner of the uncovered region, in a fixed order. Empty exactly
    /// when the placed pieces cover the target.
    fn frontier(&self) -> Vec<Corner> {
        let tolerance = *self.inner.tolerance();
        self.inner
            .frontier()
            .into_iter()
            .map(|c| {
                let (source_piece, source_edge) = edge_parts(c.source);
                Corner {
                    x: c.vertex[0],
                    y: c.vertex[1],
                    direction: c.direction,
                    angle: c.angle,
                    convex: c.is_convex(&tolerance),
                    source_piece,
                    source_edge,
                }
            })
            .collect()
    }

    /// The placements that fill a corner and fit, leaving out congruent twins
    /// and symmetric repeats. Complete for a convex corner.
    fn propose(&mut self, corner: PyRef<'_, Corner>) -> PyResult<Vec<Candidate>> {
        let source = self.fixed_edge(corner.source_piece, corner.source_edge)?;
        let corner = tiling_geometry::Corner {
            vertex: [corner.x, corner.y],
            direction: corner.direction,
            angle: corner.angle,
            source,
        };
        Ok(self
            .inner
            .propose(&corner)
            .into_iter()
            .map(|c| {
                let (contact_piece, contact_edge) = edge_parts(c.contact);
                Candidate {
                    piece: c.piece,
                    x: c.pose.x,
                    y: c.pose.y,
                    theta: c.pose.theta,
                    vertex: c.vertex,
                    contact_piece,
                    contact_edge,
                }
            })
            .collect())
    }

    /// Measure a placement against the target and the other placed pieces.
    fn check_placement(&self, piece: usize, pose: PoseArg) -> PyResult<PlacementCheck> {
        let check = self
            .inner
            .check_placement(piece, &pose_of(pose))
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(PlacementCheck {
            outside_mm: check.outside,
            overlap_mm: check.overlap,
            blocker: check.blocker,
            fits: check.fits(self.inner.tolerance()),
        })
    }

    /// Candidate work so far as `(generated, rejected_outside, rejected_overlap)`.
    fn stats(&self) -> (u64, u64, u64) {
        let stats = self.inner.stats();
        (
            stats.generated,
            stats.rejected_outside,
            stats.rejected_overlap,
        )
    }
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(signed_area, m)?)?;
    m.add_function(wrap_pyfunction!(centroid, m)?)?;
    m.add_function(wrap_pyfunction!(is_convex_ccw, m)?)?;
    m.add_function(wrap_pyfunction!(transform, m)?)?;
    m.add_function(wrap_pyfunction!(contains_point, m)?)?;
    m.add_function(wrap_pyfunction!(point_outside_depth, m)?)?;
    m.add_function(wrap_pyfunction!(outside_depth, m)?)?;
    m.add_function(wrap_pyfunction!(penetration_depth, m)?)?;
    m.add_function(wrap_pyfunction!(intersection, m)?)?;
    m.add_function(wrap_pyfunction!(intersection_area, m)?)?;
    m.add_function(wrap_pyfunction!(outside_area, m)?)?;
    m.add_function(wrap_pyfunction!(edge_signatures, m)?)?;
    m.add_function(wrap_pyfunction!(roof_height, m)?)?;
    m.add_function(wrap_pyfunction!(world_gradient, m)?)?;
    m.add_function(wrap_pyfunction!(seam_mismatch, m)?)?;
    m.add_function(wrap_pyfunction!(tangential_gradient_mismatch, m)?)?;
    m.add_class::<EdgeSignature>()?;
    m.add_class::<Corner>()?;
    m.add_class::<Candidate>()?;
    m.add_class::<PlacementCheck>()?;
    m.add_class::<Assembly>()?;
    Ok(())
}
