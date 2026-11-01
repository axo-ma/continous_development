param(
    [Parameter(Mandatory=$true)][string]$HomeDirectory,
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [string]$TaskName = 'CD5 Continuator',
    [switch]$PreserveRunEntry
)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$taskHome = (Resolve-Path -LiteralPath $HomeDirectory).Path
$taskPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$taskPythonw = Join-Path (Split-Path -Parent $taskPython) 'pythonw.exe'
$taskRunner = Join-Path $PSScriptRoot 'shared_continuator.py'
$taskGenerator = Join-Path $PSScriptRoot 'continuator_task.py'
if (!(Test-Path -LiteralPath $taskPythonw)) { throw 'pythonw.exe required' }
$taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$taskXml = (& $taskPython -X utf8 $taskGenerator --home $taskHome --runner $taskRunner --pythonw $taskPythonw --user-sid $taskSid) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'Task XML generation failed' }
$taskService = New-Object -ComObject 'Schedule.Service'
$taskService.Connect()
$taskFolder = $taskService.GetFolder('\')
$taskPrevious = $null
try { $taskPrevious = $taskFolder.GetTask($TaskName) } catch {
    $taskException = $_.Exception
    $taskNotFound = $false
    while ($null -ne $taskException) {
        if ($taskException.HResult -eq -2147024894) { $taskNotFound = $true; break }
        $taskException = $taskException.InnerException
    }
    if (!$taskNotFound) { throw }
}
if ($null -ne $taskPrevious) {
    if ($taskPrevious.Xml -notlike '*shared_continuator.py*') { throw 'Existing task is not this Continuator; preserved' }
    [IO.File]::WriteAllText((Join-Path $taskHome ('TASK-BEFORE-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'.xml')), $taskPrevious.Xml)
    $taskOldHome = $taskPrevious.Definition.Actions.Item(1).WorkingDirectory
    if (!$taskOldHome) { throw 'Existing task has no verified working directory; preserved' }
    $taskPrevious.Enabled = $false
    $taskPrevious.Stop(0)
    # Stop is asynchronous. Never mistake its return for proof the old PID exited.
    $taskStopDeadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        $taskOldProcesses = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'shared_continuator.py' -and
            $_.CommandLine.Replace('\','/').Contains($taskOldHome.Replace('\','/'))
        })
        if ($taskOldProcesses.Count -eq 0) { break }
        if ([DateTime]::UtcNow -ge $taskStopDeadline) {
            $taskPrevious.Enabled = $true
            throw 'Previous Continuator has not exited; no parallel replacement started'
        }
        Start-Sleep -Milliseconds 250
    } while ($true)
}
# One task, one action, least privilege, interactive user token; no password stored.
$taskRegistered = $taskFolder.RegisterTask($TaskName,$taskXml,6,$null,$null,3,$null)
[IO.File]::WriteAllText((Join-Path $taskHome 'TASK.xml'),$taskRegistered.Xml)
$taskRunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$taskOldRun = (Get-ItemProperty -LiteralPath $taskRunKey -Name 'CD5 Continuator' -ErrorAction SilentlyContinue).'CD5 Continuator'
$taskRemovedRun = $false
if ($taskOldRun -and !$PreserveRunEntry) {
    $taskNormalized = $taskOldRun.Replace('\','/')
    if ($taskNormalized -notlike '*shared_continuator.py*' -or $taskNormalized -notlike ('*'+$taskHome.Replace('\','/')+'*')) {
        throw 'Unexpected old Run entry preserved; inspect before removing'
    }
    @{value=$taskOldRun} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskHome 'RUN-BEFORE-TASK.json') -Encoding utf8
    Remove-ItemProperty -LiteralPath $taskRunKey -Name 'CD5 Continuator'
    $taskRemovedRun = $true
}
$null = $taskRegistered.Run($null)
$taskReceipt = @{task=$TaskName;installed=$true;started=$true;recovery='Windows Task Scheduler: failure + one-minute repetition';run_entry_removed=$taskRemovedRun;user_sid=$taskSid}
$taskReceipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskHome 'TASK-SETUP.json') -Encoding utf8
$taskReceipt | ConvertTo-Json
