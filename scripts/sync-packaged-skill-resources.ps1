[CmdletBinding()]
param(
    [switch]$Update
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Split-Path -Parent $PSScriptRoot)
$packageRoot = Join-Path $repositoryRoot 'src\photonic_workflow\data\skill'
$resourceSets = @(
    @{
        Source = Join-Path $repositoryRoot 'examples\lumerical'
        Target = Join-Path $packageRoot 'examples\lumerical'
        Filter = '*.json'
    },
    @{
        Source = Join-Path $repositoryRoot 'examples\native-devices'
        Target = Join-Path $packageRoot 'examples\native-devices'
        Filter = '*.json'
        Names = @('straight.json', 'crossing.json', 'directional-coupler.json', 'mmi2x2.json',
                  'ybranch.json', 'ring.json', 'ring-modulator.json', 'pn-depletion.json')
    },
    @{
        Source = Join-Path $repositoryRoot 'examples\device-models'
        Target = Join-Path $packageRoot 'examples\device-models'
        Filter = '*.json'
        Names = @('waveguide.json', 'directional-coupler.json', 'ring-allpass.json',
                  'ring-adddrop.json', 'bragg-uniform.json', 'mmi2x2-ideal.json', 'ybranch-ideal.json')
    },
    @{
        Source = Join-Path $repositoryRoot 'examples\comsol-device-canary'
        Target = Join-Path $packageRoot 'examples\comsol-device-canary'
        Filter = '*'
        Names = @('README.md', 'DeviceCanary.java', 'run.py', 'audit.py', 'taper_profile.py',
                  'profile_modes.py', 'profile_driven.py', 'bend_profile.py', 'bend_geometry.py')
    },
    @{
        Source = Join-Path $repositoryRoot 'references'
        Target = Join-Path $packageRoot 'references'
        Filter = '*.md'
    },
    @{
        Source = Join-Path $repositoryRoot 'agents'
        Target = Join-Path $packageRoot 'agents'
        Filter = '*-agent.md'
    },
    @{
        Source = Join-Path $repositoryRoot 'examples\comsol-hadamard-inverse'
        Target = Join-Path $packageRoot 'examples\comsol-hadamard-inverse'
        Filter = '*'
        Names = @('README.md', 'HadamardNative.java', 'run.py', 'campaign.py',
                  'analyze.py', 'extract_mask.py', 'plot_results.py',
                  'CvfDiscreteGradientProbe.java', 'check_discrete_gradient.py')
    }
)

$findings = [System.Collections.Generic.List[string]]::new()
foreach ($resourceSet in $resourceSets) {
    $sourceRoot = [System.IO.Path]::GetFullPath($resourceSet.Source)
    $targetRoot = [System.IO.Path]::GetFullPath($resourceSet.Target)
    if (-not $targetRoot.StartsWith(
        [System.IO.Path]::GetFullPath($packageRoot),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Packaged resource target escaped its controlled root: $targetRoot"
    }
    if ($Update) {
        New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
    }

    $sourceFiles = @(
        Get-ChildItem -LiteralPath $sourceRoot -Filter $resourceSet.Filter -File |
            Sort-Object Name
    )
    if ($resourceSet.Names) {
        $sourceFiles = @($sourceFiles | Where-Object { $_.Name -in $resourceSet.Names })
        foreach ($requiredName in $resourceSet.Names) {
            if ($requiredName -notin $sourceFiles.Name) {
                throw "Missing allowlisted example source: $requiredName"
            }
        }
    }
    $sourceNames = @($sourceFiles.Name)
    $targetFiles = @()
    if (Test-Path -LiteralPath $targetRoot -PathType Container) {
        $targetFiles = @(
            Get-ChildItem -LiteralPath $targetRoot -Filter $resourceSet.Filter -File |
                Sort-Object Name
        )
    }

    if ($Update) {
        foreach ($sourceFile in $sourceFiles) {
            Copy-Item -LiteralPath $sourceFile.FullName -Destination $targetRoot -Force
        }
        foreach ($targetFile in $targetFiles) {
            if ($targetFile.Name -notin $sourceNames) {
                $resolvedTarget = [System.IO.Path]::GetFullPath($targetFile.FullName)
                if (-not $resolvedTarget.StartsWith(
                    $targetRoot + [System.IO.Path]::DirectorySeparatorChar,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                    throw "Refusing to remove file outside packaged resource root: $resolvedTarget"
                }
                Remove-Item -LiteralPath $resolvedTarget -Force
            }
        }
        $targetFiles = @(
            Get-ChildItem -LiteralPath $targetRoot -Filter $resourceSet.Filter -File |
                Sort-Object Name
        )
    }

    $targetNames = @($targetFiles.Name)
    foreach ($name in $sourceNames) {
        if ($name -notin $targetNames) {
            $findings.Add("missing packaged resource: $name")
            continue
        }
        $sourceHash = (Get-FileHash -LiteralPath (Join-Path $sourceRoot $name) -Algorithm SHA256).Hash
        $targetHash = (Get-FileHash -LiteralPath (Join-Path $targetRoot $name) -Algorithm SHA256).Hash
        if ($sourceHash -ne $targetHash) {
            $findings.Add("packaged resource differs: $name")
        }
    }
    foreach ($name in $targetNames) {
        if ($name -notin $sourceNames) {
            $findings.Add("unexpected packaged resource: $name")
        }
    }
}

if ($findings.Count -gt 0) {
    $findings | ForEach-Object { Write-Error $_ }
    exit 1
}

$mode = if ($Update) { 'updated and verified' } else { 'verified' }
Write-Output "Packaged skill resources $mode."
