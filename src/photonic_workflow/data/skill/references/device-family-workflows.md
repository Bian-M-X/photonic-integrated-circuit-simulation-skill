# Device-Family Workflows

Use this reference when the target is not specifically an MZI/LT-aMZI, or when the user needs a general integrated-photonics simulation route.

## First Question: What Device Family Is This?

Before building a model, classify the device:

- straight/rib/strip waveguide
- bend, crossing, or transition
- taper or mode converter
- Y-branch, MMI, directional coupler, or splitter
- ring resonator, disk resonator, or coupled resonator
- Bragg grating, photonic crystal, or periodic reflector
- grating coupler or free-space coupling structure
- MZI/aMZI/LT-aMZI or other interferometer
- sensor or modulator
- inverse-design region or topology-optimized splitter

Then choose the smallest validation model that proves the core physics.

For executable analytic/reduced models of straight propagation, directional
coupling, all-pass/add-drop rings and uniform Bragg reflection, use
`executable-device-models.md`. It distinguishes parameterized complex-S
evaluation from geometry construction and native field validation. The family
routes below describe engineering work; they do not imply that every family
already has a native backend or acceptance evidence.

## Universal Validation Ladder

1. Straight waveguide: material, port, mode, mesh, and boundary sanity.
2. Elementary unit: bend, taper, coupler, resonator cell, grating period, or splitter unit.
3. Functional block: complete splitter, ring with bus, Bragg section, MZI, or sensor baseline.
4. Full device: routed and parameterized final topology.
5. Sweep: wavelength, geometry, material perturbation, or drive variable.
6. Audit: energy balance, reflection, loss channel, mesh sensitivity, and boundary sensitivity.

## Waveguide, Bend, And Taper

Straight waveguide:

- validate `S21`, `S11`, mode shape, and phase
- compare against expected effective index when possible
- use this as the first smoke test for every project

Bend:

- compare to a straight reference of comparable length
- sweep bend radius
- refine bend mesh
- inspect radiation into background
- check reflection at bend entry/exit

For an offline return-to-center Euler geometry, use
`examples/comsol-device-canary/bend_profile.py`. It reuses the symmetric Euler
recipe, composes four normal-offset bends with straight leads and keeps both
end tangents along +x. A zero-angle rectangle and sign-mirror control isolate
the geometry change. Intended path/strip area and sampled chord/polygon area
are separate diagnostics. Its fixed interpolation-solid Java fragment has no
materials, ports or solver; sampled nonintersection does not accept the actual
COMSOL interpolant. Verify native geometry and the bend's own mode checkpoint
before interpreting any scattering result. It is separate from taper bundles.

The separate `bend_geometry.py` probe has checked a zero-angle rectangle and the
default four-closed-solid bend in COMSOL. The rectangle passed final semantic
geometry checks. The nonzero bend formed one core and retained correct end
widths/materials, but a native edge exceeded its frozen contour tolerance by
reaching about 0.52 nm beyond the intended lower boundary. Its geometry adoption
remains blocked; an area pass alone does not qualify the contour. Preserve this
counterexample and test a flat-cap/open-offset construction before its own modes.

Taper or transition:

- define input/output widths and target modes
- sweep taper length
- check mode conversion and reflection
- compare field shape before and after taper

The offline `examples/comsol-device-canary/taper_profile.py` prepares the
existing symmetric double-ramp topology with fixed 0.30 um end widths. It can
produce an equal-width control and configure-stage Java with independently
checkable polygon area and bounds. It does not solve, predict transmission or
convert between unequal port widths. A zero-length profile with changed width
is rejected; a zero-length equal-width profile is a rectangle. Custom profiles
still need native geometry readback and a separately bound modal/solve pipeline;
the legacy runner's fixed-profile plots are not evidence for them.

Two equal-width controls have passed bounded native configuration readbacks:
the positive-length collinear polygon and the zero-length rectangle. They had
the same domain areas/materials and port spans but different finalized entity
counts and boundary IDs. Derive selections from the rebuilt geometry and bind
the profile, audited source and checkpoint identities before mode/solve reuse.
Neither configuration check ran a mesh or field solve. Nonzero profiles need
their own modes and driven evidence before any performance acceptance.

`profile_modes.py` prepares a separate modes source and binds its profile,
dependencies, actual geometry readbacks, native receipt and selected checkpoint.
Use its offline validation route before reusing custom-profile mode evidence.
It rejects mismatched files, failed receipt status and driven-result markers,
and checks duplicate complex-field traces before the inherited mode analysis.
The legacy fixed-profile runner is a separate interface; a prepared bundle alone
does not establish mode readiness or authorize a solver run.

The separate `profile_driven.py` route prepares a driven continuation from
identified mode evidence and validates complete two-source target-mode S plus
signed flux observations. It asserts the persisted profile before resuming and
keeps historical producer data distinct from current validation. A changed-width
profile requires its own mode checkpoint. Treat the first driven result as a
bounded diagnostic until its normalization, fields and convergence support the
desired claim; do not identify `1-R-T` as measured loss in a particular channel.

One nonzero double ramp has completed such a single-wavelength diagnostic with
its own mode checkpoint. Its target-mode transmission was close to one, while
the independent receiving-flux/modal gate still failed. Keep both observations
visible; a nearly unit target-mode result alone cannot qualify low loss.

## Splitters And Couplers

Applies to directional couplers, Y-branches, MMI splitters, and custom splitters.

Build standalone before system integration.

Metrics:

```text
T_i1 = abs(Si1)^2
T_sum = sum(T_i1 over intended outputs)
R11 = abs(S11)^2
split_ratio_i = T_i1 / T_sum
imbalance = max(split_ratio_i) - min(split_ratio_i)
uncollected = 1 - T_sum - R11
```

Typical sweeps:

- coupling length
- gap
- MMI width/length
- Y-branch opening angle
- taper length
- bend radius
- wavelength

Acceptance is target-dependent. A 3 dB directional coupler is not the only valid splitter target.

For inexpensive circuit screening, `executable-device-models.md` provides ideal
MMI and Y models with complete complex S. A Y model must account for branch-side
reflection or other channels: reciprocity, losslessness and matching at all
three ports cannot hold simultaneously for a complete three-channel matrix.
Validate reverse excitation and coherent combining, not just the trunk-input
split ratio. These ideal models do not replace geometry-specific verification.

## Resonators

Applies to ring resonators, disk resonators, add-drop filters, and coupled resonator systems.

Core checks:

- bus-ring gap or coupling region
- round-trip loss
- resonance wavelength
- FSR
- extinction ratio
- loaded Q and intrinsic Q when extractable
- through and drop spectra

Use fine wavelength steps around resonances. A coarse sweep can miss narrow resonances entirely.

## Bragg, Periodic, And Photonic Crystal Devices

Core checks:

- period
- duty cycle or corrugation depth
- number of periods
- effective index and Bragg condition
- stopband center
- stopband width
- reflection/transmission spectra
- termination reflections

Start with a short periodic section, then sweep period count and apodization/chirp if relevant.

## Grating Couplers

Grating couplers can require 2D cross-section, 2.5D approximations, or 3D validation depending on the claim.

Core checks:

- coupling efficiency
- bandwidth
- back-reflection
- radiation angle
- polarization sensitivity
- substrate/cladding/PML influence
- fiber or free-space mode overlap, if modeled

Do not claim final coupling efficiency from a simplified 2D approximation unless the limitation is explicit.

## Sensors And Modulators

First build a passive baseline. Then add perturbation or drive.

Possible perturbations:

- analyte or cladding index change
- temperature change
- carrier-induced index/loss change
- electro-optic index change
- mechanical displacement
- geometry variation

Metrics:

- resonance shift
- phase shift
- sensitivity
- insertion loss
- extinction ratio
- bandwidth
- figure of merit

Separate optical-only assumptions from coupled thermal/electrical/mechanical physics.

## Inverse-Design Regions

Use strict selection discipline:

- fixed waveguides are not design variables
- ports are not design variables
- background is not accidentally overwritten
- design region has its own material/selection
- exported masks are previews unless they pass fabrication checks

Useful artifacts:

- density preview
- binary preview
- SVG/PNG layout preview
- CSV mask
- manifest of resolution, threshold, and objective

## Evidence By Device Family

| Device | Minimum evidence |
|---|---|
| straight waveguide | field map, S21/S11, mode profile |
| bend | bend loss vs radius, field leakage check |
| taper | transmission/reflection vs length, output mode check |
| splitter/coupler | split table, excess loss, wavelength tolerance |
| ring | spectrum, resonance extraction, Q/FSR/ER |
| Bragg | reflection/transmission spectrum, stopband extraction |
| grating coupler | coupling efficiency, bandwidth, radiation/PML audit |
| interferometer | field map, sweep fringes, FSR, ER/IL |
| sensor/modulator | baseline, perturbation sweep, sensitivity or phase shift |
| inverse design | objective history, best candidate, robustness and preview |

## General Failure Patterns

- field plot looks plausible but no quantitative sweep exists
- S parameters look plausible but the field is launched across the full outer
  boundary, lives mainly outside the intended core, or conflicts with the
  declared source/topology
- port mode is wrong or evaluated on the wrong dataset
- material selections are lost after geometry rebuild
- boundary or PML absorbs guided power unintentionally
- mesh is too coarse in gap, bend, grating, or resonance region
- wavelength step misses narrow resonance or interference peaks
- optimized structure is not compared against a simple baseline
- 2D approximation is reported as if it were final 3D validation
