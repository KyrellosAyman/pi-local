param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PiArguments)

$ErrorActionPreference = 'Stop'
$app = Join-Path $PSScriptRoot 'agent-clients-v8/pi-gui'
$config = Join-Path $app 'runtime-config.json'
if (-not (Test-Path -LiteralPath $config)) {
    throw 'Configure this checkout with configure.py before starting Pi.'
}
$runtime = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
$state = Join-Path $PSScriptRoot '.local/state'
$workspace = Join-Path $PSScriptRoot '.local/workspace'
New-Item -ItemType Directory -Force -Path $workspace | Out-Null
& $runtime.python -B (Join-Path $app 'app.py') --state-dir $state --workspace $workspace @PiArguments
exit $LASTEXITCODE
