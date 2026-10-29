"""Recipe parity, explicit units/sign, and genuine fitted-material readback."""

import copy

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical.materials import apply_sampled_material, sample_material_model
from photonic_workflow.recipes.materials import li_silicon_1980, malitson_fused_silica_1965


@pytest.mark.parametrize("model", ["li-silicon-1980", "malitson-fused-silica-1965"])
def test_samples_are_the_existing_formula_and_sort_jointly(model):
    wavelengths = [1.55e-6, 1.5e-6, 1.6e-6]
    spec = {"model": model}
    if model == "li-silicon-1980":
        spec["temperature_k"] = 310
    samples = sample_material_model(spec, wavelengths)
    assert samples["wavelength_m"] == list(reversed(sorted(wavelengths)))
    assert samples["frequency_hz"] == sorted(samples["frequency_hz"])
    expected = [li_silicon_1980(w * 1e6, 310)["refractive_index"] if model == "li-silicon-1980"
                else malitson_fused_silica_1965(w * 1e6)["refractive_index"] for w in samples["wavelength_m"]]
    np.testing.assert_array_equal(samples["n_real"], expected)
    np.testing.assert_array_equal(samples["permittivity_real"], np.array(expected) ** 2)
    assert samples["n_imag"] == [0, 0, 0]
    assert samples["time_dependence"] == "exp(-iwt)"
    assert not samples["physics_accepted"]


class Session:
    def __init__(self, fit_error=0.0, corrupt_table=False):
        self.table = None
        self.fit_error = fit_error
        self.corrupt_table = corrupt_table
        self.events = []

    def addmaterial(self, kind):
        self.events.append(("addmaterial", kind))
        return "new_material"

    def setmaterial(self, material, prop, value):
        self.events.append(("setmaterial", material, prop))
        if prop == "sampled data":
            self.table = np.array(value)

    def getmaterial(self, name, prop):
        assert prop == "sampled data"
        return self.table + (1 if self.corrupt_table else 0)

    def getfdtdindex(self, name, frequency, minimum, maximum):
        np.testing.assert_array_equal(frequency, self.table[:, 0].real)
        assert minimum == frequency.min() and maximum == frequency.max()
        # Independent fake vendor readback: a deliberate complex fit residual.
        return np.sqrt(self.table[:, 1]) + self.fit_error


def test_native_table_is_permittivity_and_fit_error_is_measured_not_erased():
    samples = sample_material_model({"model": "li-silicon-1980"}, np.linspace(1.5e-6, 1.6e-6, 21))
    session = Session(fit_error=0.01 + 0.002j)
    fit = apply_sampled_material(session, "shared_core_material", samples)
    assert session.events[0] == ("addmaterial", "Sampled data")
    assert session.table.shape == (21, 2)
    np.testing.assert_array_equal(session.table[:, 0].real, samples["frequency_hz"])
    np.testing.assert_array_equal(session.table[:, 1].real, samples["permittivity_real"])
    assert fit["max_index_fit_error"] == pytest.approx(abs(0.01 + 0.002j))
    assert fit["sampled_data_readback_matches"]
    assert fit["fit_settings"] == "vendor defaults retained"
    assert not fit["physics_accepted"]


def test_tampered_recipe_data_rejected_before_native_creation():
    samples = sample_material_model({"model": "li-silicon-1980"}, [1.5e-6, 1.55e-6, 1.6e-6])
    bad = copy.deepcopy(samples)
    bad["n_real"][0] += 0.1
    session = Session()
    with pytest.raises(InvalidInputError, match="reviewed recipe"):
        apply_sampled_material(session, "safe_material", bad)
    assert session.events == []


def test_vendor_table_mismatch_fails_instead_of_claiming_success():
    samples = sample_material_model({"model": "malitson-fused-silica-1965"}, [1.5e-6, 1.55e-6, 1.6e-6])
    with pytest.raises(ValueError, match="readback differs"):
        apply_sampled_material(Session(corrupt_table=True), "safe_material", samples)


@pytest.mark.parametrize("spec,wavelengths", [
    ({"model": "vendor-material-name"}, [1.5e-6, 1.55e-6, 1.6e-6]),
    ({"model": []}, [1.5e-6, 1.55e-6, 1.6e-6]),
    ({"model": "li-silicon-1980", "temperature_k": 800}, [1.5e-6, 1.55e-6, 1.6e-6]),
    ({"model": "malitson-fused-silica-1965", "temperature_k": 310}, [1.5e-6, 1.55e-6, 1.6e-6]),
    ({"model": "li-silicon-1980"}, [1e-6, 1.05e-6, 1.1e-6]),
    ({"model": "li-silicon-1980"}, [1.5e-6, 1.5e-6, 1.6e-6]),
    ({"model": "li-silicon-1980"}, [1.5e-6, float("nan"), 1.6e-6]),
    ({"model": "li-silicon-1980"}, [True, False, True]),
    ({"model": "li-silicon-1980"}, [1.5e-6, 1.6e-6]),
])
def test_bad_specs_and_out_of_domain_samples_rejected(spec, wavelengths):
    with pytest.raises(InvalidInputError):
        sample_material_model(spec, wavelengths)
