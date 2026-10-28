# Experimental straight-waveguide and taper native canary

This COMSOL 6.4 Java example builds original geometry. It tests a 2D scalar,
nondispersive bulk-index surrogate (n=2.6/1.45, 1550 nm); it is not a qualified
220 nm SOI EIM or fabrication model.

Run `python run.py --solver-root <licensed-root> --output <new-private-directory>`
for a source review and dry-run plan. Add `--execute` only within an authorized
campaign. The default stops at configuration. Use `--stop-after modes` for
configuration followed by selected-mode acceptance; use `--stop-after solve
--restart <selected_modes.mph> --mode-report <mode_analysis.json>` to resume the
accepted checkpoint. Official compiler/batch entrypoints use four cores, serial
execution and unique runtime directories. The default wall-clock ceiling is
600 seconds; `--total-budget` permits 120..1200 seconds. Externally reviewed
retries retain the first compile's `--campaign-start-epoch`: elapsed repair and
failed-attempt time consume the same campaign budget.

Configuration readback precedes mesh/solve. It checks semantic materials,
geometry and exterior partition. Selected-mode analysis compares neff with an
independent symmetric-slab equation, checks outgoing Ez/Hy relations, unit power,
window decay and the common reflected polar/axial basis. Six sampled eigenpairs
per port are a sampled census, not spectrum completeness. `analyze_modes` only
returns a report and never writes files; its caller persists a fresh report and
CSV profiles. Resume validates checkpoint, native console, report, original Java,
mode-definition hash and the actual recorded parser source. Selected modes are
frozen before a same-model two-source driven sweep. Post-driven acceptance
requires both sources to use the same actual complex Ez/Hy profiles, and each
profile to agree with the bound pre-driven fields. Missing prior evidence fails
an explicit gate. Reports and raw logs carry exact stage/shape/source identities.

Native output contains the four physical complex S entries, signed nonport flux,
material absorption and port flux. Full-domain exports contain complex Ez,
linear/log electric intensity and Poavx/Poavy. Complex Hy is exported at the
ports for modal checks; full-domain complex Hx/Hy is not exported. A driven
checkpoint is saved before postprocessing. Python produces CSVs and field views
and recomputes power balances from native integrals; this is not independent
full-field E/H reintegration. `analyze(..., output_folder=<new directory>)`
keeps new products separate from frozen inputs; `report_name=None` performs no
file writes.

## Local validation status (2026-10-19)

Phase-three's five bounded attempts produced fresh classes, configuration and
selected-mode evidence, then a complete straight two-source driven solve. The
final Java is byte-identical to attempt05's original source, and rendering it
for straight/solve matches the source compiled and executed in that attempt.
Historical failures remain preserved: initial native/configuration/API issues,
a mode-report JSON serialization error, and a driven parser census-inheritance
failure. Attempt04's later mode report was not listed in its original receipt
and has a modification time after that receipt; it is a derived report, not
receipt-bound original acceptance evidence. Every artifact actually listed in
the five receipts still matches its recorded hash.

The final Python repair passed offline counterexample tests and fresh reanalysis
of receipt-bound raw console/checkpoint data. It has not had a new native
end-to-end run. The original 1200-second campaign wall budget expired and was
not reset. Fresh reports live in the private phase-three reanalysis directory;
old reports/receipts were not overwritten during this final reanalysis.
Nominal straight diagnostic gates pass at one mesh and one wavelength; the
approximately 0.67% mismatch between scattering-derived and flux-derived
transmission remains unassigned. Taper was not run in that original campaign.
Later profile-specific diagnostics are described below. No qualified taper,
mesh/material/boundary convergence, PML qualification, broadband phase, group
delay or physical device qualification is established. Runtime artifacts,
installation paths and license configuration remain private.

Process supervision samples registered descendants using PID/create-time
identity, cleans those descendants in `finally`, and confirms sampled exit.
It does not prove Windows Job Object containment of every detached child or
an unconditional operating-system deadline for undiscovered processes.

## Offline quadrature and flux audit (2026-10-20)

`audit.py` is a standalone offline parser, with no native execution option.
`parse_audit(text, stage="audit")` requires complete source/port/q=2,4,6,8
grids, actual source/wavelength and dataset identity, unique numerical nodes,
integration-order readback, coupling/selection entities and finite values.
For preserved historical logs, explicitly select `stage="postprocess"` or
`stage="solve"`; solve permits the two identical boundary readbacks emitted
before driving and before the audit. A missing or malformed record raises
`ValueError`; a numerical gate failure returns `accepted: false`.

The independent `exp(30*y/1[um])` line-integral control is checked against its
analytic value in metres on the measured port bounds. Each source/port must
show nonzero q2 error and improvement to q8 relative error <=1e-5. Physical
integral stability requires q6-to-q8 differences <=1e-5 of the fixed 1 W/m Pin;
Poav/explicit E/H agreement requires <=1e-8. These form `postprocessing_pass`.
The same gate also requires q8 modal power to agree with 1 within 1e-8;
this checks the reported mode normalization, and does not independently
validate driven input power. Low-order mode-power errors remain diagnostic.
The separate `flux_gap_pass` requires receiving-port total flux to agree with
the modal transmission power within 1e-3 Pin. `accepted` combines only these
named gates. It does not establish mesh convergence, independent field
validation, or physical qualification. Signed net-flux/modal differences at
both ports remain in `comparisons`; no fitted renormalization is applied.

The CLI requires `--checkpoint <file> --checkpoint-sha256 <64-hex-digest>
--output <new-directory>`. Without `--console`, it validates the checkpoint,
prints a dry-run plan, and creates no output. Adding `--console <existing-log>
--stage postprocess` parses offline and writes `audit.json` to a new directory;
exit 0 means the named gates pass, 1 means a numerical rejection, and 2 means
invalid inputs. The checkpoint digest is checked before output creation.
Its binding covers the specified file only: the console/checkpoint association
has not been authenticated against native receipts, which the report states
explicitly. Preserve and verify those receipts separately for evidence work.

The preserved phase-four native runs established order effectiveness and
postprocessing stability, while the receiving flux/modal gap remained above
0.1% Pin across the three meshes. This offline path makes that rejection
reproducible. It does not launch another campaign or reset expired budgets.
The Java template and the configure/modes/solve execution interface remain
the phase-three baseline; they do not provide a new audit execution stage.

## Offline symmetric taper profile preparation (2026-10-25)

`python taper_profile.py` prints a JSON-only plan without writing files or
requiring a solver path or license. `--center-width-um W --taper-length-um L`
sets a symmetric double ramp centered at x=7 um, within a fixed 14 um total
length and fixed 0.30 um end widths. This is the existing canary topology,
not a converter between different port widths. Defaults W=0.34 and L=4
produce the exact legacy taper/configure source bytes on the same platform.

The tool accepts finite numbers with `0.30 <= W < 2.4` and `0 <= L < 14`.
Zero length requires W=0.30 and produces a four-vertex rectangle. Positive
length requires distinct representable coordinates around x=7 um; lengths
below floating-point coordinate resolution are rejected. Equal width with
positive length retains the symmetric polygon with collinear vertices.
Equal width describes the same nominal core region; topology, mesh and
scattering equivalence cannot be inferred. Nonfinite values, bools, text supplied
through the Python API, invalid ranges and changed-width zero length fail.

Add `--output <new-directory>` to write only `profile.json` and a
configure-stage `DeviceCanary.java`. Existing paths are rejected before
writes, files are created exclusively, and parent directories must exist.
The JSON records polygon vertices, area, bbox and template/source SHA-256,
with `will_execute=false`, `physics_accepted=false` and native execution
explicitly unperformed. Geometry, area and bbox template anchors must each
occur exactly once; template drift fails even for the default profile.

The W=0.30/L=4 and W=0.30/L=0 controls have undergone a bounded native
configuration check using supplemental audit source. Both passed finalized
areas/bounds, materials, actual port settings/spans and exterior partition
checks. The full model retained respectively 18/22 and 12/16 vertices/edges,
with five domains in each; some boundary IDs changed. No mesh, mode or driven
solve ran. This is evidence for these two configurations, not all custom
profiles or the unmodified generated source's complete execution path.

The generator still only prepares files, so its per-invocation JSON correctly
records native execution as unperformed. The legacy `run.py` uses its fixed
profile; its modes, solve, acceptance and plotting paths must not be presented
as acceptance of custom profiles. A reusable custom-profile pipeline still
needs explicit profile/source/checkpoint identity binding. No ideal scattering
matrix or assumed effective index is used as geometry evidence.

## Profile-bound mode preparation and validation

`profile_modes.py` adds an offline route for custom symmetric profiles. Prepare
a new bundle, then verify its exact profile, generated Java and dependency bytes:

```powershell
python -B profile_modes.py prepare --output NEWDIR --center-width-um 0.30 --taper-length-um 4
python -B profile_modes.py verify --bundle NEWDIR
```

The bundle contains only `profile.json`, `DeviceCanary.java` and `manifest.json`.
The Java is a modes-stage source with a runtime profile identity and geometry,
material and port readbacks. It checks that the selected-mode store precedes
the driven study step. Preparation and verification use the standard library;
they never start a solver. The legacy runner retains its fixed-profile contract.

After a separately authorized native run with preserved execution records:

```powershell
python -B profile_modes.py validate --bundle NEWDIR --run-folder RUN --receipt RUN/supervised_receipt.json
```

Validation requires NumPy and psutil, provided by the package's `comsol` extra.
It verifies a completed modes receipt, hashes and artifact membership for the
actual Java, console and selected-mode checkpoint, plus runtime profile identity
and actual geometry/material/port readbacks. It recomputes the selected-mode
checks and rejects driven-result markers. Hash linkage is local provenance;
it cannot authenticate a receipt if every file and record has been rewritten.

Repeated `(port,y)` samples are inspected before the legacy mode calculation:
the maximum complex E or H spread must be at most `1e-6 * port_peak + 1e-12`
in its respective unit. Significant conflicting traces reject the evidence.
The report records spreads, mode stores/datasets and the original numerical
thresholds. Readiness applies to the identified profile and checkpoint. Six
sampled eigenpairs per port do not prove a complete modal census; accepted mode
evidence does not establish device transmission, broadband or mesh convergence.

Bundles also pin the helper versions. Keep a reviewed producer snapshot with
historical evidence; regenerating a bundle after a helper change does not update
the original execution receipt. Even a formatting-only helper change changes
its byte hash and therefore requires an explicit provenance decision.

The two W=0.30 equal-width controls (L=4 and L=0) completed a bounded native
mode campaign. Both passed the profile, readback and selected-mode conditions:
neff was about 2.1836923 at 1550 nm and the native outward mode power was 1 W/m.
These observations apply to the frozen producer and two identified checkpoints;
they do not validate a nonzero-width-change taper or its driven scattering.

## Profile-bound driven preparation and diagnostics

`profile_driven.py` prepares a separate driven-resume source from identified
selected-mode evidence. It copies the exact checkpoint into a new bundle:

```powershell
python -B profile_driven.py prepare --output NEWDIR --mode-bundle MODE_BUNDLE --mode-run-folder MODE_RUN --mode-receipt MODE_RUN/supervised_receipt.json
python -B profile_driven.py verify --bundle NEWDIR
python -B profile_driven.py validate --bundle NEWDIR --run-folder DRIVEN_RUN --receipt DRIVEN_RUN/supervised_receipt.json
```

The five bundle files are `profile.json`, `DeviceCanary.java`, `input_modes.mph`,
`mode_origin.json` and `manifest.json`. The origin capsule preserves authenticated
raw mode records for current recomputation; neither preparation nor validation
starts a solver. The generated solve branch loads the saved model and asserts
actual geometry, materials, ports, studies and mode stores before resuming its
original driven step. It does not rebuild the geometry on that branch.

For an explicitly reviewed historical producer, add `--producer-snapshot DIR`
and `--producer-manifest FILE`. This separate route authenticates the producer
bytes as data, regenerates the exact original profile and mode Java with the
current trusted generator, and recomputes the mode criteria. It never imports
Python selected by those input paths. The original strict mode verifier still
rejects changed dependencies; there is no implicit historical fallback or
rewriting of the original receipt. Keep original producer identity and current
validator identity in the evidence record.

Driven validation requires a completed receipt, unchanged input checkpoint,
runtime profile/origin identities, geometry readbacks before resume, preserved
mode stores, two sources at 1550 nm, four unique complex S entries and two raw
power records. This fixed COMSOL 6.4 canary protocol also checks the actual
`[freq, PortName]` parameter axis and its four frequency/source values. Explicit
failure/Java exception records invalidate an otherwise complete log.

Results retain raw complex S, target-mode R/T, signed net port/open-boundary
flux, material Qh and conditional closure residuals. `1-R-T` is a target-mode
deficit; it does not identify absorption or radiation. Diagnostic integrity
does not pass the original port/mesh gates. The route is single-wavelength,
2D scalar and profile-specific; a changed-width taper needs its own mode
checkpoint. Independent models also need modal gauge alignment before comparing
complex phase or connecting their S matrices as reusable circuit elements.

A bounded campaign completed this route for the equal-width control and a
default W=0.34/L=4 double ramp, after building the latter's own mode checkpoint.
Both returned complete raw target-mode S and signed flux records at 1550 nm.
The receiving-flux/modal discrepancy remained about 0.67%, above the original
0.1% gate. These observations establish execution and evidence linkage for
those cases; they do not establish converged taper loss or device qualification.

## Offline return-to-center Euler-bend geometry

`bend_profile.py` prepares a new geometry family using the package's existing
symmetric Euler recipe. The four turns are `[theta, -theta, -theta, theta]`,
with 3 um straight leads and a computed central straight. Both ends lie at
y=0, point along +x and span x=0..14 um. Width is measured along the local
normal. The default is theta=15 degrees, minimum radius=3 um and width=0.3 um;
negative theta mirrors the route and theta=0 gives one straight rectangle.

Run from an installed package environment, or make this checkout's `src`
available on `PYTHONPATH` before invoking the example:

```powershell
python -B bend_profile.py
python -B bend_profile.py --turn-angle-deg 0
python -B bend_profile.py --turn-angle-deg 15 --minimum-radius-um 3 --samples 64 --output NEWDIR
```

The default prints a JSON plan. `--output` exclusively creates a new directory
containing `geometry.json` and `geometry_fragment.java`. The fragment creates
four interpolation-curve solids, straight rectangles and a core union; it
assumes an existing 2D geometry sequence named `g` in um. It creates no
materials, ports, studies or solver and does not start COMSOL. It is a geometry
fragment, and cannot be supplied as a `profile_modes.py` taper bundle.

The JSON distinguishes the intended centerline length and strip area from
sampled chord length and polygon area. The recipe's midpoint integration gives
finite constraint points; the central straight depends on that sampled endpoint,
so the total intended length also depends on sampling. Stepwise chord length
can equal the declared arc length; use independent endpoint quadrature and
refinement rather than their difference to assess integration accuracy.
Curvature/offset feasibility and sampled-boundary intersection checks do not
certify the interpolating solid's actual topology or area. Native geometry
readback, selection/material/port identity and this bend's own mode checkpoint
are required before a driven diagnostic. No bend loss, mode readiness or
cross-model phase alignment is established by this offline preparation.

Closed interpolation solids are smooth around their entire perimeter, so their
end caps can differ from the intended flat normal sections. Native checks must
also establish connectivity after the union. See the
[COMSOL interpolation-curve manual](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_geometry.23.050.html)
and `references/smooth-bend-geometry.md` before adapting this configuration.

## Native geometry probe preparation

`bend_geometry.py` prepares a separate geometry-only probe from the identified
bend profile. Preparation and verification are offline; they never compile or
start COMSOL:

```powershell
python -B bend_geometry.py prepare --output NEWDIR
python -B bend_geometry.py prepare --turn-angle-deg 0 --output ZERO_DIR
python -B bend_geometry.py verify --bundle NEWDIR
```

The four files are `geometry.json`, `geometry_fragment.java`,
`BendGeometryProbe.java` and `manifest.json`. The manifest binds their bytes and
the trusted helper/recipe dependencies. Preserve the actual compiled Java,
execution receipt, raw readbacks and saved model in a separately supervised
native run; a verified preparation bundle alone is configuration evidence.

The probe uses the existing 14 by 5 um exterior split at y=+/-1.2 um, the
profile's actual core fragment and a resulting core selection. It reads final
core/background entities, material assignments, areas/bounds, exterior and
geometric port windows. Core end sections come from actual domain-to-boundary
adjacency intersected with those windows. These are geometric selections;
the source creates no physics Port, mesh, mode, study or driven solution.

`BEND_GEOMETRY RECORD` lines contain actual native readbacks, separately from
the input identity. Finalized edge samples support geometry inspection. The
native completion marker records execution; geometry acceptance still needs
the frozen numerical and topology checks. COMSOL area/length measurements use
a rendering-mesh approximation, so preserve that limit when comparing them
with the intended strip or sampled polygon. A saved geometry model is not a
mode checkpoint and cannot be consumed by the taper modes/driven interfaces.

The probe prints the API unit's actual Unicode codepoints as ASCII integers
before its canonical unit label. Only `um`, U+00B5 followed by `m`, and U+03BC
followed by `m` map to `um`; an unknown string remains unsupported. A console
replacement such as `?m` is insufficient evidence of micrometre units. Preserve
both the codepoints and coordinate-range checks, without rescaling the data to
make an ambiguous unit record pass.

A bounded COMSOL 6.4 probe accepted the zero-angle rectangle's final geometry
and material/end-window selections after recording actual unit codepoints
`[181,109]`. The default four-closed-solid bend remained rejected: a finalized
edge point reached y=-0.1505189073 um against the intended -0.15 um lower edge,
exceeding the frozen 0.0001 um contour tolerance. Its core was one final domain,
its end widths were 0.3 um, and its area passed the separate approximation
check; those checks did not cancel the contour failure. The default is retained
as a reproducible candidate and counterexample, with no accepted bend mode or
loss result. Investigate open offset curves with explicit flat end caps before
adopting this construction for precision geometry.
