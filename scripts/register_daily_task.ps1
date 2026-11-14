<#
.SYNOPSIS
Register or remove the daily certifications vault sync task for the current user.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -PythonPath "C:\path\to\python.exe"
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$TaskName = 'CertificationsVaultDailySync'

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed task $TaskName."
    } else {
        Write-Output "Task $TaskName is not registered."
    }
    return
}

if (-not $PythonPath) { throw 'Pass -PythonPath with the full path to python.exe.' }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python not found: $PythonPath" }
$Cmd = Join-Path $PSScriptRoot 'run_daily_sync.cmd'
if (-not (Test-Path -LiteralPath $Cmd -PathType Leaf)) { throw "Wrapper not found: $Cmd" }

$Python = (Resolve-Path -LiteralPath $PythonPath).Path
$Arguments = '/c "set VAULT_PYTHON={0}&& "{1}""' -f $Python, $Cmd
$Action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -Daily -At '08:15'
$User = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Force `
    -Description 'Commit and push new certificates to main.' | Out-Null
Write-Output "Registered task $TaskName for $User, daily at 08:15."
