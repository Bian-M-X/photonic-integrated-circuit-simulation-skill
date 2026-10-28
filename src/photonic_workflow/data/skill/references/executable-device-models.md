# Executable device baselines

Use this route for inexpensive complex-amplitude screening before geometry or
field solving. These models take declared effective indices, coupling strengths
and losses as inputs. They do not infer them from a process stack or validate a
fabricated device. `physics_accepted` remains false after successful evaluation.

## Select the implemented capability

| Model ID | Channels | Implemented physics | Important exclusions |
|---|---:|---|---|
| `waveguide` | 2 | Matched propagation and uniform power loss | Geometry-to-index extraction, reflections, roughness prediction |
| `directional-coupler` | 4 | Uniform coupled modes, propagation mismatch, common loss | Geometry-to-coupling calibration, radiation, unequal guide loss |
| `ring-allpass` | 2 | Single-bus traveling-wave feedback | Backscattering, coupler dispersion, thermal/nonlinear response |
| `ring-adddrop` | 4 | Two couplers, unequal arc lengths, uniform propagation loss | Independent arc losses, counterpropagating-mode coupling |
| `bragg-uniform` | 2 | Uniform lossless two-envelope coupled-mode reflector | Strong-grating accuracy, absorption, chirp, Bloch/vector modes |
| `mmi2x2-ideal` | 4 | Ideal symmetric splitter/combiner with declared split, common phase and excess loss | MMI self-imaging, geometry, imbalance phase, reflection, spectral calibration |
| `ybranch-ideal` | 3 | Matched trunk coupled to a declared branch superposition; orthogonal branch combination reflects | Geometry, odd-mode radiation, independent channel loss, spectral calibration |

The two ring variants are distinct models within one device family. There are
seven models here, not seven independent native electromagnetic validations.
Tapers, Y branches, MMIs, crossings, gratings and modulators still require their
appropriate geometry/field/multiphysics routes. An ideal splitter matrix is not
a validated MMI. Existing fixed Hadamard examples have a separate, narrower
2D material-index-surrogate scope.

## Ideal MMI screening contract

`mmi2x2-ideal` represents an ideal four-port circuit element, not a solved
multimode region. Supply `coupling_power` between 0 and 1, nonnegative
`excess_loss_db` (power loss in dB), and finite `phase_rad` (positive means common
phase lag; negative values are allowed). All three inputs are constant over the
requested wavelengths. A constant phase parameter does not model physical
dispersion or establish group delay. Example: `examples/device-models/mmi2x2-ideal.json`.

Order ports as upper-left, lower-left, upper-right, lower-right. Define
`k=coupling_power`, `a=10**(-excess_loss_db/20)` and `g=exp(-i*phase_rad)`:

```text
U = a*g * [[sqrt(1-k), -i*sqrt(k)], [-i*sqrt(k), sqrt(1-k)]]
S = [[0, U^T], [U, 0]]
```

Each zero block is 2 by 2. Reciprocity uses a transpose for the reverse block,
not a conjugate transpose; the shared phase survives reverse propagation.
This convention gives `S=S^T` and `S†S=a²I`. It assumes matched ports, symmetric
splitting and equal excess loss for both orthogonal input combinations. It
does not allocate missing power between radiation, absorption or omitted modes.
The cross-phase choice is a declared local convention, not a phase prediction
for arbitrary MMI geometry or port gauges.

Power ratios alone cannot validate this element. Replacing both cross terms by
positive real amplitudes at k=0.5 preserves each single-input 50:50 power ratio,
but makes the columns nonorthogonal and permits coherent inputs to violate
passivity. Likewise, excess_loss_db=20 still gives a 50:50 split while transmitting
only 1% of total input power. Test complex amplitudes and all input columns,
including actual circuit composition, before relying on an interference result.

The three-port Y-branch model needs its own assumptions: reciprocal,
lossless and matched at every port are incompatible for a complete three-channel
scattering matrix. Reflection, loss or additional channels cannot be silently
discarded just to obtain an ideal splitter.

## Ideal Y-branch screening contract

`ybranch-ideal` orders its ports as `trunk`, `upper`, `lower`. Its parameters
are `coupling_power=k` in [0,1], `excess_loss_db=L` >= 0, and finite signed
`phase_rad=phi`. Here k is the fraction of trunk-input power delivered to the
lower branch before uniform excess loss; it is not a geometry-derived coupling
coefficient. Define `c=sqrt(1-k)`, `s=sqrt(k)`, `a=10**(-L/20)`:

```text
S = a*exp(-i*phi) * [[0, c, s], [c, -s*s, s*c], [s, s*c, -c*c]]
```

The trunk exchanges with the normalized branch combination `u=(c,s)`; the
orthogonal combination `v=(-s,c)` reflects with a relative phase of pi. They
are equal-weight even/odd combinations only at k=0.5. This construction gives
`S=S^T` and `S†S=a²I`. The trunk is matched, while the branches generally reflect.
For k=0.5 and L=0, a single branch input sends power 1/2 to the trunk, 1/4 back
to itself and 1/4 to the other branch. Coherent branch excitation in u combines
into the trunk; excitation in v returns to the branches rather than vanishing.

These are declared ideal channel assumptions, not predictions for an actual
Y-junction. Real odd combinations can radiate, couple to additional modes, or
reflect differently. Uniform attenuation scales all three channel combinations
equally and does not identify a loss mechanism. Parameters are constant across
the requested wavelengths; no geometry or group delay is inferred. Use
`examples/device-models/ybranch-ideal.json` for the executable request.

Deleting the branch reflection block changes the channel physics even if the
trunk-input split ratio is unchanged. Check reverse sources and coherent branch
combinations. Closing two ideal Y branches into a lossless loop can also create
an undetermined internal dark state. Report singular feedback explicitly;
neither arbitrary damping nor a single stable-looking external transmission
establishes a unique internal solution.

## Run and compose

```powershell
photonic device list --json
photonic device evaluate examples/device-models/waveguide.json --json
photonic init my-device-project --json
photonic device export examples/device-models/waveguide.json --project-root my-device-project --output components/waveguide.csv --json
```

From a source checkout, use `python -m photonic_workflow.cli` with `PYTHONPATH=src`
if the installed command points at a different version. Requests have exactly
`schema_version: "1.0"`, `model`, `wavelengths_nm`, and `parameters`. Inspect
`device list` for required parameters. Unknown keys, nonfinite values, boolean
numbers and invalid bounds are errors. Export is a new file under the configured
project root; it never replaces an existing artifact. The response supplies
component metadata and a SHA-256 hash. Save that response with the request.
The returned `sparameters` path is relative to the project root. Place the
assembly manifest at that root, or rebase the path relative to a nested manifest
before using the metadata.

The CSV uses exactly `wavelength_nm,out_port,in_port,s_real,s_imag`, with every
output/input pair present at every wavelength. Use the returned ordered ports,
model level and reference-plane description in the assembly manifest. All
connected components must share wavelength grids, mode definitions, power-wave
normalization and time convention. A matching CSV format does not establish
physical compatibility. See `hierarchical-device-workflow.md` for composition.

## Conventions that must survive reuse

- Time dependence is `exp(+iwt)` and forward propagation `exp(-i beta L)`.
  Positive group delay is `-d arg(S)/d omega` after valid phase unwrapping.
- Loss in dB/cm is **power** loss. An amplitude traversing `L_um` is multiplied
  by `10**(-loss_db_per_cm * L_um / 200000)`.
- The directional coupler uses cross amplitude `-i sin(kappa L)` at zero
  mismatch, with the common propagation phase retained. Its port order is
  upper-left, lower-left, upper-right, lower-right. Mismatch in the reduced
  generator is `(beta_1-beta_2)/2`.
- The add-drop ring declares input, through, add and drop separately. The arc
  fraction locates the second coupler along the forward ring direction. The
  complex drop amplitude depends on that arc; total round-trip loss and phase
  alone cannot determine it. Uniform loss is an explicit assumption.
- A completely disconnected ring has an external straight-through limit.
  This does not establish a finite internal circulating field at a singular
  lossless resonance. These APIs return external scattering only.
- Bragg detuning is relative to `beta_B=pi/period`. The model restores carrier
  phase at physical port planes: transmission includes `exp(-i beta_B L)`,
  right reflection `exp(-2i beta_B L)`. Zero coupling must recover ordinary
  waveguide propagation, not propagation at the detuning alone.

Single-mode channel names are declarations, not a modal census. Several modal
channels on one physical face are a different problem: distinguish physical
boundary partitioning from channel identity, mode normalization and basis
orthogonality. Complete matrix shape alone cannot certify any of those.

## Tests and acceptance

Use independent Hamiltonian eigendecomposition for the directional coupler,
linear feedback equations for rings, and boundary-value ODE integration for
Bragg scattering. For the ideal MMI, use even/odd eigenchannels and coherent
two-stage network interference to check phase and reverse-port conventions.
For the ideal Y, derive the matrix in the orthogonal bright/dark branch basis,
check reverse and coherent branch excitation, and compose actual CSV feedback
networks. Include a closed lossless dark state that must be rejected as singular;
nearby resolvable examples do not establish accuracy for every high-Q network.
Check zero length/coupling, mismatch, critical coupling,
unequal arcs, stopband and band-edge limits; then pass generated matrices through
the actual circuit loader and network elimination. Passivity, reciprocity and
lossless unitarity are necessary model checks, not independent field validation.

Next obtain geometry-specific modal indices/couplings and compare the complex
matrix to a bounded field solve at matching reference planes. For native work,
first close geometry/material/port readback and a straight control; collect
actual source/dataset/wavelength identities and independent power flux. Refine
mesh, port window, domain/absorber and spectral sampling before performance
acceptance. A single-wavelength, single-mesh solve remains diagnostic.

## Primary sources and derivation boundary

- [COMSOL: dielectric slab waveguide](https://doc.comsol.com/6.3/doc/com.comsol.help.models.woptics.dielectric_slab_waveguide/dielectric_slab_waveguide.html): analytic slab dispersion as an independent 2D modal control.
- [COMSOL: directional coupler](https://doc.comsol.com/6.3/doc/com.comsol.help.models.woptics.directional_coupler/directional_coupler.html): supermode beating and explicit modal phases.
- [Bogaerts et al., Silicon microring resonators](https://photonics.intec.ugent.be/download/pub_3105.pdf): traveling-wave all-pass/add-drop power relations and critical coupling.
- [COMSOL: tapered waveguide](https://doc.comsol.com/6.3/doc/com.comsol.help.models.woptics.tapered_waveguide/tapered_waveguide.html): guided-mode projection and radiation accounting; no universal taper transmission formula.
- [Domenech et al., arbitrary-ratio MMI couplers](https://arxiv.org/abs/1405.6025): geometry-specific design and distinction between splitting ratio and excess loss.
- [Bachmann, Besse and Melchior, self-imaging including phase relations](https://doi.org/10.1364/AO.33.003905): the publisher abstract relates image amplitudes and phases to multimode geometry and propagation. The ideal matrix above is our declared circuit model, not a reproduction of that paper's geometry.

The complex signs, port order and Bragg carrier transformation above are local
derivations under the declared convention, not claims that these sources use
identical signs. A high-contrast multilayer DBR is not a direct validation of a
weak integrated-grating coupled-mode approximation.
