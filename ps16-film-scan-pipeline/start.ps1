param(
    [string]$Config = (Join-Path $PSScriptRoot 'config.json'),
    [ValidateSet('watch', 'once', 'status', 'retry', 'approve', 'prune')]
    [string]$Command = 'watch',
    [string]$GroupId,
    [string]$ApprovalToken,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$pipeline = Join-Path $PSScriptRoot 'pipeline.py'
$pythonExecutable = $null
$pythonPrefix = @()
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    if ($LASTEXITCODE -eq 0) {
        $pythonExecutable = $python.Source
    }
}
if (-not $pythonExecutable) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonExecutable = $launcher.Source
            $pythonPrefix = @('-3')
        }
    }
}
if (-not $pythonExecutable) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) {
        $pythonExecutable = $bundled
    }
}
if (-not $pythonExecutable) {
    throw 'Python 3.10 or newer was not found (py.exe or python.exe).'
}

$arguments = @($pythonPrefix)
$arguments += @($pipeline, '--config', $Config, $Command)
if ($GroupId) {
    $arguments += @('--group-id', $GroupId)
}
if ($ApprovalToken) {
    $arguments += @('--approval-token', $ApprovalToken)
}
if ($DryRun) {
    $arguments += '--dry-run'
}

Push-Location $PSScriptRoot
try {
    & $pythonExecutable @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
