from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from click.testing import CliRunner

from photonic_workflow.cli import cli
from photonic_workflow.diagnostics import (
    audit_request,
    geometry_audit,
    load_diagnostic_request,
    phase_audit,
    scattering_audit,
)
from photonic_workflow.exceptions import InvalidInputError


def scattering_request(matrix: np.ndarray) -> dict:
    channels = [f"mode{i}" for i in range(len(matrix))]
    return {
        "channels": channels, "source_map": {p: f"source-{i + 7}" for i, p in enumerate(channels)},
        "wavelength_nm": 1550.0, "tolerance": 1e-8,
        "assumptions": {"passive": True, "reciprocal": True, "lossless": True,
                        "complete_channels": True, "power_orthonormal": True,
                        "source_independent_basis": True, "reciprocity_paired_basis": True,
                        "evidence": ["verification/basis.json"]},
        "columns": [{"input_channel": p, "source_id": f"source-{j + 7}",
                     "model_id": "built-once", "basis_id": "frozen", "dataset_id": "dset1",
                     "wavelength_nm": 1550.0,
                     "values": [[float(z.real), float(z.imag)] for z in matrix[:, j]]}
                    for j, p in enumerate(channels)],
    }


def geometry_request() -> dict:
    return {"length_unit": "um",
            "domains": [{"id": 9, "area_um2": 21.0, "bbox_um": [0, 30, -.35, .35], "material": "core"},
                        {"id": 2, "area_um2": 699.0, "bbox_um": [0, 30, -12, 12], "material": "clad"}],
            "regions": [{"name": "guide", "domain_ids": [9], "material": "core",
                         "area_interval_um2": [20.9, 21.1], "bbox_interval_um": [0, 30, -.36, .36]},
                        {"name": "background", "domain_ids": [2], "material": "clad",
                         "area_interval_um2": [698, 700], "bbox_interval_um": [0, 30, -12, 12]}],
            "expected_neff": [1.53, 1.55], "actual_neff": 1.5387}


class ConditionalScatteringTests(unittest.TestCase):
    def test_active_gain_is_not_rejected_by_column_power(self) -> None:
        data = scattering_request(2 * np.eye(2, dtype=complex))
        data["assumptions"].update(passive=False, lossless=False)
        result = scattering_audit(data)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"]["passivity"]["status"], "not_applicable")
        self.assertEqual(result["raw_metrics"]["column_power"], [4, 4])
        data["assumptions"]["passive"] = True
        self.assertEqual(scattering_audit(data)["checks"]["passivity"]["status"], "fail")

    def test_lossy_reciprocal_positive_and_lossless_negative(self) -> None:
        data = scattering_request(.7 * np.array([[0, 1], [1, 0]], dtype=complex))
        data["assumptions"]["lossless"] = False
        self.assertEqual(scattering_audit(data)["status"], "pass")
        data["assumptions"]["lossless"] = True
        self.assertEqual(scattering_audit(data)["checks"]["unitarity"]["status"], "fail")

    def test_nonreciprocal_permutation(self) -> None:
        data = scattering_request(np.roll(np.eye(3, dtype=complex), 1, axis=0))
        data["assumptions"]["reciprocal"] = False
        self.assertEqual(scattering_audit(data)["status"], "pass")
        data["assumptions"]["reciprocal"] = True
        self.assertEqual(scattering_audit(data)["checks"]["reciprocity"]["status"], "fail")

    def test_unitary_rephasing_preserves_singular_values_but_not_raw_symmetry(self) -> None:
        matrix = np.array([[0, .8], [.8, 0]], dtype=complex)
        rotated = np.diag(np.exp(1j * np.array([.2, 1.3]))) @ matrix @ np.diag(np.exp(1j * np.array([.7, -.4])))
        data = scattering_request(rotated)
        data["assumptions"].update(lossless=False, reciprocity_paired_basis=False)
        result = scattering_audit(data)
        self.assertAlmostEqual(result["raw_metrics"]["sigma_max"], .8)
        self.assertEqual(result["checks"]["passivity"]["status"], "pass")
        self.assertEqual(result["checks"]["reciprocity"]["status"], "blocked")

    def test_source_dependent_coordinates_do_not_prove_operator(self) -> None:
        # Independently rotating the second column of I onto the first yields sqrt(2), not 1.
        data = scattering_request(np.array([[1, 1], [0, 0]], dtype=complex))
        data["assumptions"]["source_independent_basis"] = False
        result = scattering_audit(data)
        self.assertAlmostEqual(result["raw_metrics"]["sigma_max"], math.sqrt(2))
        self.assertEqual(result["status"], "blocked")

    def test_missing_evidence_unknown_assumptions_and_cross_run_block(self) -> None:
        for mutate in [lambda d: d["assumptions"].update(evidence=[]),
                       lambda d: d["assumptions"].update(passive=None),
                       lambda d: d["columns"][1].update(model_id="rebuilt")]:
            data = scattering_request(np.eye(2, dtype=complex))
            mutate(data)
            self.assertEqual(scattering_audit(data)["status"], "blocked")

    def test_four_channels_ordered_by_identity_not_array_position(self) -> None:
        data = scattering_request(np.eye(4, dtype=complex))
        data["columns"].reverse()
        result = scattering_audit(data)
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["physics_accepted"])

    def test_missing_duplicate_wrong_source_and_nan_rejected(self) -> None:
        cases = []
        data = scattering_request(np.eye(4, dtype=complex))
        cases.append({**data, "columns": data["columns"][:-1]})
        data = copy.deepcopy(data)
        data["columns"][1] = copy.deepcopy(data["columns"][0])
        cases.append(data)
        for field, value in [("source_id", "wrong"), ("wavelength_nm", 1560),
                             ("values", [[math.nan, 0]] * 4)]:
            data = scattering_request(np.eye(4, dtype=complex))
            data["columns"][0][field] = value
            cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(InvalidInputError):
                scattering_audit(data)


class GeometryReadbackTests(unittest.TestCase):
    def test_positive_and_material_swap(self) -> None:
        data = geometry_request()
        self.assertEqual(geometry_audit(data)["status"], "pass")
        data["domains"][0]["material"], data["domains"][1]["material"] = "clad", "core"
        result = geometry_audit(data)
        self.assertEqual(result["checks"]["guide:material"]["status"], "fail")
        self.assertEqual(result["checks"]["background:material"]["status"], "fail")

    def test_area_bbox_and_neff_each_detect_independent_error(self) -> None:
        for field, value, check in [("area_um2", 75.4, "guide:area"),
                                    ("bbox_um", [-.02, 31.47, -1.47, .35], "guide:bbox")]:
            data = geometry_request()
            data["domains"][0][field] = value
            self.assertEqual(geometry_audit(data)["checks"][check]["status"], "fail")
        data = geometry_request()
        data["actual_neff"] = 1.58036
        self.assertEqual(geometry_audit(data)["checks"]["port_neff"]["status"], "fail")

    def test_multicore_reordered_ids_and_smaller_air_hole(self) -> None:
        data = geometry_request()
        data["domains"].append({"id": 1, "area_um2": .01, "bbox_um": [1, 1.1, 1, 1.1], "material": "air"})
        data["regions"].append({"name": "hole", "domain_ids": [1], "material": "air",
                                "area_interval_um2": [.009, .011], "bbox_interval_um": [1, 1.1, 1, 1.1]})
        core = data["domains"][0]
        core["area_um2"] = 10.5
        data["domains"].append({**core, "id": 15})
        data["regions"][0]["domain_ids"] = [15, 9]
        self.assertEqual(geometry_audit(data)["status"], "pass")
        data["regions"][0]["domain_ids"] = [1]
        with self.assertRaises(InvalidInputError):
            geometry_audit(data)

    def test_missing_mode_does_not_pass_requested_mode_check(self) -> None:
        data = geometry_request()
        data["actual_neff"] = None
        self.assertEqual(geometry_audit(data)["status"], "blocked")
        data["expected_neff"] = None
        self.assertEqual(geometry_audit(data)["status"], "pass")


class PhaseAndCliTests(unittest.TestCase):
    def test_large_finite_components_do_not_crash_or_create_nan(self) -> None:
        data = {"reference": [[1.7e308, 1.7e308]], "candidate": [[1.7e308, 1.7e308]],
                "amplitude_floor": 1, "phase_tolerance_rad": .05, "complex_tolerance": 1e-8,
                "policy_id": "large-finite"}
        self.assertEqual(phase_audit(data)["status"], "pass")
        data["candidate"] = [[-1.7e308, -1.7e308]]
        with self.assertRaises(InvalidInputError):
            phase_audit(data)

    def test_near_zero_keeps_strict_failure(self) -> None:
        data = {"reference": [[1e-10, 0]], "candidate": [[0, 1e-10]], "amplitude_floor": 1e-4,
                "phase_tolerance_rad": .05, "complex_tolerance": 1e-8, "policy_id": "future-frozen-v1"}
        result = phase_audit(data)
        self.assertEqual(result["checks"]["strict_phase"]["status"], "fail")
        self.assertEqual(result["checks"]["absolute_complex"]["status"], "pass")
        self.assertEqual(result["conditioned_phase"]["status"], "not_applicable")
        data["reference"] = [[0, 0]]
        self.assertIsNone(phase_audit(data)["rows"][0]["raw_phase_error_rad"])
        self.assertEqual(phase_audit(data)["status"], "blocked")

    def test_positive_phase_and_branch_cut(self) -> None:
        data = {"reference": [[-1, 1e-5]], "candidate": [[-1, -1e-5]], "amplitude_floor": .01,
                "phase_tolerance_rad": .05, "complex_tolerance": 1e-3, "policy_id": "test"}
        self.assertEqual(phase_audit(data)["status"], "pass")

    def test_json_contract_and_cli_rejection_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            payload = {"schema_version": "1.0", "kind": "geometry", "data": geometry_request()}
            path.write_text(json.dumps(payload), encoding="utf-8")
            runner = CliRunner()
            result = runner.invoke(cli, ["audit", "diagnostics", str(path), "--fail-on-issues", "--json"])
            self.assertEqual(result.exit_code, 0, result.output)
            payload["data"]["actual_neff"] = 1.58
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = runner.invoke(cli, ["audit", "diagnostics", str(path), "--fail-on-issues", "--json"])
            self.assertEqual(result.exit_code, 6, result.output)
            for text in ['{"a":1,"a":2}', '{"a":NaN}']:
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(InvalidInputError):
                    load_diagnostic_request(path)
            payload["data"]["typo"] = 1
            with self.assertRaises(InvalidInputError):
                audit_request(payload)
