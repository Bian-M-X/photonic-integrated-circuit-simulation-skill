# Smooth Bend Geometry Notes

Use this reference when a task involves replacing polygonal bend approximations with truly smooth waveguide bends, auditing bend loss, or scanning bend radius while preserving an interferometer path-length difference.

## Preferred 2D COMSOL Construction

For a routed 2D effective-index waveguide with circular bends:

1. Represent the centerline as vertices.
2. For each non-collinear corner, compute two tangent points at distance `R` from the vertex along the incoming and outgoing segments.
3. Replace the corner by an analytic circular arc with center, start angle, and end angle.
4. Build straight core sections as rectangles between tangent points.
5. Build each bend core as an analytic annular sector:
   - create an outer `Circle` sector with radius `R + w/2`;
   - create an inner `Circle` sector with radius `R - w/2`;
   - create a `Difference` with `input = outer`, `input2 = inner`;
   - set `intbnd = off` where internal boundaries are not physically meaningful.
6. Union all straight and bend pieces into one routed waveguide object and contribute it to the cumulative core selection.

This route avoids representing the physical bend edge as many short straight segments. It also makes the centerline length analytic:

```text
L = sum(straight tangent-to-tangent lengths) + sum(abs(delta_angle) * R)
```

For MZI/aMZI/LT-aMZI, recompute detour depth or arm geometry after changing the bend model so that `DeltaL = L2 - L1` remains the target value.

## COMSOL Java API Primitives

Useful documented primitives:

- `Circle` in 2D can create solid disks and circular sectors; `angle` is the sector angle and `rot` is the rotation angle.
- `Difference` subtracts `input2` objects from `input` objects.
- `InterpolationCurve` can create a 2D `solid` object from a table or coordinate vectors. With `rtol=0`, the supplied points are interpolation constraints, and the resulting boundary is a smooth curve rather than a polyline.
- `Fillet` can round selected vertices in 2D, but it depends on reliable vertex selections and may skip or fail if a fillet intersects an edge.
- `ParametricCurve` creates a curve, not a waveguide domain; it is useful for references and diagnostics, but a physical core still needs a domain construction.

## Smooth Euler Bend Construction

Use this route when the user explicitly asks for Euler bends and rejects short-line or polygonal connections.

Hard rule:

- Do not implement the physical Euler bend boundary as `Polygon`, `Polyline`, or many short straight line segments.
- If sampled Euler points are used, they are only constraint points for a COMSOL `InterpolationCurve` with `type=solid`, not the final edge discretization.

Recommended construction:

1. Compute a symmetric Euler centerline for each bend. For total bend angle `theta` and minimum radius `R`, use maximum curvature `1/R` at the midpoint and centerline length `L_euler = 2*R*abs(theta)`.
2. Compute the endpoint displacement of the local Euler bend and its tangent cutback from the original sharp vertex. For a 90 degree bend with `R=5 um`, the cutback is about `9.35048 um`, larger than the `R=5 um` circular-arc cutback.
3. Validate routing clearance segment by segment. A straight segment between two Euler bends must be longer than the sum of the two adjacent cutbacks, with a small numerical margin.
4. Build the waveguide bend domain from offset boundary curves, not from a widened centerline polygon:
   - sample centerline positions and tangents;
   - compute left and right offset boundaries using the local normal and `w/2`;
   - order boundary points as left side forward and right side reversed;
   - create a COMSOL `InterpolationCurve`;
   - set `type = solid`, `source = table` or `vectors`, `rtol = 0`.
5. Build straight waveguide sections as rectangles between Euler tangent points. A tiny overlap, such as `0.02-0.05 um`, can make Boolean union more robust, but the bend itself must remain a smooth interpolation-curve solid.
6. Union all straight and Euler-bend solids, set `intbnd = off` if internal piece boundaries are not physically meaningful, and contribute the union to the cumulative core selection.

Minimal Java pattern for a smooth Euler-bend solid after computing the ordered boundary table:

```java
g.create(tag, "InterpolationCurve");
g.feature(tag).set("type", "solid");
g.feature(tag).set("source", "table");
g.feature(tag).set("table", boundaryTable);
g.feature(tag).set("rtol", 0.0);
g.feature(tag).label("smooth Euler bend core");
```

For interferometers, equalizing bend count is not enough. If the goal is Jones-matrix style arm analysis, report at least:

- L1/L2 bend count;
- L1/L2 total bend angle;
- left/right turn count;
- minimum Euler radius;
- maximum Euler cutback;
- `L1`, `L2`, and `DeltaL` measured along the Euler centerlines.

Recent LT-aMZI Design4 lesson: switching a matched-bend control from circular bends to smooth Euler-bend `InterpolationCurve` solids can strongly improve single-point energy balance, but it may also require larger routing clearance. To isolate the Euler-bend benefit, compare against a circular-bend control with the same enlarged clearance before making a general optimization claim.

## Minimal Java Pattern

```java
g.create(outer, "Circle");
g.feature(outer).set("type", "solid");
g.feature(outer).set("r", radius + 0.5 * width);
g.feature(outer).set("pos", new double[]{cx, cy});
g.feature(outer).set("angle", angleDeg);
g.feature(outer).set("rot", rotDeg);

g.create(inner, "Circle");
g.feature(inner).set("type", "solid");
g.feature(inner).set("r", radius - 0.5 * width);
g.feature(inner).set("pos", new double[]{cx, cy});
g.feature(inner).set("angle", angleDeg);
g.feature(inner).set("rot", rotDeg);

g.create(tag, "Difference");
g.feature(tag).selection("input").set(new String[]{outer});
g.feature(tag).selection("input2").set(new String[]{inner});
g.feature(tag).set("intbnd", "off");
```

See `scripts/emit-analytic-bend-java-helper.py` for a reusable helper skeleton that emits centerline, tangent-point, and annular-sector helper code.

## Validation Sequence

Run a staged comparison before treating the smooth model as the new baseline:

1. Single isolated bend: compare low-step polygon, high-step polygon, and analytic annular sector.
2. If using Euler bends, run a tiny API probe that creates one `InterpolationCurve type=solid` domain and confirms it contributes to a domain selection.
3. Full device single point: preserve the original optical targets such as `DeltaL`, `gap_dc`, `Lc`, and `R_bend`.
4. Full device wavelength sweep: compare `T21`, `S11`, `S11 + T21`, peak positions, approximate FSR, valleys, and weak/strong peak ratio.
5. If routing clearance changed to fit Euler cutbacks, create a same-clearance circular-bend control before attributing gains to Euler bends.
6. Only after the smooth model is stable, scan `R_bend`.

Recent LT-aMZI Design4 lesson: analytic smooth bends are a better geometry baseline, but they do not automatically increase `T21`. A true smooth model may reduce geometry discretization error while revealing that the main loss/imbalance is instead from couplers, boundaries, mesh, or the 2D EIM approximation.

## Reporting Rules

- State whether the geometry is polygonal, high-sampling polygonal, analytic circular-arc, filleted, or parametric.
- For Euler bends, state whether the physical bend domain is `InterpolationCurve type=solid` or a polygonal approximation. Do not call a sampled polygon "fully smooth."
- Report centerline lengths, not only coordinate differences.
- For interferometers, explicitly report `L1`, `L2`, `DeltaL`, and the FSR formula used.
- Do not claim that more arc steps or smoother geometry necessarily means lower loss; verify it with the same port, mesh, boundary, and sweep settings.

### Offline return-to-center control

`examples/comsol-device-canary/bend_profile.py` composes four existing Euler
recipe results and straight leads, including a zero-angle rectangle control.
The recipe integrates midpoint headings in fixed arc-length steps: the sum of
the exported chords can equal its declared arc length without proving endpoint
accuracy. Compare endpoints with independent quadrature under sample refinement.
The central straight uses the sampled x displacement, so the total intended
route length and strip area inherit that sampling dependence.

`InterpolationCurve` with `type=solid` and `rtol=0` interpolates its points but
closes the full perimeter smoothly. Flat ideal end caps and a sampled simple
boundary therefore do not establish the actual solid's topology, join geometry
or area. Verify native connectivity, areas/bounds, material selections and port
spans before using the bend as a mode or driven model. This follows the
[official API properties](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.102.html)
and the [geometry manual's closure and self-intersection guidance](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_geometry.23.050.html).

For an identified geometry-only native probe, use the separate
`examples/comsol-device-canary/bend_geometry.py` prepare/verify route. Its Java
adds the exterior and semantic material selections around the unchanged bend
fragment, then reads finalized entities, measurements and edge coordinates.
Core end sections use actual domain-adjacent boundaries intersected with the
end windows. Keep this geometry checkpoint separate from mode checkpoints.
Area/length readbacks include a rendering-mesh approximation; inspect units,
coverage and native topology before interpreting agreement with an intended
strip or sampled polygon. See the
[official measurement-method limits](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.047.html).

The bounded return-to-center probe supplies a concrete counterexample to
accepting a closed interpolating solid from its point table alone. Its zero-angle
rectangle passed final geometry/material/end-window checks. The default four
closed Euler solids formed one core domain and retained 0.3 um end widths, but
a finalized edge point at x=10.9909846721 um reached y=-0.1505189073 um. That
is about 0.52 nm beyond the intended lower edge, exceeding the declared 0.1 nm
contour tolerance. The area check passed independently. At least this lower-edge
offset is present in actual edge coordinates; the upper measurement-box versus
65-point sample discrepancy remains unresolved. Keep the nonzero construction
rejected for that precision target. Open offset curves and explicit flat caps
are a next construction hypothesis requiring their own native test, not an
already accepted repair or a universal verdict on Euler bends.

## Sources

- COMSOL Java API geometry documentation: `Circle` supports sector angle and rotation properties; `Difference` supports `input` and `input2` Boolean selections.
- Local project evidence: LT-aMZI Design4 true-smooth conversion, single-point check, and 1518-1521 nm dense sweep from 2026-06-09.
