"""Single source of truth for the package version."""

from __future__ import annotations

import re

__version__ = "0.8.0"


def compatible_minor_requirement(
    distribution: str = "photonic-workflow",
) -> str:
    """Return the project-scaffold dependency range for this runtime minor."""

    match = re.match(r"^(\d+)\.(\d+)(?:\.\d+)?", __version__)
    if match is None:
        raise RuntimeError(f"package version is not release-like: {__version__!r}")
    major, minor = (int(part) for part in match.groups())
    return f"{distribution}>={major}.{minor},<{major}.{minor + 1}"


__all__ = ["__version__", "compatible_minor_requirement"]
