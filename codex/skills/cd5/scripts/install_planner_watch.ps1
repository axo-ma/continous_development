param(
    [Parameter(Mandatory=$true)][string]$Project,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Adapter,
    [string]$TaskName = 'CD5 Planner control',
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    exit
}
$projectPath = (Resolve-Path -LiteralPath $Project).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$adapterPath = (Resolve-Path -LiteralPath $Adapter).Path
$controller = Join-Path $PSScriptRoot 'planner_control.py'
# Task runs in the user's interactive session. No elevated principal, credentials,
# network listener, model automation or hidden replacement server is installed.
$parts = @($controller, '--root', $projectPath, 'watch', '--adapter', $adapterPath)
foreach ($part in $parts) {
    if ($part.Contains('"')) { throw 'Quotes in task arguments are unsupported' }
}
$arguments = ($parts | ForEach-Object { '"' + $_ + '"' }) -join ' '
$pythonWindowless = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) {
    throw 'pythonw.exe required to avoid a visible terminal window'
}
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists; inspect it before updating'
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Deterministic CD5 checks; no periodic model turns' | Out-Null
Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,State
