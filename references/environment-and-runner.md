# Environment and Batch Runner

Use this reference when a task needs local solver-path setup, Java API automation, batch execution, runtime-directory control, or privacy-safe command previews.

## Core Principle

For a new campaign, compile and export a small representative case in a unique
run directory first. Preserve source and executable fingerprints and require a
fresh successful class plus solver completion/output checks; launcher exit zero
alone may hide an internal Java failure. Read actual dataset, source, wavelength,
coordinate units/ranges and row/case counts instead of trusting plot titles or
filenames. Never reuse an old class/output after a failed compile. Keep failed
attempts in the resource record; a still-running timed-out process continues to
consume actual time even when the billing counter stops.

The skill must not hard-code the author's local installation path. Each user supplies their own licensed solver root through either `-SolverRoot` or `PHOTONIC_SOLVER_ROOT`.

Expected Windows relative files under the solver root:

```text
bin\win64\comsolbatch.exe
bin\win64\comsolcompile.exe
bin\win64\comsol.exe
```

These are compatibility references only. This repository does not include solver binaries, plugins, license files, or proprietary documentation.

## Configure A Local Solver Root

For the current PowerShell session:

```powershell
$env:PHOTONIC_SOLVER_ROOT = 'C:\Path\To\LicensedSolverRoot'
```

For a persistent user-level variable:

```powershell
setx PHOTONIC_SOLVER_ROOT "C:\Path\To\LicensedSolverRoot"
```

Optional runtime directories:

```powershell
$env:PHOTONIC_SOLVER_PREFS = Join-Path $env:TEMP 'photonic-waveguide-solver\prefs'
$env:PHOTONIC_SOLVER_CONFIG = Join-Path $env:TEMP 'photonic-waveguide-solver\config'
$env:PHOTONIC_SOLVER_TMP = Join-Path $env:TEMP 'photonic-waveguide-solver\tmp'
```

For parallel sweeps, use separate runtime directories per worker:

```powershell
$worker = 'worker-001'
$env:PHOTONIC_SOLVER_PREFS = Join-Path $env:TEMP "photonic-waveguide-solver\$worker\prefs"
$env:PHOTONIC_SOLVER_CONFIG = Join-Path $env:TEMP "photonic-waveguide-solver\$worker\config"
$env:PHOTONIC_SOLVER_TMP = Join-Path $env:TEMP "photonic-waveguide-solver\$worker\tmp"
```

## Verify The Installation

Run these checks after setting `PHOTONIC_SOLVER_ROOT`:

```powershell
$root = $env:PHOTONIC_SOLVER_ROOT
Test-Path (Join-Path $root 'bin\win64\comsolbatch.exe')
Test-Path (Join-Path $root 'bin\win64\comsolcompile.exe')
Test-Path (Join-Path $root 'bin\win64\comsol.exe')
```

Expected result: all three commands return `True`. Then run the package probe:

```powershell
photonic solver check --json
```

This proves path-level availability only. A fresh `comsolbatch -version` or the
smoke model below is required to prove that the native entrypoint actually
starts in the current environment; a successful real model remains separate
solver/physics evidence.

If any check returns `False`, ask the user to provide the correct solver root. Do not guess by publishing local machine paths. If searching the machine is necessary, keep results local and do not commit them.

## Preferred Automation Route

Use Java API plus batch execution:

1. Generate or patch a Java source file.
2. Compile it with COMSOL's version-matched `comsolcompile.exe` entrypoint.
3. Run the compiled `.class` with `comsolbatch.exe`.
4. Save the `.mph` model inside the solver-side Java run.
5. Print key metrics to stdout or write CSV/TXT outputs.
6. Use Python or PowerShell outside the solver for aggregation, plotting, and reporting.

Avoid these as first choices:

- `mphserver`, unless the user explicitly needs an interactive service.
- Running standalone Java outside the solver batch runtime.
- Large external config reads inside solver-side Java. Prefer generated source or small embedded parameters.

## Official Compile Pattern

```powershell
$solverRoot = $env:PHOTONIC_SOLVER_ROOT
if (-not $solverRoot) { throw 'Set PHOTONIC_SOLVER_ROOT first.' }

$compiler = Join-Path $solverRoot 'bin\win64\comsolcompile.exe'

& $compiler 'C:\Path\To\ModelSource.java'
if ($LASTEXITCODE -ne 0) { throw "COMSOL compiler failed with exit code $LASTEXITCODE" }
```

Do not manually concatenate every installed plugin JAR unless a reviewed,
version-specific exception requires it. `comsolcompile` is the documented
vendor entrypoint and owns the installed Java classpath and compatibility.

## Batch Pattern

```powershell
$solverRoot = $env:PHOTONIC_SOLVER_ROOT
$prefs = if ($env:PHOTONIC_SOLVER_PREFS) { $env:PHOTONIC_SOLVER_PREFS } else { Join-Path $env:TEMP 'photonic-waveguide-solver\prefs' }
$cfg = if ($env:PHOTONIC_SOLVER_CONFIG) { $env:PHOTONIC_SOLVER_CONFIG } else { Join-Path $env:TEMP 'photonic-waveguide-solver\config' }
$tmp = if ($env:PHOTONIC_SOLVER_TMP) { $env:PHOTONIC_SOLVER_TMP } else { Join-Path $env:TEMP 'photonic-waveguide-solver\tmp' }
$batch = Join-Path $solverRoot 'bin\win64\comsolbatch.exe'

& $batch `
  -prefsdir $prefs `
  -configuration $cfg `
  -tmpdir $tmp `
  -inputfile 'C:\Path\To\ModelSource.class' `
  -outputfile 'C:\Path\To\OutputModel.mph' `
  -batchlog 'C:\Path\To\BatchLog.log'
if ($LASTEXITCODE -ne 0) { throw "batch solver failed with exit code $LASTEXITCODE" }
```

## Helper Script

Use the bundled wrapper for repeatable compile-and-run:

```powershell
.\scripts\invoke-waveguide-java-batch.ps1 `
  -SolverRoot $env:PHOTONIC_SOLVER_ROOT `
  -JavaFile 'C:\Path\To\ModelSource.java' `
  -OutputFile 'C:\Path\To\OutputModel.mph' `
  -BatchLog 'C:\Path\To\BatchLog.log'
```

Privacy-safe preview:

```powershell
.\scripts\invoke-waveguide-java-batch.ps1 `
  -SolverRoot $env:PHOTONIC_SOLVER_ROOT `
  -JavaFile 'C:\Path\To\ModelSource.java' `
  -OutputFile 'C:\Path\To\OutputModel.mph' `
  -BatchLog 'C:\Path\To\BatchLog.log' `
  -DryRun
```

`-DryRun` hides the local solver root by default. Use `-ShowFullPaths` only in
private local debugging. Optional `-Processors 8` passes `-np 8` for this job;
zero leaves the vendor default unchanged. Benchmark core counts and CPU/GPU
choices as described in `comsol-performance.md`; more cores are not always faster.
The wrapper removes a stale target `.class` before
compilation, stops immediately on a nonzero `comsolcompile` exit, requires a
newly generated class file, rejects unchanged stale MPH/log artifacts, and
propagates a nonzero batch exit. The deprecated
`-JavacExecutable` parameter remains an alias for the compiler executable so
existing automation does not fail at argument binding; new callers use
`-CompilerExecutable`. If a class produces COMSOL's single named-model suffix
(`requested_Model.mph`), the wrapper accepts only a unique file created or
changed by the current invocation and normalizes it to the requested output
path. Multiple named outputs or stale files fail closed.

## Direct-Activation Smoke Test

Use `examples/comsol-runtime-smoke/ComsolRuntimeSmoke.java` to prove the local
compiler, batch process, license startup, Java API, and MPH output path without
building a photonic device:

```powershell
$env:PHOTONIC_SOLVER_ROOT = 'C:\Path\To\LicensedSolverRoot'
& .\scripts\invoke-waveguide-java-batch.ps1 `
  -JavaFile .\examples\comsol-runtime-smoke\ComsolRuntimeSmoke.java `
  -OutputFile .\artifacts\comsol-runtime-smoke.mph `
  -BatchLog .\artifacts\comsol-runtime-smoke.log
```

Pass requires a fresh `.class`, `.mph`, and batch log from this invocation plus
zero native exit codes. It proves runtime activation only, not Wave Optics
availability, correct ports, convergence, or physical validity.

## Long-Run Discipline

In an agent or CI host, child processes can inherit a Windows Job configured to
terminate them when the host closes. `Start-Process` and a hidden window do not
prove independence from that job. Keep long runs under an active supervisor;
use completed-stage checkpoints when the host cannot guarantee session survival.
An approved persistent scheduler is a separate deployment choice, not something
the solver runner installs. A short heartbeat after a tool call proves only that
interval, not survival after the chat, host, or machine exits.

- Start with a single wavelength.
- Then run a small wavelength sweep.
- Then run dense sweeps only after geometry, materials, ports, expressions, and datasets are validated.
- If a command times out, inspect output files and the batch log before declaring failure.
- Save summaries for restartability: candidate id, parameters, metrics, output model path, log path, and status.

For a bounded repair campaign, persist one start time across all attempts and
include debugging and waiting in the declared wall-clock budget. A fresh
directory or resumed chat does not restart that budget. At expiry, preserve
completed stages and finish offline analysis; declare any later solver campaign
separately. Sampled PID/descendant supervision is useful but is not equivalent
to Windows Job Object containment.

## Failure Triage

For a Java batch job, record a unique entry marker and a separate completion
marker. A zero batch exit code can accompany a Java-method failure; require the
expected markers and outputs. If the entry marker is absent, inspect the batch
log and task-local `prefs/logs` or workspace metadata before changing model APIs.
A method-execution bridge socket error identifies a startup failure, not a
physics failure or a proven network-policy cause. Compare one execution factor
at a time within the authorized scope; preserve each attempt's logs and avoid
changing global proxy, firewall or solver configuration as a speculative repair.

Native readbacks may use equivalent unit spellings such as `um`, U+00B5 + `m`
or U+03BC + `m`. Check an explicit equivalence set and preserve the original
Unicode code points in ASCII diagnostics when console encoding is lossy. Never
accept a replacement character or wildcard as a valid unit. Retain independent
coordinate and length-integral checks for result datasets.

Use documented typed getters for critical model settings. Do not discover an
unknown property's type by trying every array and matrix getter: an unsupported
conversion can fail inside the native API. Keep optional inventory separate
from required assertions, record unavailable properties as unknown, and retain
the earliest detailed internal error when a top-level Java-class message is
generic.

| Symptom | Likely cause | First action |
|---|---|---|
| `Set PHOTONIC_SOLVER_ROOT first` | no solver root configured | set env var or pass `-SolverRoot` |
| `COMSOL compiler not found` | wrong solver root or different install layout | verify `bin\win64\comsolcompile.exe` |
| `batch executable not found` | wrong solver root or missing batch tool | verify `bin\win64\comsolbatch.exe` |
| compile succeeds but no fresh class | unsupported source or compiler/output mismatch | inspect compiler output and source class name |
| solver-side file read fails | Java security or path policy | embed small config in source or write outputs externally |
| parallel jobs corrupt runtime state | shared prefs/config/tmp | use per-worker runtime dirs |
| public logs expose local machine data | full classpath or absolute paths printed | use `-DryRun` without `-ShowFullPaths` |

## Files That Should Not Be Published By Default

- `.mph`
- `.class`
- `.log`
- solver cache directories
- license files or license-server details
- local path manifests
- private paper PDFs or vendor documentation
- generated plots/data containing confidential project names

Keep reusable workflow instructions public; keep local models, logs, credentials, and license details private unless explicitly cleared for release.
