"""Experiments: manifests, the benchmark runner, difficulty proxies, tables and plots.

An experiment is a manifest (``benchmarks/manifests/*.toml``) naming fixtures,
solvers and the settings to vary. :func:`benchmark.run` turns it into one JSON
line per run, each carrying what is needed to repeat it: solver version, input
hash, seed, tolerances and configuration. :mod:`report` turns those lines into
tables, and :mod:`plotting` into figures (the ``analysis`` extra).

Nothing here is needed to solve a puzzle, and nothing here is an algorithm:
solvers are reached through :func:`maxplus_solvers.solve` like any caller.
"""
