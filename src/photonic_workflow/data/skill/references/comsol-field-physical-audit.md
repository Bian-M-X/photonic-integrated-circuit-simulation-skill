# COMSOL Field-Plot Physical Audit

Use this reference whenever a COMSOL mode or driven-field image is used to
debug, validate, compare, or report a photonic model. Image review is a required
diagnostic gate, not a substitute for selections, convergence, S parameters,
or power accounting.

## Freeze The Plot Contract First

Before judging the image, record and visibly confirm:

- model and solution/run identity;
- wavelength or frequency and input source;
- dataset: boundary-mode solution for a port-mode plot, final driven solution
  for a device field plot;
- plotted expression, component/physics tag, units, and whether the scale is
  linear, logarithmic, normalized, clipped, or manually ranged;
- geometry/material overlay, full computational exterior, port locations, and
  PML regions when present;
- phase/time convention for real-part or phase plots.

Reject a cropped or rescaled image as `blocked` when the crop or color range can
hide the background, ports, PML, or leakage channel under review. Inspect at
least one linear intensity map and one logarithmic or deliberately extended
dynamic-range map for confinement and weak radiation.

## Expected Guided-Wave Physics

For a high-index-contrast SOI strip or its documented 2D effective-index
surrogate, the intended guided mode should have its strongest energy density in
the silicon/effective-core region with evanescent tails in the cladding. Exact
component signs and lobe shapes depend on polarization and phase; confinement
does not mean the exterior field must be exactly zero.

For a splitter or interferometer driven from one input, the image should also
be compatible with the declared topology: energy follows connected guides,
coupling occurs in the intended interaction region, outputs are populated in a
way consistent with the numerical port powers, and any radiation leaves through
declared open boundaries or PML.

## Fail-Closed Visual Red Flags

Mark the field-image audit `fail` and return to geometry/selections/physics if
any unexplained item is visible:

- high-amplitude field appears launched across an arbitrary full exterior side
  instead of the intended local waveguide cross-section;
- the guided field is mainly in bulk background while the intended core is weak;
- a mode is concentrated in an unrelated guide, material, boundary, or PML;
- nonphysical discontinuity occurs away from a material, geometry, source, or
  phase discontinuity;
- a geometrically symmetric device shows unexplained large output asymmetry;
- a disconnected region carries guided power;
- strong standing waves fill the exterior without an accounted reflector;
- the image and reported port powers, source column, polarization, or material
  selections are mutually inconsistent.

A vision model or human reviewer must explicitly check these physical red flags.
Do not accept an image merely because it is smooth, colorful, symmetric, or
visually similar to a reference. Colormap saturation, normalization, phase
snapshots, interpolation, crop, and aspect ratio can all conceal errors.

## Required Numeric Crosschecks

Pair image review with:

1. port-mode plots and port-selection entity IDs;
2. exact exterior partition audit: ports are mutually disjoint, ports do not
   overlap open-boundary selections, and ports plus open boundaries cover the
   complete exterior with no extra internal boundary;
3. modal output/reflection powers for the active source;
4. signed non-port exterior flux and material absorption;
5. mesh and open-boundary/PML sensitivity;
6. when practical, integrated core-versus-background energy or a mode-overlap
   measure at representative cross-sections.

The visual and numeric evidence must agree. A plausible image with bad power
closure is not a pass; good-looking S values with a physically impossible field
map are also not a pass.

When direct port flux and modal power disagree, retain both observables and
compare the actual complex fields with the selected mode at the receiving port.
For a port without incoming excitation, compare against the exported complex
transmission coefficient times that outgoing mode under the declared convention.
Do not use this relation unchanged at an excited port containing incident and
reflected fields. Compare E and H separately; a small electric-field residual
does not establish magnetic-field or flux accuracy. Preserve raw S rather than
fitting a scale factor to force agreement.

Unsmoothed exports can contain several values at one coordinate. Measure and
report the spread before any deduplication, especially for H or derivatives.
An average over different traces changes the observation. Sparse sampled-field
quadrature or an averaged-profile L2 residual is not the native finite-element
integral or a demonstrated error bound; identify it as a separate diagnostic.

For a spatial flux diagnostic on an existing solution, declare a fixed direction
for internal cuts rather than reusing exterior boundary normals. In a 2D
out-of-plane electric-field model, the +x time-average flux is
`-0.5*real(Ez*conj(Hy))`; keep its sign for reverse excitation and report any
propagation-direction conversion explicitly. Internal cut flux is not a modal
S parameter. Retain the original port observations when assessing a discrepancy.

Validate a cut dataset's physical coordinates and units using its endpoint
readbacks and a constant-length integral before interpreting field integrals.
Declare the unit of numeric endpoint arrays explicitly; do not infer SI units
from an API's use of doubles. Check integrated `x/1[um]` and `y/1[um]` against
the intended physical location as well as the length. A dimensionally valid
integral can still describe the wrong location or scale.
Split at actual material interfaces and compare the sum with the complete cut;
use a nonpolynomial analytic control and integration-order checks for that
specific evaluation path. Boundary-integral controls do not automatically
validate a newly introduced cut/interpolation path.

Match field sampling to the dataset type. A mesh-oriented `Eval` operation may
reject a `CutLine2D` dataset even when its `IntLine` integrals work. COMSOL's
[Interp API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.082.html)
supports arbitrary datasets. Record interpolation dimension, refinement and
derivative recovery settings; validate returned source and coordinate axes.
Changing the sampling API does not validate the underlying field solution or
make sampled-field quadrature equivalent to the native line integral.
Check nonlinear observables at the sample level too: reconstruct Poynting flux
from the exported complex E/H components and compare with the exported flux
expression at the same source and coordinates. Interpolation of a product and
the product of interpolated components need not coincide; investigate the
evaluation order and traces before assigning a discrepancy to physical loss.
Agreement between two native flux expressions or their line integrals does not
establish this separate sampled-component consistency check.

Separate sampling algebra from field accuracy with a same-point analytic
control, for example export both `y/1[um]` and `(y/1[um])^2` and compare the
second expression with the square of the first. Also compare a complex field's
raw real/imaginary arrays with separately evaluated `real(...)`/`imag(...)`.
A failed analytic product control cannot be explained solely by a magnetic-field
derivative error. Changing result refinement is not a mesh-convergence test.
For explicit interpolation coordinates, record the numeric input and its unit,
then verify returned physical `x` and `y`; a successful coordinate setter or
unchanged geometry length unit alone does not establish the evaluation location.

For component-product consistency, compare a cut's shape sampling with an
explicit-coordinate `Interp` on the actual Solution dataset. Bind the actual
domain entities; Solution datasets use selections rather than `edim`. Validate
all returned physical coordinates for all sources before accepting any field
array. In a tested 2D geometry using um, unscaled geometry-native coordinate
values passed this check, while converting them to metres misplaced the points.
This is a tested path, not a unit guarantee for every result API.
Keep analytic product checks, direct complex-array decoding, nonlinear flux and
component-product flux separate. A valid explicit-point path does not retroactively
validate the cut path. If repeated cut coordinates carry different traces, an
all-domain point evaluation returning one value cannot establish which trace is
appropriate; investigate domain sides before comparing interface derivatives.

For a side-specific check, derive candidate domains from actual material
assignments and finalized geometry, then sample each domain separately with
explicit coordinates. Read back `dom` as well as physical coordinates; an
all-domain result must belong to a domain containing the query point, not just
any globally selected domain. Set and read back `ext=0` when extrapolation is
excluded. Keep requested interface coordinates distinct from rounded bounding
boxes; nearby offsets and the boundary itself answer different questions.
Log units before asserting them, and validate both sources completely before
emitting accepted rows. In the tested 6.4 path, the label variables `PortName`
and `dom` returned empty dimensionless units; this does not justify accepting
empty units for coordinates or fields.

A bounded two-source check at one section returned 56 valid rows across core,
background, two fixed interface offsets and separately selected interface
sides. Component/product/direct flux identities passed, and all-domain versus
single-domain values agreed to roundoff at these points. This checks the local
observation identity; it neither validates every finite-element trace nor
explains the earlier CutLine discrepancy or receiver power gap. Keep failed
and unsupported paths separate from accepted rows, without averaging traces.

A finite transverse window is an open observation surface. Changes of axial
flux along it may include flow through its sides; they cannot alone establish
absorption or radiation loss. A wider cut at the same location measures omitted
axial tail flux, not a boundary-sensitivity test or closed-volume power balance.
Read the actual field discretization separately from the geometry mapping order;
logs describing geometric shape functions do not establish the field FE order
or how derived H fields and derivatives were evaluated.

An independent result parser must verify the observation identity as well as
the numerical grid: stage/completion, dataset/source, actual bounds, cut and
integration-node readbacks, and field schema. Missing metadata, conflicting
failure records or samples outside the declared window invalidate the affected
claim even when the power numbers look plausible. Test these cases against a
complete positive fixture; successful arithmetic on an incomplete fixture is
not evidence that the parser fails closed. Authenticate the raw log separately
against execution receipts and hashes.

## Review Record

Record one of `pass`, `fail`, or `blocked` plus:

```text
plot_artifact:
run_and_dataset:
source_and_wavelength:
expression_scale_units:
geometry_ports_pml_visible:
expected_guided_regions:
observed_confinement_and_leakage:
visual_red_flags:
numeric_crosschecks:
decision_and_next_action:
```

This record supports diagnostic confidence only. Device acceptance still
requires the applicable G1-G8 evidence.
