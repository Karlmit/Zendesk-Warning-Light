<#
    Installs Zendesk Warning Light for the current user. No administrator rights needed.

    It copies the build into %LOCALAPPDATA%\Programs\ZendeskWarningLight, adds a Start
    menu shortcut, registers the app in Settings > Apps (Add/Remove Programs) so it can
    be uninstalled the normal way, and sets it to start with Windows.

    Usage:
        .\install.ps1                     # build if needed, install, autostart, launch
        .\install.ps1 -NoAutostart        # install without the startup entry
        .\install.ps1 -DesktopShortcut    # also drop a shortcut on the desktop
        .\install.ps1 -Force              # rebuild from source even if dist\ exists
#>
[CmdletBinding()]
param(
    [switch]$NoAutostart,
    [switch]$DesktopShortcut,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$AppName      = 'Zendesk Warning Light'
$AppId        = 'ZendeskWarningLight'
$Publisher    = 'Karl Almqvist'
$InstallDir   = Join-Path $env:LOCALAPPDATA "Programs\$AppId"
$BuildDir     = Join-Path $PSScriptRoot "dist\$AppId"
$Exe          = Join-Path $InstallDir "$AppId.exe"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$RunKey       = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$StartMenu    = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"

function Get-AppVersion {
    $initPy = Join-Path $PSScriptRoot 'zwl\__init__.py'
    $match = Select-String -Path $initPy -Pattern '__version__\s*=\s*"([^"]+)"'
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return '1.0.0'
}

# --- 1. make sure we have something to install ------------------------------

if ($Force -or -not (Test-Path (Join-Path $BuildDir "$AppId.exe"))) {
    Write-Host 'Building the application...' -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'build.ps1') -Clean
}
if (-not (Test-Path (Join-Path $BuildDir "$AppId.exe"))) {
    throw "No build found at $BuildDir. Run .\build.ps1 first."
}

# --- 2. stop any running copy ----------------------------------------------

$running = Get-Process $AppId -ErrorAction SilentlyContinue
if ($running) {
    Write-Host 'Closing the running copy...' -ForegroundColor Cyan
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# --- 3. copy files ----------------------------------------------------------

Write-Host "Installing to $InstallDir" -ForegroundColor Cyan
if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir -ErrorAction Stop
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Recurse -Force (Join-Path $BuildDir '*') $InstallDir

$uninstallSource = Join-Path $PSScriptRoot 'installer\uninstall.ps1'
if (Test-Path $uninstallSource) {
    Copy-Item -Force $uninstallSource (Join-Path $InstallDir 'uninstall.ps1')
}

# --- 4. shortcuts -----------------------------------------------------------

$shell = New-Object -ComObject WScript.Shell

function New-Shortcut([string]$Path) {
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath       = $Exe
    $link.WorkingDirectory = $InstallDir
    $link.IconLocation     = "$Exe,0"
    $link.Description      = 'Flashes a warning when a Zendesk ticket needs attention'
    $link.Save()
}

New-Shortcut $StartMenu
Write-Host "Start menu shortcut created." -ForegroundColor DarkGray

if ($DesktopShortcut) {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk")
    Write-Host 'Desktop shortcut created.' -ForegroundColor DarkGray
}

# --- 5. register in Settings > Apps ----------------------------------------

$sizeKb = [int]((Get-ChildItem -Recurse $InstallDir | Measure-Object -Property Length -Sum).Sum / 1KB)
New-Item -Path $UninstallKey -Force | Out-Null
$values = @{
    DisplayName     = $AppName
    DisplayVersion  = Get-AppVersion
    Publisher       = $Publisher
    DisplayIcon     = $Exe
    InstallLocation = $InstallDir
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\uninstall.ps1`""
    NoModify        = 1
    NoRepair        = 1
    EstimatedSize   = $sizeKb
}
foreach ($name in $values.Keys) {
    $type = if ($values[$name] -is [int]) { 'DWord' } else { 'String' }
    New-ItemProperty -Path $UninstallKey -Name $name -Value $values[$name] -PropertyType $type -Force | Out-Null
}
Write-Host 'Registered under Settings > Apps > Installed apps.' -ForegroundColor DarkGray

# --- 6. autostart -----------------------------------------------------------

if ($NoAutostart) {
    Remove-ItemProperty -Path $RunKey -Name $AppId -ErrorAction SilentlyContinue
    Write-Host 'Autostart left off.' -ForegroundColor DarkGray
} else {
    New-ItemProperty -Path $RunKey -Name $AppId -Value "`"$Exe`"" -PropertyType String -Force | Out-Null
    Write-Host 'Will start automatically when you sign in to Windows.' -ForegroundColor DarkGray
}

# --- 7. launch --------------------------------------------------------------

Start-Process $Exe
Start-Sleep -Seconds 3

Write-Host ''
if (Get-Process $AppId -ErrorAction SilentlyContinue) {
    Write-Host "$AppName $(Get-AppVersion) installed and running." -ForegroundColor Green
    Write-Host 'Look for the warning cat in your system tray.'
} else {
    Write-Warning "Installed, but the app did not stay running. Check $env:APPDATA\$AppId\warning-light.log"
}
Write-Host "Uninstall from Settings > Apps, or run: $InstallDir\uninstall.ps1"
