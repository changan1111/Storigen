# Windows install (NOT tested on a real Windows machine yet). Run in PowerShell as Administrator from the program folder:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install_windows.ps1 -User DOMAIN\autoid -Password 'the user password'
# The program runs as a dedicated Windows user who can read the shares. Use UNC paths (\\nas\Playout\INBOX) in autoid.env, not drive letters.
param([Parameter(Mandatory=$true)][string]$User, [Parameter(Mandatory=$true)][string]$Password)
$ErrorActionPreference = "Stop"
$here = (Resolve-Path "$PSScriptRoot\..\..").Path
$py = (Get-Command python -ErrorAction Stop).Source
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; if ($LASTEXITCODE -ne 0) { throw "Python 3.9 or newer is required" }
& $py "$here\autoid.py" init
$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$here\autoid.py`" run" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtStartup
$set     = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0) -StartWhenAvailable
Register-ScheduledTask -TaskName "AutoID" -Action $action -Trigger $trigger -Settings $set -User $User -Password $Password -RunLevel Highest -Force | Out-Null
New-NetFirewallRule -DisplayName "AutoID web" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -ErrorAction SilentlyContinue | Out-Null
# autoid.env holds the secrets: only the service user (and Administrators) may open it. (Added in v9.1, not tried on a real Windows machine yet.)
icacls "$here\autoid.env" /inheritance:r /grant:r "${User}:(M)" "Administrators:(F)" | Out-Null
# a server must never sleep or hibernate while on mains power
powercfg /change standby-timeout-ac 0 | Out-Null; powercfg /change hibernate-timeout-ac 0 | Out-Null
Write-Host "Installed the AutoID task (starts at boot, restarts if it stops). Edit autoid.env, run: python autoid.py doctor, then: Start-ScheduledTask AutoID"
