param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [Parameter(Mandatory = $true)]
    [string]$InputFolder,
    [int]$WindowTimeoutSeconds = 20
)

$ErrorActionPreference = 'Stop'
$running = Get-Process -Name 'PixelShift2DNG' -ErrorAction SilentlyContinue
if ($running) {
    throw 'PixelShift2DNG is already running. Close it before starting the intake runner.'
}
$process = Start-Process -FilePath $Executable -ArgumentList @($InputFolder) -PassThru

Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::RootElement
$deadline = [DateTime]::UtcNow.AddSeconds($WindowTimeoutSeconds)
$window = $null

while (-not $window -and [DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 250
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $process.Id
    )
    $window = $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Children,
        $condition
    )
}

if (-not $window) {
    throw "PixelShift2DNG window did not appear within $WindowTimeoutSeconds seconds."
}

$nameCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    'Analyze + Convert All'
)
$button = $window.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants,
    $nameCondition
)
if (-not $button) {
    throw 'Could not find the Analyze + Convert All button.'
}

while (-not $button.Current.IsEnabled -and [DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 250
}
if (-not $button.Current.IsEnabled) {
    throw 'Analyze + Convert All did not become enabled before the timeout.'
}

$pattern = $button.GetCurrentPattern(
    [System.Windows.Automation.InvokePattern]::Pattern
)
$pattern.Invoke()
Write-Output $process.Id
