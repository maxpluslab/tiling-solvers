//! Custom search algorithms.
//!
//! Each solver is a module here and becomes its own crate only when its size
//! or dependencies justify it. A solver receives the whole puzzle once and runs
//! entirely in Rust; nothing here calls back into Python.
//!
//! | Module | Contents |
//! | --- | --- |
//! | [`contact_dfs`] | depth-first search over corner contacts, with roofs, cavity pruning and the tray's rotations |
//! | [`canonical`] | when two assemblies are the same, and a canonical form |

pub mod canonical;
pub mod contact_dfs;

pub use canonical::Symmetry;
