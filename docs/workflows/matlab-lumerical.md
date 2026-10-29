# MATLAB-Lumerical Workflow

Status: optional MATLAB bridge remains descriptor-only; native Python execution
has a separate implementation and evidence scope.

For direct Lumerical work, use `photonic lumerical discover`, `plan`, `run`,
`export-geometry`, `import-sparameters`, `device-export`, `compare-devices` and
`optimize-step`. The native route does not require
MATLAB. See [Lumerical workflows](../../references/lumerical-workflows.md) for
MODE/FDTD requests, geometry reuse and the complex-S exchange contract. Native
Python success does not validate this MATLAB bridge or additional products.
The [complete device workflow](../../references/lumerical-device-workflow.md)
documents all-source optical extraction and reuse of the existing circuit and
optimization tools.

## Use when

Use this workflow for an audited legacy project or a requirement that
specifically needs the Ansys Lumerical MATLAB API for FDTD, MODE, DEVICE, or
INTERCONNECT. Prefer native supported automation when MATLAB adds no required
value.

## Flow

1. Freeze project alias, fixed script ID, products, monitor/result allowlist,
   inputs, outputs, port order, fidelity, metrics, and tolerances.
2. Probe product version, MATLAB release compatibility, API path alias,
   headless capability, and license availability.
3. Render a dry-run for a registered entrypoint ID; no user function name or
   script string enters MATLAB or Lumerical.
4. Execute only on an authorized machine with isolated runtime and timeout.
5. Capture result JSON, MAT/HDF5, Touchstone/CSV, logs, project hash, producer
   versions, and key metrics.
6. Compare against an independent model or native route where required.

Old API examples are treated as version-specific leads, not compatibility
evidence.

## Gates and claim boundary

Capability discovery does not pass a physics gate. A real accepted mode or
full-wave run may contribute to G1, G2, G4, or G6 only at its declared fidelity
and after port, convergence, and artifact checks. INTERCONNECT evidence remains
circuit level. G8 records version compatibility, entrypoint ID, project/result
hashes, and limitations.

## Capability and phases

- **Phase A:** `MatlabLumericalAdapter` descriptor, input/output contracts,
  monitor/result allowlist policy, capability fields, and dry-run schema.
- **Phase B:** no Lumerical execution is implied; MATLAB data-exchange fixtures
  may be validated independently.
- **Phase C:** licensed API smoke, product-specific parity, timeout/failure
  tests, result inspection, and an explicit adoption decision.

Missing API, product, headless support, or license is reported independently;
one available product does not imply all products are supported.

## No-fake boundary

Do not pass arbitrary Lumerical script text, infer result names, reuse an
unverified old API path, or describe a descriptor/mock result as a solver run.
FDTD, MODE, DEVICE, and INTERCONNECT claims remain distinct.
