# Run the current checkout, independently of an older installed photonic CLI.
# All trailing arguments are forwarded literally; no shell expression is evaluated.
$ErrorActionPreference = 'Stop'
$sourceRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'src'
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ($previousPythonPath) {
        $sourceRoot + [System.IO.Path]::PathSeparator + $previousPythonPath
    } else {
        $sourceRoot
    }
    & python -B -m photonic_workflow.cli lumerical @args
    $commandExit = $LASTEXITCODE
} finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $previousPythonPath
    }
}
exit $commandExit
