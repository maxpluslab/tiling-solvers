//! Python bindings, importable as `maxplus_solvers._native`.
//!
//! This crate only converts types and forwards calls. Geometry belongs in
//! `tiling-geometry` and search in `tiling-search`.

use pyo3::prelude::*;

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

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(signed_area, m)?)?;
    Ok(())
}
