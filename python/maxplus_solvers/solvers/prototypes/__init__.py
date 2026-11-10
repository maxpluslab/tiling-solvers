"""Solvers prototyped in Python.

They are written the way their Rust successors will be: integer indices,
reversible state, deterministic iteration, no recursion that a port would have
to undo. Geometry comes from ``_native``, so a port replaces the control flow
and nothing else.
"""
