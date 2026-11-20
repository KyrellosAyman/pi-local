param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PiArguments)

$ErrorActionPreference = 'Stop'
$app = Join-Path $PSScriptRoot 'agent-clients-v8/pi-gui'
$config = Join-Path $app 'runtime-config.json'
if (-not (Test-Path -LiteralPath $config)) {
    throw 'Configure this checkout with configure.py before starting Pi.'
}
$runtime = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
& $runtime.python -B (Join-Path $app 'app.py') @PiArguments
exit $LASTEXITCODE
