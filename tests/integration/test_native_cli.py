"""Native-family CLI routing and explicit execution boundaries, without COMSOL."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from photonic_workflow import native_backend, native_pn
from photonic_workflow.cli import main

FAMILIES = ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch", "ring", "ring-modulator")


def invoke(arguments):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        code = main(arguments)
    return code, json.loads(output.getvalue()), error.getvalue()


def request_file(tmp_path, family="crossing", **updates):
    request = {"schema_version": "1.0", "family": family, "wavelengths_nm": [1550], "stage": "configure"}
    request.update(updates)
    path = tmp_path / f"{family}.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def test_catalog_and_all_families_prepare_verify_without_solver(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline CLI attempted a solver process")

    monkeypatch.setattr(native_backend, "_launch", forbidden)
    code, catalog, error = invoke(["native", "list", "--json"])
    assert (code, error) == (0, "")
    assert catalog["data"]["families"] == list(FAMILIES)
    assert catalog["data"]["physics_accepted"] is False
    for family in FAMILIES:
        bundle = tmp_path / f"{family}-bundle"
        code, prepared, error = invoke(
            [
                "native",
                "prepare",
                str(request_file(tmp_path, family)),
                "--output",
                str(bundle),
                "--json",
            ]
        )
        assert (code, error) == (0, ""), prepared
        assert prepared["data"]["manifest"]["family"] == family
        assert prepared["data"]["manifest"]["native_execution"] is False
        code, verified, error = invoke(["native", "verify", str(bundle), "--json"])
        assert (code, error) == (0, "")
        assert verified["data"]["family"] == family
        assert verified["data"]["native_execution"] is False
        geometry = json.loads((bundle / "geometry.json").read_text())
        if family in ("crossing", "directional-coupler", "mmi2x2"):
            assert len(geometry["ports"]) == 4
        if family == "ring-modulator":
            assert "pn_response" in geometry


def test_substituted_source_and_reused_output_are_rejected(tmp_path):
    request = request_file(tmp_path)
    bundle = tmp_path / "bundle"
    assert invoke(["native", "prepare", str(request), "--output", str(bundle), "--json"])[0] == 0
    manifest = (bundle / "manifest.json").read_bytes()
    code, report, error = invoke(["native", "prepare", str(request), "--output", str(bundle), "--json"])
    assert (code, error) == (2, "")
    assert report["ok"] is False
    assert (bundle / "manifest.json").read_bytes() == manifest
    with (bundle / "NativePic.java").open("ab") as stream:
        stream.write(b"\n// changed after preparation\n")
    code, report, error = invoke(["native", "verify", str(bundle), "--json"])
    assert (code, error) == (2, "")
    assert report["ok"] is False


@pytest.mark.parametrize("wavelengths", [[], [1550, 1540], [1550, 1550], [True], [1800]])
def test_invalid_spectral_request_never_creates_bundle(tmp_path, wavelengths):
    request = request_file(tmp_path, wavelengths_nm=wavelengths)
    bundle = tmp_path / "not-created"
    code, report, error = invoke(["native", "prepare", str(request), "--output", str(bundle), "--json"])
    assert (code, error) == (2, "")
    assert report["ok"] is False
    assert not bundle.exists()


@pytest.mark.parametrize("field", ["optical_width_um", "junction_length_um"])
@pytest.mark.parametrize("value", ["0.3", [], None, True, False])
def test_invalid_pn_dimensions_return_json_error_without_creating_bundle(tmp_path, field, value):
    request = request_file(tmp_path, "ring-modulator", pn={field: value})
    bundle = tmp_path / "not-created"
    code, report, error = invoke(["native", "prepare", str(request), "--output", str(bundle), "--json"])
    assert (code, error) == (2, "")
    assert report["ok"] is False
    assert report["status"] == "invalid_input"
    assert any(field in message for message in report["errors"])
    assert not bundle.exists()


def test_pn_response_and_native_poisson_preparation_are_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(native_backend, "_launch", lambda *a, **k: pytest.fail("unexpected native process"))
    request = tmp_path / "pn.json"
    request.write_text(json.dumps({"reverse_bias_v": 1.0}), encoding="utf-8")
    code, report, error = invoke(["native", "pn-response", str(request), "--json"])
    assert (code, error) == (0, "")
    response = report["data"]
    assert response["parameters"]["reverse_bias_v"] == 1
    assert response["physics_accepted"] is False
    assert response["delta_n_eff"] > 0
    assert response["delta_k_eff"] < 0
    bundle = tmp_path / "pn-bundle"
    code, report, error = invoke(["native", "pn-prepare", str(request), "--output", str(bundle), "--json"])
    assert (code, error) == (0, "")
    assert report["data"]["native_execution"] is False
    verified = native_pn.verify_pn_bundle(bundle)
    assert verified["parameters"] == response["parameters"]


@pytest.mark.parametrize("pn", [False, True])
def test_missing_native_capability_returns_unavailable_envelope(tmp_path, monkeypatch, pn):
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    def unavailable(*args, **kwargs):
        raise RuntimeError("native execution unavailable in this test")

    monkeypatch.setattr(
        native_pn if pn else native_backend, "run_pn_bundle" if pn else "run_native_bundle", unavailable
    )
    code, report, error = invoke(["native", "pn-run" if pn else "run", str(bundle), "--json"])
    assert (code, error) == (3, "")
    assert report["status"] == "unavailable_capability"
    assert report["ok"] is False


@pytest.mark.parametrize("pn", [False, True])
def test_executed_failure_retains_receipt_and_execution_failure_status(tmp_path, monkeypatch, pn):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    receipt = {
        "status": "failed",
        "stage": "stationary" if pn else "solve",
        "family": "pn-depletion-poisson" if pn else "crossing",
        "run_directory": str(tmp_path / "failed-run"),
        "elapsed_seconds": 0.1,
        "error": {"type": "RuntimeError", "message": "synthetic compile failure"},
    }
    monkeypatch.setattr(
        native_pn if pn else native_backend, "run_pn_bundle" if pn else "run_native_bundle", lambda *a, **k: receipt
    )
    code, report, error = invoke(["native", "pn-run" if pn else "run", str(bundle), "--json"])
    assert (code, error) == (5, "")
    assert report["status"] == "execution_failure"
    assert report["data"]["status"] == "failed"
    assert report["data"]["error"]["message"] == "synthetic compile failure"


@pytest.mark.parametrize("pn", [False, True])
def test_failed_native_receipt_cannot_be_calibrated(tmp_path, pn):
    receipt = tmp_path / "failed.json"
    receipt.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    code, report, error = invoke(["native", "pn-calibrate" if pn else "calibrate", str(receipt), "--json"])
    assert (code, error) == (2, "")
    assert report["ok"] is False
