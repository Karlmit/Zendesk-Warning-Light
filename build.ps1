<#
    Builds a standalone Zendesk Warning Light.exe with PyInstaller.

    Usage:
        .\build.ps1              # folder build in dist\ZendeskWarningLight (fast startup)
        .\build.ps1 -OneFile     # single .exe (slower startup, extracts to temp each run)
        .\build.ps1 -Installer   # also compile a setup wizard (needs Inno Setup 6)
        .\build.ps1 -Clean       # discard previous build output first

    To install after building, run .\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$Clean,
    [switch]$Installer
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'Creating virtual environment...' -ForegroundColor Cyan
    py -3.10 -m venv $venv
}

Write-Host 'Installing dependencies...' -ForegroundColor Cyan
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -r requirements.txt pyinstaller

Write-Host 'Generating application icon...' -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = 'offscreen'
& $python tools\make_icon.py
Remove-Item Env:\QT_QPA_PLATFORM

# Read the single source of truth for the version, and build the resource that
# stamps it onto the exe so Windows Properties and inventory tools can see it.
$appVersion = (Select-String -Path zwl\__init__.py -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$versionFile = Join-Path $PSScriptRoot 'build\version_info.txt'
Write-Host "Stamping version $appVersion..." -ForegroundColor Cyan
& $python tools\make_version_file.py $versionFile

if ($Clean) {
    Write-Host 'Cleaning previous build output...' -ForegroundColor Cyan
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
    & $python tools\make_version_file.py $versionFile   # build\ was just deleted
}

$pyiArgs = @(
    '--noconfirm'
    '--windowed'                       # no console window
    '--name', 'ZendeskWarningLight'
    '--icon', 'assets\app.ico'
    '--version-file', $versionFile
    '--add-data', 'assets;assets'
    '--exclude-module', 'tkinter'
    '--exclude-module', 'PySide6.QtWebEngineCore'
    '--exclude-module', 'PySide6.QtQuick'
    '--exclude-module', 'PySide6.Qt3DCore'
    '--exclude-module', 'PySide6.QtMultimedia'
    'main.py'
)
if ($OneFile) { $pyiArgs = @('--onefile') + $pyiArgs }

Write-Host 'Running PyInstaller...' -ForegroundColor Cyan
& $python -m PyInstaller @pyiArgs

$exe = if ($OneFile) {
    Join-Path $PSScriptRoot 'dist\ZendeskWarningLight.exe'
} else {
    Join-Path $PSScriptRoot 'dist\ZendeskWarningLight\ZendeskWarningLight.exe'
}

if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    $stamped = (Get-Item $exe).VersionInfo.FileVersion
    Write-Host ''
    Write-Host "Build complete: $exe ($size MB, version $stamped)" -ForegroundColor Green
} else {
    throw "PyInstaller finished but $exe is missing."
}

if ($Installer) {
    $iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"   # per-user install
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($iscc) {
        Write-Host 'Compiling the setup wizard...' -ForegroundColor Cyan
        & $iscc 'installer\ZendeskWarningLight.iss'
        $setup = Join-Path $PSScriptRoot "dist\ZendeskWarningLight-Setup-$appVersion.exe"
        if (Test-Path $setup) {
            $setupMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)

            # Stage the Intune wrappers beside the installer: IntuneWinAppUtil
            # packages a whole folder, and the .cmd finds the setup exe next to it.
            $distDir = Join-Path $PSScriptRoot 'dist'
            Copy-Item -Force (Join-Path $PSScriptRoot 'installer\Intune-Install.cmd') $distDir
            Copy-Item -Force (Join-Path $PSScriptRoot 'installer\Intune-Uninstall.cmd') $distDir

            Write-Host ''
            Write-Host "Give this file to colleagues:" -ForegroundColor Green
            Write-Host "  $setup  ($setupMb MB)" -ForegroundColor Green
            Write-Host ''
            Write-Host "For Intune, package the dist folder - it now also contains:" -ForegroundColor Green
            Write-Host "  Intune-Install.cmd    (SYSTEM -> all users, user -> current user)"
            Write-Host "  Intune-Uninstall.cmd"
        } else {
            throw "ISCC finished but $setup is missing."
        }
    } else {
        Write-Warning 'Inno Setup 6 is not installed, so no setup wizard was built.'
        Write-Host 'Install it from https://jrsoftware.org/isdl.php, or just run .\install.ps1 -' -ForegroundColor DarkGray
        Write-Host 'that installs for the current user without any extra tooling.' -ForegroundColor DarkGray
    }
}

Write-Host ''
Write-Host 'Next: .\install.ps1   (installs for you, adds a Start menu entry, starts with Windows)'
