@echo off
rem ===========================================================================
rem  Zendesk Warning Light - install wrapper for Intune
rem
rem  Picks the install mode from the account running it:
rem
rem    running as SYSTEM  ->  /ALLUSERS    (Program Files, HKLM, every user)
rem    running as a user  ->  /CURRENTUSER (%LOCALAPPDATA%, HKCU, that user)
rem
rem  Inno Setup cannot choose the mode itself - PrivilegesRequired=lowest means
rem  non-administrative mode even when launched by an administrator - so the
rem  decision has to be made out here, before Setup starts.
rem
rem  Use as the Intune install command:
rem      Intune-Install.cmd
rem  Anything you add on the command line is passed through, e.g.
rem      Intune-Install.cmd /LOG="%TEMP%\zwl.log"
rem
rem  Exits with Setup's own exit code, so Intune reports success and failure
rem  correctly. 0 = installed.
rem ===========================================================================

setlocal enabledelayedexpansion

rem --- find the setup exe sitting next to this script ------------------------
set "SETUP="
for %%F in ("%~dp0ZendeskWarningLight-Setup-*.exe") do set "SETUP=%%~fF"

if not defined SETUP (
  echo ERROR: no ZendeskWarningLight-Setup-*.exe found next to this script.>&2
  echo Put this .cmd in the same folder as the installer.>&2
  exit /b 1
)

rem --- who are we? S-1-5-18 is the well-known SID of LocalSystem -------------
set "MODE=/CURRENTUSER"
set "CONTEXT=a user account - installing for this user only"

rem System tools by absolute path: cmd looks in the current directory first.
"%SystemRoot%\System32\whoami.exe" /user 2>nul | "%SystemRoot%\System32\find.exe" /i "S-1-5-18" >nul
if not errorlevel 1 (
  set "MODE=/ALLUSERS"
  set "CONTEXT=SYSTEM - installing machine-wide for all users"
)

echo Detected: %CONTEXT%
echo Setup   : "%SETUP%"
echo Command : /VERYSILENT %MODE% /SUPPRESSMSGBOXES /NORESTART %*
echo.

"%SETUP%" /VERYSILENT %MODE% /SUPPRESSMSGBOXES /NORESTART %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo Installed successfully.
) else (
  echo Setup failed with exit code %RC%.
  echo   1 = failed to initialize ^(see the /LOG file - a bad switch lands here^)
  echo   2 = cancelled before installing      5 = cancelled during install
  echo   3 = fatal error preparing to install  4 = fatal error installing
)

exit /b %RC%
