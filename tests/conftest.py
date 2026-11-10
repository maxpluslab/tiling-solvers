"""Suite-wide configuration: hypothesis profiles and the source checkout fixture."""

import os
from pathlib import Path

import pytest
from hypothesis import settings

from support import corpus

# `ci` is derandomized so that a failure in CI reproduces locally with the same profile.
settings.register_profile("dev", max_examples=60, deadline=None)
settings.register_profile("ci", max_examples=300, deadline=None, derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(scope="session")
def source_repo() -> Path:
    """The tropical-puzzle-lab checkout. Missing is a skip locally and a failure in CI."""
    found = corpus.source_checkout()
    if found is None:
        message = f"no tropical-puzzle-lab checkout; set {corpus.SOURCE_ENV} or clone it alongside"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    return found
