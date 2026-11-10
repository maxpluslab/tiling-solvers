//! Custom search algorithms.
//!
//! Each solver is a module here (`contact_dfs` first, then `branch_bound`) and
//! becomes its own crate only when its size or dependencies justify it. A solver
//! receives the whole instance once and runs entirely in Rust; nothing here
//! calls back into Python.
//!
//! No solver is implemented yet. See `docs/roadmap.md`.
