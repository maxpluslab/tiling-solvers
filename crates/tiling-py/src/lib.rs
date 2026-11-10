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
    Ok(())
}
