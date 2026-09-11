@echo off
rem ===========================================================================
rem  Zendesk Warning Light - uninstall wrapper for Intune
rem
rem  Finds whichever install is present and removes it silently. Checks HKLM
rem  first (machine-wide) then HKCU (per-user), so the same command works for
rem  either deployment context.
rem
rem  Use as the Intune uninstall command:
rem      Intune-Uninstall.cmd
rem
rem  Settings and logs in %APPDATA%\ZendeskWarningLight are deliberately kept,
rem  so a reinstall keeps each user signed in. Add --purge to delete them.
rem
rem  Exit codes: 0 = removed, or nothing was installed. Otherwise the
rem  uninstaller's own code.
rem ===========================================================================

setlocal enabledelayedexpansion

set "KEY=SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}_is1"
set "PURGE=0"
if /i "%~1"=="--purge" set "PURGE=1"

set "UNINST="
set "SCOPE="

for /f "tokens=2,*" %%A in (
  'reg query "HKLM\%KEY%" /v QuietUninstallString 2^>nul ^| find /i "QuietUninstallString"'
) do (
  set "UNINST=%%B"
  set "SCOPE=machine-wide (HKLM)"
)

if not defined UNINST (
  for /f "tokens=2,*" %%A in (
    'reg query "HKCU\%KEY%" /v QuietUninstallString 2^>nul ^| find /i "QuietUninstallString"'
  ) do (
    set "UNINST=%%B"
    set "SCOPE=per-user (HKCU)"
  )
)

if not defined UNINST (
  echo Zendesk Warning Light is not installed - nothing to do.
  exit /b 0
)

echo Found a %SCOPE% install.
echo Running: !UNINST! /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
echo.

rem The uninstaller copies itself to temp and returns immediately, so wait for
rem the copy to finish or Intune would check detection too early.
!UNINST! /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
set "RC=%ERRORLEVEL%"

set /a WAITED=0
:wait
timeout /t 2 /nobreak >nul 2>&1
tasklist /fi "imagename eq unins000.exe" 2>nul | find /i "unins000.exe" >nul
if errorlevel 1 goto done
set /a WAITED+=2
if %WAITED% GEQ 120 goto done
goto wait
:done

if "%PURGE%"=="1" (
  if exist "%APPDATA%\ZendeskWarningLight" (
    rd /s /q "%APPDATA%\ZendeskWarningLight"
    echo Deleted settings and logs for this user.
  )
  echo NOTE: --purge only clears the account running this command. Each user has
  echo their own %%APPDATA%%\ZendeskWarningLight and their own encrypted token.
)

echo.
if "%RC%"=="0" (
  echo Removed.
) else (
  echo Uninstaller exit code %RC%.
)
exit /b %RC%
