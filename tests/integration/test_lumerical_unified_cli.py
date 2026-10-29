"""Check the shared renderer and paired-model contracts through the public CLI."""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from photonic_workflow.cli import main
from photonic_workflow.lumerical.parity import make_benchmark_plan
from photonic_workflow.recipes import load_recipe_request, render_recipe

ROOT = Path(__file__).resolve().parents[2]


def invoke(arguments):
    output = io.StringIO()
    with redirect_stdout(output):
        code = main([*arguments, "--json"])
    return code, json.loads(output.getvalue())


class UnifiedLumericalCliTests(unittest.TestCase):
    def test_lsf_cli_keeps_explicit_stack_and_matches_shared_renderer_bytes(self):
        path = ROOT / "examples/recipes/circular-route.json"
        request = load_recipe_request(path)
        code, report = invoke([
            "recipe", "render", request.recipe_id, "--input", str(path),
            "--renderer", "lumerical-lsf-fragment", "--instance-id", "circular_cli",
            "--height-um", "0.22", "--core-index", "2.6",
        ])
        self.assertEqual(code, 0, report)
        expected = render_recipe(request.recipe_id, request.parameters, version=request.recipe_version,
                                 renderer="lumerical-lsf-fragment", instance_id="circular_cli",
                                 height_um=.22, core_index=2.6)
        self.assertEqual(report["data"]["content"], expected.content)
        self.assertEqual(report["data"]["sha256"], expected.sha256)
        self.assertFalse(report["data"]["will_execute"])
        self.assertEqual(report["data"]["renderer_options"], {"height_um": .22, "core_index": 2.6})

    def test_lsf_cli_does_not_invent_a_missing_material_or_extrusion(self):
        path = ROOT / "examples/recipes/circular-route.json"
        code, report = invoke([
            "recipe", "render", "geometry.circular-route", "--input", str(path),
            "--renderer", "lumerical-lsf-fragment", "--instance-id", "missing_stack",
        ])
        self.assertNotEqual(code, 0)
        self.assertFalse(report["ok"])

    def test_cli_benchmark_uses_same_frozen_solver_requests_and_budget(self):
        code, report = invoke(["lumerical", "plan-benchmark", "directional-coupler", "--power-tolerance", "0.03"])
        self.assertEqual(code, 0, report)
        self.assertEqual(report["data"], make_benchmark_plan("directional-coupler", power_tolerance=.03))
        self.assertFalse(report["data"]["will_execute"])


if __name__ == "__main__":
    unittest.main()
