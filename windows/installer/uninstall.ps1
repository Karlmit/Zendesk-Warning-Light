<#
    Removes Zendesk Warning Light for the current user.

    Invoked by Settings > Apps, or run directly. Because this script lives inside the
    folder it deletes, it relaunches itself from the temp directory first.

    Usage:
        .\uninstall.ps1                  # remove the app, keep settings and logs
        .\uninstall.ps1 -RemoveSettings  # also delete %APPDATA%\ZendeskWarningLight
#>
[CmdletBinding()]
param(
    [switch]$RemoveSettings,
    [switch]$Relaunched
)

$ErrorActionPreference = 'Stop'

$AppName      = 'Zendesk Warning Light'
$AppId        = 'ZendeskWarningLight'
$InstallDir   = Join-Path $env:LOCALAPPDATA "Programs\$AppId"
$DataDir      = Join-Path $env:APPDATA $AppId
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$RunKey       = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$StartMenu    = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"
$Desktop      = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"

# --- run from temp so we can delete our own folder -------------------------

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Relaunched -and $here -eq $InstallDir) {
    # Unique name, so nothing can pre-plant or swap a predictable script path.
    $copy = Join-Path $env:TEMP ("$AppId-uninstall-{0}.ps1" -f [guid]::NewGuid())
    Copy-Item -Force $MyInvocation.MyCommand.Path $copy
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$copy`"", '-Relaunched')
    if ($RemoveSettings) { $arguments += '-RemoveSettings' }
    Start-Process powershell.exe -ArgumentList $arguments
    return
}

Write-Host "Uninstalling $AppName..." -ForegroundColor Cyan

# --- stop the app ----------------------------------------------------------

# Only this session's copy: other users' processes cannot be stopped without admin
# rights, and with ErrorActionPreference=Stop trying would abort the script.
$mySession = (Get-Process -Id $PID).SessionId
$running = Get-Process $AppId -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $mySession }
if ($running) {
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2
    Write-Host '  stopped the running app' -ForegroundColor DarkGray
}

# --- autostart, shortcuts, registry ---------------------------------------

if (Get-ItemProperty -Path $RunKey -Name $AppId -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $RunKey -Name $AppId -ErrorAction SilentlyContinue
    Write-Host '  removed the startup entry' -ForegroundColor DarkGray
}

foreach ($link in @($StartMenu, $Desktop)) {
    if (Test-Path $link) {
        Remove-Item -Force $link -ErrorAction SilentlyContinue
        Write-Host "  removed $(Split-Path -Leaf $link)" -ForegroundColor DarkGray
    }
}

if (Test-Path $UninstallKey) {
    Remove-Item -Recurse -Force $UninstallKey -ErrorAction SilentlyContinue
    Write-Host '  deregistered from Settings > Apps' -ForegroundColor DarkGray
}

# --- program files --------------------------------------------------------

if (Test-Path $InstallDir) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -Recurse -Force $InstallDir -ErrorAction Stop
            Write-Host '  deleted the program folder' -ForegroundColor DarkGray
            break
        } catch {
            if ($attempt -eq 5) {
                Write-Warning "Could not delete $InstallDir - delete it manually once nothing is using it."
            } else {
                Start-Sleep -Seconds 2
            }
        }
    }
}

# --- settings and logs ----------------------------------------------------

if ($RemoveSettings) {
    if (Test-Path $DataDir) {
        Remove-Item -Recurse -Force $DataDir -ErrorAction SilentlyContinue
        Write-Host '  deleted settings and logs' -ForegroundColor DarkGray
    }
} elseif (Test-Path $DataDir) {
    Write-Host ''
    Write-Host "Settings and logs were kept in $DataDir" -ForegroundColor Yellow
    Write-Host 'Re-run with -RemoveSettings to delete them too.'
}

Write-Host ''
Write-Host "$AppName has been removed." -ForegroundColor Green
if ($Relaunched) {
    Remove-Item -Force $MyInvocation.MyCommand.Path -ErrorAction SilentlyContinue   # the temp copy
    Start-Sleep -Seconds 4
}
