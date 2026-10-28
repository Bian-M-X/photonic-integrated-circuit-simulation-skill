"""Validate wheel runtime resources and sdist maintenance sources."""

from __future__ import annotations

import argparse
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NATIVE_EXAMPLE_NAMES = {
    "README.md", "HadamardNative.java", "run.py", "campaign.py",
    "analyze.py", "extract_mask.py", "plot_results.py",
    "CvfDiscreteGradientProbe.java", "check_discrete_gradient.py",
}

WHEEL_REQUIRED_SUFFIXES = (
    "photonic_workflow/data/skill/examples/comsol-device-canary/DeviceCanary.java",
    "photonic_workflow/data/skill/examples/comsol-device-canary/run.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/audit.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/taper_profile.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/profile_modes.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/profile_driven.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/bend_profile.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/bend_geometry.py",
    "photonic_workflow/data/skill/examples/comsol-device-canary/README.md",
    "photonic_workflow/data/skill/examples/device-models/waveguide.json",
    "photonic_workflow/data/skill/examples/device-models/directional-coupler.json",
    "photonic_workflow/data/skill/examples/device-models/ring-allpass.json",
    "photonic_workflow/data/skill/examples/device-models/ring-adddrop.json",
    "photonic_workflow/data/skill/examples/device-models/bragg-uniform.json",
    "photonic_workflow/data/skill/examples/device-models/mmi2x2-ideal.json",
    "photonic_workflow/data/skill/examples/device-models/ybranch-ideal.json",
    "photonic_workflow/device_models.py",
    "photonic_workflow/data/skill/references/executable-device-models.md",
    "photonic_workflow/diagnostics.py",
    "photonic_workflow/consumption.py",
    "photonic_workflow/data/skill/references/executable-diagnostics.md",
    "photonic_workflow/adapters/testing.py",
    "photonic_workflow/models/migration_catalog.py",
    "photonic_workflow/data/templates/mzi-4port/assembly.json",
    "photonic_workflow/data/matlab/tests/TestPhotonicRuntime.m",
    "photonic_workflow/data/recipes/provenance-v1.json",
    "photonic_workflow/optimization/robustness.py",
    "photonic_workflow/data/skill/references/fabrication-aware-robust-design.md",
)

SDIST_REQUIRED_RELATIVE_PATHS = (
    "examples/comsol-device-canary/DeviceCanary.java",
    "examples/comsol-device-canary/run.py",
    "examples/comsol-device-canary/audit.py",
    "examples/comsol-device-canary/taper_profile.py",
    "examples/comsol-device-canary/profile_modes.py",
    "examples/comsol-device-canary/profile_driven.py",
    "examples/comsol-device-canary/bend_profile.py",
    "examples/comsol-device-canary/bend_geometry.py",
    "examples/comsol-device-canary/README.md",
    "examples/device-models/waveguide.json",
    "examples/device-models/directional-coupler.json",
    "examples/device-models/ring-allpass.json",
    "examples/device-models/ring-adddrop.json",
    "examples/device-models/bragg-uniform.json",
    "examples/device-models/mmi2x2-ideal.json",
    "examples/device-models/ybranch-ideal.json",
    "tests/unit/test_device_models.py",
    "tests/unit/test_device_models_oracles.py",
    "tests/unit/test_mmi2x2_oracles.py",
    "tests/unit/test_ybranch_oracles.py",
    "tests/integration/test_device_cli.py",
    "tests/unit/test_device_canary.py",
    "tests/unit/test_device_canary_audit.py",
    "tests/unit/test_taper_profile.py",
    "tests/unit/test_profile_modes.py",
    "tests/unit/test_profile_driven.py",
    "tests/unit/test_bend_profile.py",
    "tests/unit/test_bend_geometry.py",
    "docs/research/device-family-roadmap-2026-10.md",
    "examples/diagnostics/geometry-positive.json",
    "examples/diagnostics/four-channel-positive.json",
    "examples/diagnostics/near-zero-phase.json",
    "examples/diagnostics/trace_transform.py",
    "tests/unit/test_diagnostics.py",
    "tests/unit/test_consumption.py",
    "SKILL.md",
    "CHANGELOG.md",
    "README.zh.md",
    "photonic.toml.example",
    "docs/maintenance.md",
    "docs/research/workflow-upgrade-2026-09-results.json",
    "docs/research/literature-methods-2026-10.md",
    "references/fabrication-aware-robust-design.md",
    "examples/optimization/fabrication_robustness.py",
    "tests/unit/test_optimization_robustness.py",
    "docs/providers/authoring-third-party-adapter.md",
    "docs/showcases/hadamard-2d/README.md",
    "docs/showcases/hadamard-2d/verify.py",
    "docs/showcases/hadamard-2d/evidence/bundle.json",
    "docs/showcases/hadamard-2d/evidence/mask.json",
    "docs/showcases/hadamard-2d/evidence/manifest.json",
    "docs/showcases/hadamard-2d/evidence/numeric-verification.json",
    "docs/showcases/hadamard-2d/evidence/startup-gradient-audit.json",
    "examples/minimal-adapter-provider/pyproject.toml",
    "examples/minimal-adapter-provider/src/photonic_example_adapter/__init__.py",
    "examples/recipes/circular-route.json",
    "matlab/tests/TestPhotonicRuntime.m",
    "scripts/sync-packaged-matlab-resources.ps1",
    "scripts/test_installed_adapter_provider.py",
    "tests/fixtures/contract_surface_v1.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.dist_dir.glob("*.whl"))
    sdists = sorted(args.dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}"
        )

    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_names = set(archive.namelist())
        native_prefix = "photonic_workflow/data/skill/examples/comsol-hadamard-inverse/"
        native_names = {name.removeprefix(native_prefix) for name in wheel_names if name.startswith(native_prefix)}
        if native_names != NATIVE_EXAMPLE_NAMES:
            raise RuntimeError(f"wheel native example file set differs: {sorted(native_names)}")
        for name in NATIVE_EXAMPLE_NAMES:
            original = REPOSITORY_ROOT / "examples/comsol-hadamard-inverse" / name
            if archive.read(native_prefix + name) != original.read_bytes():
                raise RuntimeError(f"wheel original native source differs: {name}")
        for example, expected_names in (
            ("device-models", {"waveguide.json", "directional-coupler.json", "ring-allpass.json",
                               "ring-adddrop.json", "bragg-uniform.json", "mmi2x2-ideal.json", "ybranch-ideal.json"}),
            (
                "comsol-device-canary",
                {"README.md", "DeviceCanary.java", "run.py", "audit.py", "taper_profile.py",
                 "profile_modes.py", "profile_driven.py", "bend_profile.py", "bend_geometry.py"},
            ),
        ):
            prefix = f"photonic_workflow/data/skill/examples/{example}/"
            actual_names = {name.removeprefix(prefix) for name in wheel_names if name.startswith(prefix)}
            if actual_names != expected_names:
                raise RuntimeError(f"unexpected packaged {example} files: {sorted(actual_names)}")
            for name in expected_names:
                if archive.read(prefix + name) != (REPOSITORY_ROOT / "examples" / example / name).read_bytes():
                    raise RuntimeError(f"packaged {example}/{name} differs from reviewed source")
    if any("comsol-euler-bend" in name for name in wheel_names):
        raise RuntimeError("wheel contains private Euler example")
    for suffix in WHEEL_REQUIRED_SUFFIXES:
        if not any(name.endswith(suffix) for name in wheel_names):
            raise RuntimeError(f"wheel is missing {suffix}")
    reference_count = sum(
        "/data/skill/references/" in name for name in wheel_names
    )
    agent_count = sum("/data/skill/agents/" in name for name in wheel_names)
    matlab_count = sum("/data/matlab/" in name for name in wheel_names)
    expected_counts = (
        len(tuple((REPOSITORY_ROOT / "references").glob("*.md"))),
        len(tuple((REPOSITORY_ROOT / "agents").glob("*-agent.md"))),
        len(tuple((REPOSITORY_ROOT / "matlab").rglob("*.m"))),
    )
    if (reference_count, agent_count, matlab_count) != expected_counts:
        raise RuntimeError(
            "wheel resource counts are "
            f"{reference_count}/{agent_count}/{matlab_count}, expected "
            f"{expected_counts[0]}/{expected_counts[1]}/{expected_counts[2]} "
            "from repository sources"
        )

    with tarfile.open(sdists[0], mode="r:gz") as archive:
        sdist_names = {
            PurePosixPath(name).parts[1:]
            for name in archive.getnames()
            if len(PurePosixPath(name).parts) > 1
        }
    forbidden_sdist_prefixes = (
        PurePosixPath("examples/comsol-euler-bend").parts,
        PurePosixPath("examples/minimal-adapter-provider/build").parts,
        PurePosixPath(
            "examples/minimal-adapter-provider/src/"
            "photonic_example_adapter.egg-info"
        ).parts,
    )
    for name in sdist_names:
        for prefix in forbidden_sdist_prefixes:
            if name[: len(prefix)] == prefix:
                raise RuntimeError(
                    "sdist contains generated example build metadata: "
                    + PurePosixPath(*name).as_posix()
                )
    for relative in SDIST_REQUIRED_RELATIVE_PATHS:
        parts = PurePosixPath(relative).parts
        if parts not in sdist_names:
            raise RuntimeError(f"sdist is missing {relative}")
    native_sdist_prefix = PurePosixPath("examples/comsol-hadamard-inverse").parts
    native_sdist_files = {
        name[-1] for name in sdist_names
        if name[:2] == native_sdist_prefix and len(name) == 3
    }
    if native_sdist_files != NATIVE_EXAMPLE_NAMES or any(
        name[:2] == native_sdist_prefix and len(name) > 3 for name in sdist_names
    ):
        raise RuntimeError("sdist native example is not the finite original file set")

    print(
        json.dumps(
            {
                "wheel": wheels[0].name,
                "wheel_file_count": len(wheel_names),
                "skill_references": reference_count,
                "skill_agents": agent_count,
                "matlab_files": matlab_count,
                "sdist": sdists[0].name,
                "sdist_file_count": len(sdist_names),
                "maintenance_sources": "present",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
