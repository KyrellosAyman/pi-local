[CmdletBinding()]
param(
    [ValidateSet('optimized', 'standard')][string]$Profile = 'optimized',
    [string]$Python,
    [switch]$Download,
    [switch]$OfflineDependencies,
    [switch]$Audio
)

$ErrorActionPreference = 'Stop'
$nodeVersion = & node --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -ne 'v24.22.3') { throw 'Install Node.js 24.22.3 x64 and open a new PowerShell window.' }
$venv = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venv 'Scripts/python.exe'
$client = Join-Path $PSScriptRoot 'agent-clients-v8'
if (-not $OfflineDependencies) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($PSBoundParameters.ContainsKey('Python')) {
            & $Python -m venv $venv
        } else {
            & py -3.12 -m venv $venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12.16 x64 with Tk, or supply its executable with -Python.' }
    }
}
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { throw 'Create the Pi environment before offline setup.' }
& $venvPython -I -B -c "import platform, sys, tkinter; sys.exit(not ((3, 12, 16) <= sys.version_info[:3] < (3, 13) and platform.machine().upper() == 'AMD64'))"
if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.12.16 x64 or a later 3.12 security update, with Tk. Move an older .venv aside and rerun setup.' }
if (-not $OfflineDependencies) {
    & $venvPython -I -m pip --isolated --disable-pip-version-check install --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($Audio) {
        & $venvPython -I -m pip --isolated --disable-pip-version-check install --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r (Join-Path $PSScriptRoot 'requirements-audio.txt')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & npm ci --prefix $client --registry https://registry.npmjs.org --ignore-scripts --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $venvPython -B -c 'import markdown_it, mcp, psutil, win32com.client'
if ($LASTEXITCODE -ne 0) { throw 'Required Python dependencies are missing.' }
if ($Audio) {
    & $venvPython -I -B -c "import numpy, onnxruntime, sys; sys.exit('CPU provider unavailable' if 'CPUExecutionProvider' not in onnxruntime.get_available_providers() else 0)"
    if ($LASTEXITCODE -ne 0) { throw 'The Pi environment is missing working audio packages. Run setup with -Audio before using offline setup.' }
}
$cli = Join-Path $client 'node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
if (-not (Test-Path -LiteralPath $cli)) { throw 'Install the pinned Node dependencies before offline setup.' }
$setupArguments = @('--profile', $Profile)
if ($Download) { $setupArguments += '--download' }
if ($Audio) { $setupArguments += '--audio' }
& $venvPython -B (Join-Path $PSScriptRoot 'scripts/prepare_assets.py') @setupArguments
exit $LASTEXITCODE
