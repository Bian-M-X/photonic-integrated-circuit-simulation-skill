from __future__ import annotations

import importlib
import sys
import tomllib
import unittest
from pathlib import Path

from photonic_workflow.adapters import validate_adapter_provider_contract
from photonic_workflow.compatibility import ADAPTER_ENTRY_POINT_GROUP

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "minimal-adapter-provider"


class ExternalProviderExampleTests(unittest.TestCase):
    def test_example_metadata_and_provider_match_the_public_contract(self) -> None:
        with (EXAMPLE_ROOT / "pyproject.toml").open("rb") as handle:
            metadata = tomllib.load(handle)
        entry_points = metadata["project"]["entry-points"]
        self.assertEqual(
            entry_points[ADAPTER_ENTRY_POINT_GROUP]["reviewed-example"],
            "photonic_example_adapter:provide_adapters",
        )
        self.assertEqual(
            metadata["project"]["dependencies"],
            ["photonic-workflow>=0.5,<0.9"],
        )

        example_source = str(EXAMPLE_ROOT / "src")
        sys.path.insert(0, example_source)
        try:
            module = importlib.import_module("photonic_example_adapter")
            registrations = validate_adapter_provider_contract(
                module.provide_adapters,
                provider_name="reviewed-example",
            )
        finally:
            sys.modules.pop("photonic_example_adapter", None)
            sys.path.remove(example_source)
        self.assertEqual(
            [item.descriptor.adapter for item in registrations],
            ["reviewed-example"],
        )


if __name__ == "__main__":
    unittest.main()
