from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import click

from photonic_workflow import __version__
from photonic_workflow.cli import cli
from photonic_workflow.compatibility import (
    ADAPTER_ENTRY_POINT_GROUP,
    CURRENT_ADAPTER_SPI_VERSION,
    CURRENT_API_ENVELOPE_SCHEMA_VERSION,
    CURRENT_CONTRACT_SCHEMA_VERSION,
    DEFAULT_CONTRACT_SCHEMA_VERSION,
)
from photonic_workflow.device_models import list_models
from photonic_workflow.maintenance import _cli_surface, contract_surface_snapshot
from photonic_workflow.mcp.server import (
    AGENT_RESOURCES,
    REFERENCE_RESOURCES,
    default_skill_root,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_CLI_SURFACE = {
    "audit": ("artifacts", "diagnostics"),
    "check": (),
    "circuit": ("compose", "validate"),
    "component": ("inspect",),
    "device": ("evaluate", "export", "list"),
    "doctor": (),
    "gate": ("adoption", "list", "set"),
    "init": (),
    "inspect": (),
    "layout": ("compare-backends", "normalize"),
    "lumerical": ("compare-devices", "compare-solvers", "device-export", "discover", "export-geometry",
                  "import-sparameters", "inspect-result", "optimize-step", "plan", "plan-benchmark", "run"),
    "matlab": (
        "check",
        "doctor",
        "inspect",
        "plan",
        "products",
        "run",
        "sessions",
        "test",
        "toolboxes",
    ),
    "measurement": ("inspect",),
    "model": ("build", "compare", "ingest", "inspect", "release", "validate"),
    "native": (
        "calibrate", "compare", "list", "pn-calibrate", "pn-prepare", "pn-response", "pn-run",
        "prepare", "run", "verify",
    ),
    "netlist": ("backannotate", "compare", "extract", "validate"),
    "optimize": ("compare", "inspect", "plan", "promote", "resume", "run", "suggest"),
    "package": ("inspect",),
    "pdk": ("inspect", "validate"),
    "recipe": ("inspect", "list", "render"),
    "report": ("status",),
    "solver": ("check", "plan"),
    "sparams": ("validate",),
    "status": (),
    "tapeout": ("freeze", "inspect"),
    "testplan": ("inspect",),
    "variation": ("validate",),
}


class PublicSurfaceMaintenanceTests(unittest.TestCase):
    def test_device_model_catalog_keeps_seven_fixed_ids_and_analytic_ideal_junctions(self) -> None:
        models = {item["model"]: item for item in list_models()}
        self.assertEqual(set(models), {
            "waveguide", "directional-coupler", "ring-allpass", "ring-adddrop", "bragg-uniform",
            "mmi2x2-ideal", "ybranch-ideal",
        })
        self.assertEqual(models["mmi2x2-ideal"]["model_level"], "analytic")
        self.assertEqual(set(models["mmi2x2-ideal"]["parameters"]), {
            "coupling_power", "excess_loss_db", "phase_rad",
        })
        self.assertEqual(models["ybranch-ideal"]["model_level"], "analytic")
        self.assertEqual(models["ybranch-ideal"]["port_order"], ["trunk", "upper", "lower"])
        self.assertEqual(set(models["ybranch-ideal"]["parameters"]), {
            "coupling_power", "excess_loss_db", "phase_rad",
        })

    def test_cli_snapshot_resolves_lazy_defaults_without_calling_them(self) -> None:
        lazy = Mock(return_value="must not be evaluated")
        command = click.Command("fixture", params=[
            click.Option(["--flag"], is_flag=True),
            click.Option(["--nullable"], is_flag=True, default=None),
            click.Option(["--count"], count=True),
            click.Option(["--lazy"], default=lazy),
        ])
        with patch("photonic_workflow.cli.cli", command):
            parameters = _cli_surface()["photonic"]["parameters"]
        defaults = {item["name"]: item["default"] for item in parameters}
        self.assertIs(defaults["flag"], False)
        self.assertIsNone(defaults["nullable"])
        self.assertEqual(defaults["count"], 0)
        self.assertEqual(defaults["lazy"], "<Mock>")
        lazy.assert_not_called()

    def test_package_version_has_one_code_source_and_docs_are_current(self) -> None:
        with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
            pyproject = tomllib.load(handle)
        self.assertNotIn("version", pyproject["project"])
        self.assertIn("version", pyproject["project"]["dynamic"])
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "photonic_workflow._version.__version__",
        )
        requirements = [
            line.strip()
            for line in (REPOSITORY_ROOT / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(requirements, pyproject["project"]["dependencies"])
        version_source = (
            REPOSITORY_ROOT
            / "src"
            / "photonic_workflow"
            / "_version.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            re.search(r'__version__\s*=\s*"([^"]+)"', version_source).group(1),
            __version__,
        )
        for relative in (
            "README.md",
            "references/comsol-mcp-evaluation.md",
        ):
            self.assertIn(
                __version__,
                (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )

    def test_cli_group_and_command_names_match_compatibility_snapshot(self) -> None:
        actual = {
            name: tuple(sorted(getattr(command, "commands", {})))
            for name, command in sorted(cli.commands.items())
        }
        self.assertEqual(actual, EXPECTED_CLI_SURFACE)

    def test_packaged_mcp_resources_exactly_mirror_skill_sources(self) -> None:
        packaged_root = default_skill_root()
        self.assertNotEqual(packaged_root.resolve(), REPOSITORY_ROOT.resolve())
        mappings = (
            (
                REPOSITORY_ROOT / "references",
                packaged_root / "references",
                set(REFERENCE_RESOURCES.values()),
            ),
            (
                REPOSITORY_ROOT / "agents",
                packaged_root / "agents",
                set(AGENT_RESOURCES.values()),
            ),
        )
        for source_root, packaged_directory, mapped_paths in mappings:
            expected_names = {
                Path(relative).name
                for relative in mapped_paths
            }
            source_names = {
                path.name for path in source_root.glob("*.md") if path.is_file()
            }
            packaged_names = {
                path.name for path in packaged_directory.glob("*.md") if path.is_file()
            }
            self.assertEqual(source_names, expected_names)
            self.assertEqual(packaged_names, expected_names)
            for name in sorted(expected_names):
                self.assertEqual(
                    (source_root / name).read_bytes(),
                    (packaged_directory / name).read_bytes(),
                    name,
                )

    def test_schema_namespaces_and_adapter_entrypoint_are_explicit(self) -> None:
        self.assertEqual(CURRENT_CONTRACT_SCHEMA_VERSION, "1.0")
        self.assertEqual(DEFAULT_CONTRACT_SCHEMA_VERSION, "1.0")
        self.assertEqual(
            CURRENT_CONTRACT_SCHEMA_VERSION,
            DEFAULT_CONTRACT_SCHEMA_VERSION,
        )
        self.assertEqual(CURRENT_API_ENVELOPE_SCHEMA_VERSION, "1.0")
        self.assertEqual(
            ADAPTER_ENTRY_POINT_GROUP,
            "photonic_workflow.adapters",
        )
        self.assertEqual(CURRENT_ADAPTER_SPI_VERSION, "1.0")

    def test_contract_fields_enums_and_exit_codes_match_v1_snapshot(self) -> None:
        expected = json.loads(
            (
                REPOSITORY_ROOT
                / "tests"
                / "fixtures"
                / "contract_surface_v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(contract_surface_snapshot(), expected)

    def test_readme_and_skill_routed_markdown_files_exist(self) -> None:
        for relative in ("README.md", "SKILL.md"):
            text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
            targets = {
                match.replace("\\", "/")
                for match in re.findall(r"`([^`]*?\.md)`", text)
                if "*" not in match and "<" not in match
            }
            self.assertTrue(targets, relative)
            for target in sorted(targets):
                self.assertTrue(
                    (REPOSITORY_ROOT / target).is_file(),
                    f"{relative} routes to missing file {target}",
                )

    def test_external_contract_readers_cannot_bypass_version_routing(self) -> None:
        source_root = REPOSITORY_ROOT / "src" / "photonic_workflow"
        allowed_validation_module = source_root / "models" / "io.py"
        bypasses = []
        for path in source_root.rglob("*.py"):
            if path == allowed_validation_module:
                continue
            if ".model_validate(" in path.read_text(encoding="utf-8"):
                bypasses.append(path.relative_to(REPOSITORY_ROOT).as_posix())
        self.assertEqual(
            bypasses,
            [],
            "external readers must use parse_contract/parse_contract_body; "
            "typed internal mutations use revalidate_internal",
        )


if __name__ == "__main__":
    unittest.main()
