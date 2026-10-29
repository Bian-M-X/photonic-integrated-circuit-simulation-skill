"""Immutable renderer bindings shared by catalog and application services."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

MAX_COMSOL_EULER_SAMPLES: Final = 256
MAX_COMSOL_CIRCULAR_VERTICES: Final = 16
MAX_COMSOL_FRAGMENT_BYTES: Final = 48_000

COMSOL_RECIPE_BINDINGS: Final = MappingProxyType(
    {
        "geometry.circular-route": "circular-route",
        "geometry.symmetric-euler-bend": "symmetric-euler-bend",
        "waveguide.segmented-port-window": "segmented-port-window",
    }
)
COMSOL_INTERNAL_RECIPE_IDS: Final = frozenset(COMSOL_RECIPE_BINDINGS.values())
LUMERICAL_RECIPE_IDS: Final = frozenset({"geometry.circular-route", "geometry.symmetric-euler-bend"})
MAX_LUMERICAL_CIRCULAR_VERTICES: Final = 128
MAX_LUMERICAL_FRAGMENT_BYTES: Final = 1_000_000

__all__ = [
    "COMSOL_INTERNAL_RECIPE_IDS",
    "COMSOL_RECIPE_BINDINGS",
    "LUMERICAL_RECIPE_IDS",
    "MAX_COMSOL_CIRCULAR_VERTICES",
    "MAX_COMSOL_EULER_SAMPLES",
    "MAX_COMSOL_FRAGMENT_BYTES",
    "MAX_LUMERICAL_CIRCULAR_VERTICES",
    "MAX_LUMERICAL_FRAGMENT_BYTES",
]
