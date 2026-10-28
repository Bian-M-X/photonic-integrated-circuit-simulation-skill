"""Pure analytic/reduced scattering models; no solver or physical acceptance.

The signs and physical reference planes follow the independent derivations in
the Phase 2 source audit. Coefficients are caller inputs, never geometry-derived
or calibrated here. S[wavelength][out][in] contains [real, imaginary] pairs.
"""

from __future__ import annotations

import copy
import csv
import io
import math
from numbers import Real
from typing import Any

from .exceptions import InvalidInputError

_CONVENTION = {
    "time_dependence": "exp(+iwt)",
    "forward_propagation": "exp(-i beta L)",
    "sparameter_normalization": "power-wave",
    "scattering_relation": "b = S a; rows outgoing, columns incoming",
    "wavelength_unit": "nm",
}
_PARAMETERS = {
    "waveguide": ("length_um", "neff", "loss_db_per_cm"),
    "directional-coupler": ("length_um", "neff_1", "neff_2", "kappa_per_um", "loss_db_per_cm"),
    "ring-allpass": ("roundtrip_length_um", "neff", "loss_db_per_cm", "coupling_power"),
    "ring-adddrop": (
        "roundtrip_length_um", "neff", "loss_db_per_cm", "coupling_power_1", "coupling_power_2", "arc_fraction",
    ),
    "bragg-uniform": ("length_um", "neff", "period_um", "kappa_per_um"),
    "mmi2x2-ideal": ("coupling_power", "excess_loss_db", "phase_rad"),
    "ybranch-ideal": ("coupling_power", "excess_loss_db", "phase_rad"),
}
_PORTS = {
    "waveguide": ("left", "right"),
    "directional-coupler": ("upper_left", "lower_left", "upper_right", "lower_right"),
    "ring-allpass": ("input", "through"),
    "ring-adddrop": ("input", "through", "add", "drop"),
    "bragg-uniform": ("left", "right"),
    "mmi2x2-ideal": ("upper_left", "lower_left", "upper_right", "lower_right"),
    "ybranch-ideal": ("trunk", "upper", "lower"),
}
_COMMON_LIMITS = [
    "Caller-supplied modal indices, coupling and loss are uncalibrated inputs; geometry and materials are not solved.",
    "Scalar coefficients are held constant over the supplied wavelengths; dispersion must be externally justified.",
    "No native field, modal completeness, convergence, fabrication, measured performance or device gate is accepted.",
    "A finite wavelength grid does not establish a continuous-band or high-Q spectral guarantee.",
]
_SPECIFIC = {
    "waveguide": ["Matched reciprocal single-mode propagation; no reflections, radiation or mode conversion."],
    "directional-coupler": [
        "Two-mode constant real symmetric coupled-mode generator; equal uniform loss on both guides.",
        "No backward coupling, interface reflection, extra guided modes or radiation; "
        "mismatch is HALF beta difference.",
    ],
    "ring-allpass": [
        "Traveling-wave ring with lossless local -i cross coupler; no backscattering or mode splitting.",
        "Zero coupling gives external direct transmission even at an isolated internal resonance; "
        "no buildup is inferred.",
    ],
    "ring-adddrop": [
        "Two lossless local -i cross couplers; uniform propagation loss and index on both arcs.",
        "arc_fraction is the upper-to-lower forward arc fraction; "
        "the reverse physical sources use reverse circulation.",
        "No backscattering or mode splitting; disconnected internal modes do not imply finite internal buildup.",
    ],
    "bragg-uniform": [
        "Uniform lossless two-envelope coupled-mode approximation with real nonnegative coupling.",
        "Physical local field reference planes include the beta_B=pi/period carrier gauge, not envelope gauges.",
        "Weak-grating validity and coefficients require independent calibration; no high-contrast stack equivalence.",
    ],
    "mmi2x2-ideal": [
        "Ideal symmetric 2x2 mixing matrix with -i cross amplitude; positive phase_rad is common phase lag.",
        "No MMI self-imaging, geometry, multimode propagation, dispersion or group delay is predicted.",
        "Port basis and phase convention are declared; physical reference-plane calibration is not established.",
        "Uniform excess loss is a power deficit, not an identified radiation or absorption channel.",
    ],
    "ybranch-ideal": [
        "Ideal reciprocal three-port junction; coupling_power is the trunk-to-lower power fraction before loss.",
        "The trunk is matched; branch inputs generally reflect. "
        "Branch bright and dark channels depend on coupling_power.",
        "Positive phase_rad is common phase lag; the branch dark channel reflects with an additional pi phase.",
        "No geometry, modal conversion, dispersion, group delay or loss mechanism is predicted.",
        "Port basis and phase convention are declared; physical reference-plane calibration is not established.",
        "Uniform excess loss is a power deficit, not an identified radiation or absorption channel.",
    ],
}


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InvalidInputError(f"{name} must be a finite real number, not a boolean")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidInputError(f"{name} must be representable as a finite number") from exc
    return _finite(result, name)


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise InvalidInputError(f"{name}: nonfinite numerical intermediate or result; rescale the inputs")
    return value


def _exact(data: Any, keys: set[str], name: str) -> dict:
    if not isinstance(data, dict):
        raise InvalidInputError(f"{name} must be an object")
    if set(data) != keys:
        raise InvalidInputError(f"{name} fields mismatch; missing={sorted(keys - set(data))}, "
                                f"unknown={sorted(set(data) - keys, key=str)}")
    return data


def _wavelengths(values: Any) -> list[float]:
    if not isinstance(values, list) or not 1 <= len(values) <= 256:
        raise InvalidInputError("wavelengths_nm must contain between 1 and 256 wavelengths")
    result = [_number(value, f"wavelengths_nm[{i}]") for i, value in enumerate(values)]
    if any(value <= 0 for value in result):
        raise InvalidInputError("wavelengths_nm values must be positive")
    if len(set(result)) != len(result):
        raise InvalidInputError("wavelengths_nm must not contain duplicates")
    return result


def _parameter_contract(name: str) -> dict[str, Any]:
    unit = "1"
    if name.endswith("_um"):
        unit = "um^-1" if name == "kappa_per_um" else "um"
    elif name == "loss_db_per_cm":
        unit = "dB/cm (power attenuation)"
    elif name == "excess_loss_db":
        unit = "dB (power insertion loss)"
    elif name == "phase_rad":
        unit = "rad (positive phase lag)"
    result: dict[str, Any] = {"required": True, "type": "number", "unit": unit}
    if name == "phase_rad":
        return result
    if name.startswith("neff") or name == "period_um":
        result["exclusive_minimum"] = 0.0
    elif name == "arc_fraction":
        result.update(exclusive_minimum=0.0, exclusive_maximum=1.0)
    else:
        result["minimum"] = 0.0
        if name.startswith("coupling_power"):
            result["maximum"] = 1.0
    return result


def list_models() -> list[dict[str, Any]]:
    """Return detached JSON-safe descriptors for the seven fixed model IDs."""
    return [{
        "model": model,
        "model_version": "1.0.0",
        "model_level": "analytic" if model in {"waveguide", "mmi2x2-ideal", "ybranch-ideal"} else "reduced",
        "parameters": {name: _parameter_contract(name) for name in names},
        "port_order": list(_PORTS[model]),
        "limitations": [*_COMMON_LIMITS, *_SPECIFIC[model]],
    } for model, names in _PARAMETERS.items()]


def _parameters(model: str, values: Any) -> dict[str, float]:
    _exact(values, set(_PARAMETERS[model]), "parameters")
    result = {name: _number(values[name], name) for name in _PARAMETERS[model]}
    for name, value in result.items():
        if name == "phase_rad":
            valid = True  # _number already requires a finite real value.
        elif name.startswith("neff") or name == "period_um":
            valid = value > 0.0
        elif name == "arc_fraction":
            valid = 0.0 < value < 1.0
        elif name.startswith("coupling_power"):
            valid = 0.0 <= value <= 1.0
        else:
            valid = value >= 0.0
        if not valid:
            raise InvalidInputError(f"{name} outside its declared parameter bounds")
    return result


def _beta(neff: float, wavelength_nm: float) -> float:
    wavelength_um = _finite(wavelength_nm / 1000.0, "wavelength in um")
    if wavelength_um == 0:
        raise InvalidInputError("wavelength in um underflowed to zero")
    return _finite((neff / wavelength_um) * math.tau, "propagation constant")


def _phase(value: float) -> complex:
    _finite(value, "propagation phase")
    # Reduction also makes exact numerical multiples of tau reproducible.
    phase = math.remainder(value, math.tau)
    return complex(math.cos(phase), -math.sin(phase))


def _log_attenuation(loss: float, length: float) -> float:
    # 10**(-loss[dB/cm] * L[um] / 10000 / 20) is field attenuation.
    return -_finite(loss * (math.log(10) / 200000.0) * length, "amplitude attenuation exponent")


def _propagate(beta: float, length: float, log_amplitude: float) -> complex:
    return math.exp(log_amplitude) * _phase(_finite(beta * length, "propagation phase"))


def _zeros(n: int) -> list[list[complex]]:
    return [[0j for _ in range(n)] for _ in range(n)]


def _matched(transfer: complex) -> list[list[complex]]:
    return [[0j, transfer], [transfer, 0j]]


def _waveguide(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    length = p["length_um"]
    return _matched(_propagate(_beta(p["neff"], wavelength), length,
                               _log_attenuation(p["loss_db_per_cm"], length)))


def _directional_coupler(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    b1, b2 = (_beta(p[key], wavelength) for key in ("neff_1", "neff_2"))
    average, delta = b1 / 2 + b2 / 2, b1 / 2 - b2 / 2
    kappa, length = p["kappa_per_um"], p["length_um"]
    q = _finite(math.hypot(delta, kappa), "coupling beat frequency")
    beat = _phase(_finite(q * length, "coupling beat phase"))
    cosine, sine = beat.real, -beat.imag
    phase = _propagate(average, length, _log_attenuation(p["loss_db_per_cm"], length))
    d = sine * (delta / q) if q else 0.0
    cross = -1j * sine * (kappa / q) if q else 0j
    u = [[phase * complex(cosine, -d), phase * cross],
         [phase * cross, phase * complex(cosine, d)]]
    matrix = _zeros(4)
    for row in range(2):
        for column in range(2):
            matrix[row + 2][column] = matrix[column][row + 2] = u[row][column]
    return matrix


def _log_self(coupling: float) -> float:
    return 0.5 * math.log1p(-coupling) if coupling < 1 else -math.inf


def _mmi2x2_ideal(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    # Constant coefficients at every requested wavelength. Form the exponent
    # with a factor below one so even the largest finite loss can underflow
    # cleanly to zero without an avoidable intermediate overflow.
    amplitude = math.exp(-p["excess_loss_db"] * (math.log(10) / 20))
    # libm reduces the original angle accurately even at large finite values;
    # an explicit remainder against rounded tau would lose that information.
    phase = p["phase_rad"]
    factor = amplitude * complex(math.cos(phase), -math.sin(phase))
    through = factor * math.sqrt(1 - p["coupling_power"])
    cross = factor * complex(0, -math.sqrt(p["coupling_power"]))
    # S = [[0, U.T], [U, 0]]: reciprocity uses transpose, not conjugate.
    return [[0j, 0j, through, cross], [0j, 0j, cross, through],
            [through, cross, 0j, 0j], [cross, through, 0j, 0j]]


def _ybranch_ideal(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    # Constant coefficients; retain libm's reduction of the original finite
    # phase and allow the largest finite excess loss to underflow cleanly.
    amplitude = math.exp(-p["excess_loss_db"] * (math.log(10) / 20))
    phase = p["phase_rad"]
    factor = amplitude * complex(math.cos(phase), -math.sin(phase))
    c, s = math.sqrt(1 - p["coupling_power"]), math.sqrt(p["coupling_power"])
    # Exchange trunk and bright branch channel (c,s); reflect dark (-s,c)
    # with phase pi. The branch block is required for reciprocal unitarity.
    return [[0j, factor * c, factor * s],
            [factor * c, -factor * s * s, factor * s * c],
            [factor * s, factor * s * c, -factor * c * c]]


def _exp_difference(left: float, right: float) -> float:
    """exp(left)-exp(right), retaining differences near unity, including zero t."""
    if left == right:
        return 0.0
    if left > right:
        return math.exp(left) * -math.expm1(right - left)
    return math.exp(right) * math.expm1(left - right)


def _resonance_terms(phase: float) -> complex:
    # 1-exp(-i phase), avoiding 1-cos cancellation at high finesse.
    angle = math.remainder(_finite(phase, "roundtrip phase"), math.tau)
    return complex(2 * math.sin(angle / 2) ** 2, math.sin(angle))


def _ring_denominator(log_product: float, terms: complex) -> complex:
    denominator = -math.expm1(log_product) + math.exp(log_product) * terms
    if denominator == 0:
        raise InvalidInputError("ring feedback is numerically singular; coupling/loss is below numerical resolution")
    return denominator


def _allpass_transfer(coupling: float, log_loss: float, phase: float) -> complex:
    if coupling == 0:
        # The external bus is disconnected from the possibly singular internal mode.
        return 1 + 0j
    log_t = _log_self(coupling)
    terms = _resonance_terms(phase)
    denominator = _ring_denominator(log_t + log_loss, terms)
    numerator = _exp_difference(log_t, log_loss) + math.exp(log_loss) * terms
    return numerator / denominator


def _ring_allpass(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    length = p["roundtrip_length_um"]
    phase = _finite(_beta(p["neff"], wavelength) * length, "roundtrip phase")
    log_loss = _log_attenuation(p["loss_db_per_cm"], length)
    return _matched(_allpass_transfer(p["coupling_power"], log_loss, phase))


def _ring_adddrop(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    length, fraction = p["roundtrip_length_um"], p["arc_fraction"]
    phase = _finite(_beta(p["neff"], wavelength) * length, "roundtrip phase")
    log_loss = _log_attenuation(p["loss_db_per_cm"], length)
    k1, k2 = p["coupling_power_1"], p["coupling_power_2"]
    if k1 == 0 or k2 == 0:
        u11 = _allpass_transfer(k1, log_loss, phase)
        u22 = _allpass_transfer(k2, log_loss, phase)
        u12 = u21 = 0j
    else:
        lt1, lt2 = _log_self(k1), _log_self(k2)
        terms = _resonance_terms(phase)
        denominator = _ring_denominator(lt1 + lt2 + log_loss, terms)
        u11 = (_exp_difference(lt1, lt2 + log_loss) + math.exp(lt2 + log_loss) * terms) / denominator
        u22 = (_exp_difference(lt2, lt1 + log_loss) + math.exp(lt1 + log_loss) * terms) / denominator
        factor = -math.sqrt(k1) * math.sqrt(k2) / denominator
        u21 = factor * math.exp(log_loss * fraction) * _phase(phase * fraction)
        u12 = factor * math.exp(log_loss * (1 - fraction)) * _phase(phase * (1 - fraction))
    # Physical order [input, through, add, drop]. Reverse circulation enforces
    # S symmetry, even though the unequal-arc forward transfer U is asymmetric.
    return [[0j, u11, 0j, u21], [u11, 0j, u12, 0j],
            [0j, u12, 0j, u22], [u21, 0j, u22, 0j]]


def _bragg_uniform(wavelength: float, p: dict[str, float]) -> list[list[complex]]:
    beta = _beta(p["neff"], wavelength)
    carrier_beta = _finite(math.pi / p["period_um"], "Bragg carrier propagation constant")
    delta = _finite(beta - carrier_beta, "Bragg detuning")
    kappa, length = p["kappa_per_um"], p["length_um"]
    if kappa == 0:
        return _matched(_phase(_finite(beta * length, "propagation phase")))
    absolute = abs(delta)
    if kappa > absolute:
        s = _finite(math.sqrt(kappa - absolute) * math.sqrt(kappa) * math.sqrt(1 + absolute / kappa),
                    "Bragg stopband frequency")
        x = _finite(s * length, "Bragg stopband exponent")
        h_scaled = length * (math.tanh(x) / x) if x else length
        denominator = complex(1, _finite(delta * h_scaled, "Bragg scaled detuning"))
        decay = math.exp(-x)
        sech = 2 * decay / (1 + decay * decay)
        transmission = sech / denominator
        reflection = complex(0, -_finite(kappa * h_scaled, "Bragg scaled coupling")) / denominator
    else:
        if absolute == kappa:
            cosine, h = 1.0, length
        else:
            q = _finite(math.sqrt(absolute - kappa) * math.sqrt(absolute) * math.sqrt(1 + kappa / absolute),
                        "Bragg passband frequency")
            x = _finite(q * length, "Bragg passband phase")
            oscillation = _phase(x)
            cosine = oscillation.real
            h = length * (-oscillation.imag / x) if x else length
        denominator = complex(cosine, _finite(delta * h, "Bragg detuning term"))
        if denominator == 0:
            raise InvalidInputError("Bragg transfer denominator is numerically singular")
        transmission = 1 / denominator
        reflection = complex(0, -_finite(kappa * h, "Bragg coupling term")) / denominator
    carrier = _phase(_finite(carrier_beta * length, "Bragg carrier phase"))
    physical_t = transmission * carrier
    return [[reflection, physical_t], [physical_t, reflection * carrier * carrier]]


_EVALUATORS = {
    "waveguide": _waveguide,
    "directional-coupler": _directional_coupler,
    "ring-allpass": _ring_allpass,
    "ring-adddrop": _ring_adddrop,
    "bragg-uniform": _bragg_uniform,
    "mmi2x2-ideal": _mmi2x2_ideal,
    "ybranch-ideal": _ybranch_ideal,
}


def evaluate_device(request: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a strict v1 request, preserving its wavelength order and units."""
    _exact(request, {"schema_version", "model", "wavelengths_nm", "parameters"}, "request")
    if request["schema_version"] != "1.0":
        raise InvalidInputError("schema_version must be exactly '1.0'")
    model = request["model"]
    if not isinstance(model, str) or model not in _PARAMETERS:
        raise InvalidInputError("unknown device model")
    wavelengths = _wavelengths(request["wavelengths_nm"])
    parameters = _parameters(model, request["parameters"])
    matrices = []
    for wavelength in wavelengths:
        try:
            matrix = _EVALUATORS[model](wavelength, parameters)
            pairs = [[[_finite(value.real, "S real amplitude"), _finite(value.imag, "S imaginary amplitude")]
                      for value in row] for row in matrix]
        except (OverflowError, ZeroDivisionError, ValueError) as exc:
            if isinstance(exc, InvalidInputError):
                raise
            raise InvalidInputError(f"{model}: numerical evaluation failed; check input scales") from exc
        matrices.append(pairs)
    descriptor = next(item for item in list_models() if item["model"] == model)
    return {
        "schema_version": "1.0", "model": model, "model_version": "1.0.0",
        "wavelengths_nm": wavelengths, "parameters": parameters,
        "port_order": list(_PORTS[model]), "s_matrices": matrices,
        "convention": copy.deepcopy(_CONVENTION),
        "reference_planes": {port: ("Declared ideal port basis; physical reference-plane calibration not established"
                                   if model in {"mmi2x2-ideal", "ybranch-ideal"} else
                                   "Local physical power-wave amplitude at the component endpoint/coupler plane")
                             for port in _PORTS[model]},
        "assumptions": ["Single selected power-normalized mode per physical port; reciprocal passive coefficients.",
                        *_SPECIFIC[model]],
        "validity": {"parameter_contract": descriptor["parameters"],
                     "wavelengths_nm": wavelengths.copy(), "calibration": "not established",
                     "scope": "analytic/reduced screening under declared assumptions only"},
        "limitations": descriptor["limitations"], "model_level": descriptor["model_level"],
        "physics_accepted": False, "will_execute": False,
    }


def scattering_csv(result: dict[str, Any]) -> str:
    """Export exact assembly-v1 five-column complete complex S data as text.

    The caller owns any secure file creation. Export is not evidence promotion.
    """
    if not isinstance(result, dict) or result.get("schema_version") != "1.0":
        raise InvalidInputError("expected a device-model result with schema_version '1.0'")
    model = result.get("model")
    if not isinstance(model, str) or model not in _PORTS:
        raise InvalidInputError("unknown result model")
    ports = list(_PORTS[model])
    if result.get("port_order") != ports or result.get("convention") != _CONVENTION:
        raise InvalidInputError("result port order or scattering convention mismatch")
    if result.get("physics_accepted") is not False or result.get("will_execute") is not False:
        raise InvalidInputError("device export cannot claim execution or physical acceptance")
    wavelengths = _wavelengths(result.get("wavelengths_nm"))
    matrices = result.get("s_matrices")
    if not isinstance(matrices, list) or len(matrices) != len(wavelengths):
        raise InvalidInputError("one complete S matrix is required per wavelength")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("wavelength_nm", "out_port", "in_port", "s_real", "s_imag"))
    for wavelength, matrix in zip(wavelengths, matrices, strict=True):
        if not isinstance(matrix, list) or len(matrix) != len(ports):
            raise InvalidInputError("S matrix has incorrect output-channel count")
        for out_index, row in enumerate(matrix):
            if not isinstance(row, list) or len(row) != len(ports):
                raise InvalidInputError("S matrix has incorrect input-channel count")
            for in_index, value in enumerate(row):
                if not isinstance(value, list) or len(value) != 2:
                    raise InvalidInputError("S amplitudes must be [real, imaginary] pairs")
                real, imaginary = (_number(v, "S amplitude") for v in value)
                writer.writerow((wavelength, ports[out_index], ports[in_index], real, imaginary))
    return output.getvalue()


__all__ = ["evaluate_device", "list_models", "scattering_csv"]
