# Executable diagnostics before scaling a campaign

Use these checks when accepting exported model observations or diagnosing a
suspect result. They are optional for explanations and unrelated edits. Before
expanding a costly native sweep, check a representative rebuilt model and a
small source/export case. Failure blocks the dependent scan or claim, not other
investigation. These helpers do not execute COMSOL or promote a G/M gate.

## Read-only command and request format

```powershell
photonic audit diagnostics request.json --fail-on-issues --json
```

Use `python -m photonic_workflow.cli` in place of `photonic` when the source checkout
is on `PYTHONPATH`. The root request is exactly
`{"schema_version":"1.0","kind":"geometry|scattering|phase","data":{...}}`
(choose one kind). The command prints JSON; it never writes an artifact. Exit 6
with `--fail-on-issues` means failed or blocked checks, exit 2 means malformed
input. Without that flag, inspect the result status: exit 0 only means the
diagnostic completed. Request size is limited to 2 MB; duplicate keys, unknown
fields, nonfinite numbers and implicit string-to-number conversions are rejected.

Runnable requests live in `examples/diagnostics/`. The installed wheel exposes
the Python functions below and the CLI; repository examples are development
fixtures, not a licensed native validation suite.

## Final geometry and material observations

`kind=geometry` is a **2D readback audit**, with lengths in micrometres and areas
in square micrometres. Supply:

- `length_unit: "um"`;
- `domains`: final domain records with `id`, `area_um2`,
  `bbox_um: [xmin,xmax,ymin,ymax]`, and effective `material` identity;
- `regions`: independent semantic regions with `name`, `domain_ids`, expected
  `material`, `area_interval_um2: [low,high]`, and containing `bbox_interval_um`;
- `expected_neff: [low,high]` and `actual_neff`, or null for a geometry-only
  scope. A requested but missing modal observation is blocked.

Read the **finalized** geometry after booleans and material assignment. Derive
semantic selections from geometry-feature provenance or independently tested
spatial predicates; verify connectivity and intended port intersections. Do not
infer the intended core from the material already assigned to it, a fixed domain
number, or a universal smallest-area rule. Supply a disjoint partition of all
final domains; represent a multicore region by its full domain-ID list.

For a non-self-intersecting constant-width strip with ordinary end caps,
width times centerline length is an area sanity check; it is not a universal
identity for arbitrary unions, tapers or overlapping offsets. Choose explicit
intervals for the actual geometry. Measure the **finished outline**, not only
the recipe's centerline. Interpolating around sharp end caps may overshoot;
inspect sidewalls and end caps separately. Bounding boxes and areas alone do
not establish connectivity or absence of self-intersections.

COMSOL 6.4 provides selection-based geometry measurements and bounding boxes.
Its geometry measures are approximate (rendering tessellation), so exact float
equality is inappropriate; use declared tolerances and a mesh integral when
needed. See the official [measurement API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.047.html)
and [geometry API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.35.html).
The helper consumes an export; it does not query the native model or verify
material tensor/expression values. Retain the readback exporter, native-model
hash, material properties and independent mode baseline alongside the request.

## N-channel conditional scattering diagnostics

`kind=scattering` consumes one wavelength snapshot. Supply `channels` in output
row order, `source_map` mapping each input channel to its actual source ID,
`wavelength_nm`, a nonnegative `tolerance`, `columns`, and `assumptions`.
Each column has exactly `input_channel`, `source_id`, `model_id`, `basis_id`,
`dataset_id`, `wavelength_nm`, and `values` (one `[real,imag]` per output channel).
Column array order is irrelevant; channel/source identity is mandatory. At most
64 channels are accepted. Missing, duplicate, wrong-source, nonfinite and
wrong-wavelength data are rejected; no missing entry is replaced by zero.

Assumptions are explicit true/false/null: `passive`, `reciprocal`, `lossless`,
`complete_channels`, `power_orthonormal`, `source_independent_basis`, and
`reciprocity_paired_basis`, plus an `evidence` list of reviewed references.
The helper records these references but does not open or independently verify
them. Reported pass means **conditional consistency**, not physical acceptance.

The result separates raw numerical metrics, conditions and check statuses:

- Passivity uses the largest singular value only for a declared passive model
  in a source-independent orthonormal power basis. Active models do not fail
  because a column has power above one; their gain/resource accounting needs a
  separate contract.
- Reciprocity uses the absolute Frobenius norm of `S-S^T` only in a reciprocal
  paired input/output convention. A nonreciprocal model skips that criterion.
- Unitarity uses `||S^H S-I||_F` only for a declared lossless system with complete
  channels. An absorptive model or guided submatrix with unobserved radiation
  is not required to be unitary.

For `S'=Uout S Uin` with **fixed unitary** coordinate transformations,
`S'^H S'=Uin^H S^H S Uin`; all singular values are unchanged. Independent
diagonal port rephasings are one such case. Raw symmetry `S=S^T` generally is
not preserved by arbitrary independent input/output rephasing. Source-dependent
output coordinates are different: rotating the second column of the identity
onto the first produces `[[1,1],[0,0]]`, whose largest singular value is sqrt(2).
There need not be a single unitary map for the assembled columns.

Mixed model/basis/dataset contexts therefore block this helper's physical checks.
If separately built models really have proved alignment, transform them into one
documented canonical context first and retain the original columns and alignment
evidence. Finiteness, IDs and a caller assertion alone do not prove alignment.

The old `scattering.two-port-common-basis` recipe v1 remains unchanged. Its
aggregate `within_declared_diagnostic_tolerances` combines all numerical checks;
it is **not an acceptance decision** for lossy, active or nonreciprocal systems.
Use this conditional audit when those distinctions matter. The existing N-port
CSV loader/circuit assembler already checks completeness and declared passivity;
these helpers do not replace its contract or supply missing native projections.

## Near-zero phase and comparison points

`kind=phase` takes ordered `reference` and `candidate` arrays of `[real,imag]`,
`amplitude_floor`, `phase_tolerance_rad`, `complex_tolerance`, and `policy_id`.
Freeze wavelength/target selection, peak estimator, tie rules and interpolation
before producing these arrays; the helper cannot infer coordinate alignment.

It retains every wrapped raw phase difference and absolute complex error. At an
exact zero, phase is null/undefined, never zero. The strict all-entry verdict
is kept alongside a separate amplitude-conditioned verdict; the latter uses
both amplitudes at least the declared floor and returns not-applicable when no
entries qualify. It never overwrites the strict verdict. For epsilon and
epsilon*exp(i theta), the complex error tends to zero with epsilon while phase
error stays theta. New amplitude policies require a new frozen protocol; they
cannot repair a historical strict failure.

## Observed consumption versus a plan

For trusted Python postprocessing use
`photonic_workflow.consumption.capture_transformation(root=..., consumer=...,
inputs={name: relative_path}, output=..., transform=callable,
planned_consumers=(...))`. It hashes and passes the actual input bytes to the
callback, exclusively creates its byte output, and returns a versioned receipt
with consumer-source, input and output fingerprints. Persist that receipt using
a no-overwrite writer. See `examples/diagnostics/trace_transform.py`.

Use `verify_consumption(explicit_root, receipt)` to recheck those fingerprints.
Paths are relative POSIX paths under exactly the supplied root; absolute paths,
parent traversal, symlinks and junctions are rejected. There is no search across
project/arm/stage roots. Missing files under the declared root are explicit
issues, not a silent zero score. Stale `planned_consumers` remain separate
warnings; do not create placeholders or rewrite immutable history after renames.

This records observed I/O through a trusted callback, not proof that every input
causally affected an output or that native COMSOL ran. A forged receipt with
matching hashes cannot be detected by hash checks alone. Review the consumer
and use an independent replay to support semantic-use claims. The association
between the named consumer source file and the supplied callback is caller-declared,
not authenticated by this helper. Files opened by
the callback outside this wrapper are not captured. No JSON field chooses code
to execute, and no solver action is added to MCP.
