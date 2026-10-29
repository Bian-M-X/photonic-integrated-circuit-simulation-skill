"""Reuse published material recipes and inspect Lumerical's actual FDTD fit.

This is a bulk silicon / fused-silica surrogate route, not a calibrated foundry
stack. Positive imaginary index uses the Lumerical exp(-i*omega*t) convention.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import numpy as np

from ..exceptions import InvalidInputError
from ..recipes.materials import li_silicon_1980, malitson_fused_silica_1965

_C = 299792458.0
_FIELDS = ("frequency_hz", "wavelength_m", "n_real", "n_imag", "permittivity_real", "permittivity_imag")


def sample_material_model(spec: dict[str, Any], wavelengths_m: Any) -> dict[str, Any]:
    """Sample one reviewed formula with explicit SI wavelengths and recipe limits.

    Frequency, wavelength and optical values are sorted together in increasing
    frequency. Absorption is explicitly zero because these real-index recipes
    supply no extinction law; it is not inferred from a vendor material name.
    """
    if not isinstance(spec, dict) or "model" not in spec:
        raise InvalidInputError("material spec requires a model")
    model = spec["model"]
    if not isinstance(model, str):
        raise InvalidInputError("material model must be a reviewed model identifier")
    allowed = {"model", "temperature_k"} if model == "li-silicon-1980" else {"model"}
    if set(spec) - allowed or model not in {"li-silicon-1980", "malitson-fused-silica-1965"}:
        raise InvalidInputError("Only reviewed Li1980 silicon and Malitson1965 fused-silica model specs are supported")
    try:
        raw = np.asarray(wavelengths_m)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError("wavelengths_m must be a rectangular numeric array") from exc
    if raw.ndim != 1 or not 3 <= len(raw) <= 4096 or raw.dtype.kind not in "ifu":
        raise InvalidInputError("wavelengths_m must be a 1D array of 3 to 4096 finite positive real samples")
    wavelength = raw.astype(float)
    if not np.isfinite(wavelength).all() or np.any(wavelength <= 0) or len(np.unique(wavelength)) != len(wavelength):
        raise InvalidInputError("wavelengths_m must contain finite positive distinct samples")
    order = np.argsort(_C / wavelength)
    wavelength = wavelength[order]
    if model == "li-silicon-1980":
        temperature = spec.get("temperature_k", 293.15)
        records = [li_silicon_1980(float(value * 1e6), temperature) for value in wavelength]
        source_spec = {"model": model, "temperature_k": float(temperature)}
    else:
        records = [malitson_fused_silica_1965(float(value * 1e6)) for value in wavelength]
        source_spec = {"model": model}
    index = np.array([record["refractive_index"] for record in records], dtype=float)
    zeros = np.zeros_like(index)
    return {
        "schema_version": "1.0", "source_spec": source_spec, "model": model,
        "source_doi": records[0]["source_doi"], "validity": records[0]["validity"],
        "frequency_hz": (_C / wavelength).tolist(), "wavelength_m": wavelength.tolist(),
        "n_real": index.tolist(), "n_imag": zeros.tolist(),
        "permittivity_real": (index ** 2).tolist(), "permittivity_imag": zeros.tolist(),
        "bulk_group_index": [record["bulk_group_index"] for record in records],
        "time_dependence": "exp(-iwt)", "sample_order": order.tolist(),
        "absorption_model": "zero extinction; real-index recipe supplies no absorption law",
        "physics_accepted": False,
        "limitations": [str(record["claim"]["statement"]) for record in records[:1]] + [
            "Bulk material formula only; not an effective modal index or calibrated deposited-film/foundry model.",
            "FDTD fitting changes the supplied sampled dispersion; inspect fit errors before dependent claims.",
        ],
    }


def apply_sampled_material(session: Any, name: str, samples: dict[str, Any]) -> dict[str, Any]:
    """Install fixed sampled-data operations and read the fitted complex index.

    Vendor API contract: a two-column complex matrix [frequency_Hz, epsilon].
    The returned readback includes source and fitted arrays, without silently
    tightening vendor fit settings or declaring a material tolerance satisfied.
    """
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
        raise InvalidInputError("sampled material name must be a safe local identifier")
    if not isinstance(samples, dict) or samples.get("schema_version") != "1.0":
        raise InvalidInputError("sampled material requires schema_version 1.0")
    try:
        canonical = sample_material_model(samples["source_spec"], samples["wavelength_m"])
        for key in _FIELDS:
            if not np.array_equal(np.asarray(samples[key]), np.asarray(canonical[key])):
                raise InvalidInputError(f"Material samples differ from their reviewed recipe: {key}")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidInputError):
            raise
        raise InvalidInputError(f"Invalid material samples: {exc}") from exc
    frequency = np.asarray(samples["frequency_hz"], dtype=float)
    expected = np.asarray(samples["n_real"]) + 1j * np.asarray(samples["n_imag"])
    permittivity = np.asarray(samples["permittivity_real"]) + 1j * np.asarray(samples["permittivity_imag"])
    sampled_data = np.column_stack((frequency, permittivity))
    temporary = session.addmaterial("Sampled data")
    session.setmaterial(temporary, "name", name)
    session.setmaterial(name, "sampled data", sampled_data)
    readback = np.asarray(session.getmaterial(name, "sampled data"))
    if readback.shape != sampled_data.shape or not np.allclose(readback, sampled_data, rtol=1e-13, atol=1e-13):
        raise ValueError("Native material sampled-data readback differs from the supplied table")
    fitted = np.asarray(session.getfdtdindex(name, frequency, float(frequency.min()), float(frequency.max())))
    if fitted.size != len(frequency) or not np.isfinite(fitted).all():
        raise ValueError("Native FDTD material fit must return one finite complex index per sample")
    fitted = fitted.reshape(len(frequency)).astype(complex)
    error = fitted - expected
    return {
        "material_name": name, "source_samples": copy.deepcopy(samples),
        "frequency_hz": frequency.tolist(), "fitted_n_real": fitted.real.tolist(),
        "fitted_n_imag": fitted.imag.tolist(), "sampled_data_readback_matches": True,
        "max_index_fit_error": float(np.max(np.abs(error))),
        "rms_index_fit_error": float(np.sqrt(np.mean(np.abs(error) ** 2))),
        "max_permittivity_fit_error": float(np.max(np.abs(fitted ** 2 - permittivity))),
        "fitted_minimum_extinction": float(np.min(fitted.imag)),
        "fit_band_hz": [float(frequency.min()), float(frequency.max())],
        "fit_settings": "vendor defaults retained", "physics_accepted": False,
        "limitations": samples["limitations"],
    }


__all__ = ["apply_sampled_material", "sample_material_model"]
