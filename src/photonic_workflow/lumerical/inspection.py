"""Compact solver-free inspection of a receipt-bound complete device matrix."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .workflow import load_device_run


def inspect_device_run(receipt_file: Path, *, require_diagnostics: bool = False) -> dict[str, Any]:
    """Verify retained artifacts and return bounded metrics, without vendor imports.

    Native execution and diagnostic flags describe the saved run. Inspection is
    read-only and does not independently authenticate or qualify that run.
    """
    run = load_device_run(receipt_file, require_diagnostics=require_diagnostics)
    receipt, data = run["receipt"], run["data"]
    result = receipt["result"]
    pairs = np.asarray(data["s_matrices"], dtype=float)
    matrix = pairs[..., 0] + 1j * pairs[..., 1]
    guided = np.sum(np.abs(matrix) ** 2, axis=1)
    reflected = np.abs(np.diagonal(matrix, axis1=1, axis2=2)) ** 2
    return {
        "status": receipt["status"], "operation": receipt["operation"],
        "projection": "verified-device-summary", "artifact_integrity_verified": True,
        "receipt_sha256": run["receipt_sha256"], "artifact_count": len(receipt["artifacts"]),
        "native_execution_recorded": receipt["native_execution"],
        "solve_completed_recorded": receipt["solve_completed"],
        "family": run["request"]["parameters"]["family"], "model_level": data["model_level"],
        "port_order": data["port_order"], "source_count": len(result["source_columns"]),
        "matrix_shape": list(matrix.shape), "wavelength_count": len(data["wavelengths_nm"]),
        "wavelength_range_nm": [min(data["wavelengths_nm"]), max(data["wavelengths_nm"])],
        "matrix_complete": True, "basis_consistent": True,
        "native_diagnostic_passed": result.get("diagnostic_passed") is True,
        "metrics_recomputed_from_native_matrix": {
            "max_singular_value": float(np.linalg.svd(matrix, compute_uv=False).max()),
            "max_reciprocity_error": float(np.abs(matrix - matrix.transpose(0, 2, 1)).max()),
            "max_reflection_power": float(reflected.max()),
            "guided_output_power_range": [float(guided.min()), float(guided.max())],
        },
        "will_execute": False, "physics_accepted": False,
        "claim_boundary": [
            "Recorded native execution is not independently authenticated by local hashes.",
            "Complete matrix covers the declared selected modes, not every possible guided mode.",
            "Artifact integrity and conditional diagnostics do not establish device qualification.",
        ],
    }
