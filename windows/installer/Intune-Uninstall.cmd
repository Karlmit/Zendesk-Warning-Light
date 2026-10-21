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
rem  WHY THIS WRAPPER EXISTS RATHER THAN CALLING unins000.exe DIRECTLY:
rem  Inno's uninstaller copies itself to %TEMP% and lets that copy finish the
rem  job, so it can delete its own folder. The process you launched therefore
rem  returns 0 while the program folder is still on disk - measured at about
rem  three seconds' lag. Intune would evaluate its detection rule in that gap
rem  and conclude the uninstall failed. This script waits for the app to
rem  actually be gone before it exits.
rem
rem  Settings and logs in %APPDATA%\ZendeskWarningLight are deliberately kept,
rem  so a reinstall keeps each user signed in. Add --purge to delete them.
rem
rem  Exit codes: 0 = removed, or nothing was installed. 1 = still present after
rem  the timeout. Otherwise the uninstaller's own code.
rem ===========================================================================

setlocal enabledelayedexpansion

rem System tools by absolute path: cmd looks in the current directory first, and
rem this may run as SYSTEM. %SystemRoot% has no spaces, so no quoting needed.
set "SYS32=%SystemRoot%\System32"
set "KEY=SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}_is1"
set "PURGE=0"
if /i "%~1"=="--purge" set "PURGE=1"

set "UNINST="
set "TARGET="
set "SCOPE="
set "HIVE="

for %%H in (HKLM HKCU) do (
  if not defined UNINST (
    for /f "tokens=2,*" %%A in (
      '%SYS32%\reg.exe query "%%H\%KEY%" /v UninstallString 2^>nul ^| %SYS32%\find.exe /i "UninstallString"'
    ) do (
      set "UNINST=%%B"
      set "HIVE=%%H"
      if /i "%%H"=="HKLM" (set "SCOPE=machine-wide") else (set "SCOPE=per-user")
    )
    if defined UNINST (
      for /f "tokens=2,*" %%C in (
        '%SYS32%\reg.exe query "%%H\%KEY%" /v InstallLocation 2^>nul ^| %SYS32%\find.exe /i "InstallLocation"'
      ) do set "TARGET=%%D"
    )
  )
)

if not defined UNINST (
  echo Zendesk Warning Light is not installed - nothing to do.
  exit /b 0
)

echo Found a %SCOPE% install ^(%HIVE%^).
if defined TARGET echo Location: !TARGET!
echo Running : !UNINST! /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
echo.

!UNINST! /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
set "RC=%ERRORLEVEL%"

rem --- wait for it to really be gone ----------------------------------------
rem The registry key disappearing is the signal Intune's registry detection
rem rule looks for; the folder going is what a file rule looks for. Wait for
rem both, so either kind of detection rule is accurate when we exit.
set /a WAITED=0
:wait
rem Test errorlevel on the very next line: any command in between - even a plain
rem SET, which always succeeds - resets it to 0 and the check becomes useless.
"%SYS32%\reg.exe" query "%HIVE%\%KEY%" >nul 2>&1
if errorlevel 1 (set "KEYGONE=1") else (set "KEYGONE=0")

set "DIRGONE=1"
if defined TARGET if exist "!TARGET!" set "DIRGONE=0"

if "%KEYGONE%"=="1" if "%DIRGONE%"=="1" goto gone
if %WAITED% GEQ 120 goto timeout
rem ping, not timeout.exe: timeout refuses to wait when its output is redirected
rem ("input redirection is not supported") and returns instantly, which turns this
rem into a busy spin that hits the limit in a few seconds.
"%SYS32%\ping.exe" -n 3 127.0.0.1 >nul 2>&1
set /a WAITED+=2
goto wait

:timeout
echo.
echo WARNING: still present after %WAITED% seconds.
if "%KEYGONE%"=="0" echo   registry key %HIVE%\...\%KEY% remains
if "%DIRGONE%"=="0" echo   folder !TARGET! remains
echo A file may have been locked by a running copy of the app.
exit /b 1

:gone
echo Removed after %WAITED% seconds.

if "%PURGE%"=="1" (
  if exist "%APPDATA%\ZendeskWarningLight" (
    rd /s /q "%APPDATA%\ZendeskWarningLight"
    echo Deleted settings and logs for this user.
  )
  echo NOTE: --purge only clears the account running this command. Each user has
  echo their own %%APPDATA%%\ZendeskWarningLight and their own encrypted token.
)

echo.
if not "%RC%"=="0" echo Uninstaller reported exit code %RC%, but the app is gone.
exit /b 0
