; Launcher for Zendesk Warning Light.
;
; This is the exe you ship. It installs nothing itself: it carries the real Inno
; installer inside it, and its only job is to translate command lines that
; packaging tools are usually configured with:
;
;   Setup.exe                    interactive, as before
;   Setup.exe /S                 silent install, install mode auto-detected
;   Setup.exe /S /uninstall      silent uninstall of whichever copy is installed
;   Setup.exe /uninstall         the same, interactively
;   Setup.exe /VERYSILENT ...    passed straight through to the real installer
;
; WHY A LAUNCHER AND NOT JUST MORE SCRIPT IN THE INSTALLER
;
; Three things make it impossible for an Inno installer to support /S itself,
; each confirmed by testing rather than assumed:
;
;  1. Inno fixes silent mode in its own command-line parser before any [Code]
;     runs, and nothing in the script can change it afterwards.
;  2. Script cannot set the process exit code. Aborting always reports 1, which
;     every deployment tool reads as a failure - so it cannot relay a command and
;     report the real result. ExitProcess from kernel32 solves that.
;  3. A running Inno installer holds its own .exe open in a mode that blocks both
;     executing AND reading it, so it cannot relaunch or even copy itself. Only a
;     separate exe can start it.
;
; Hence: a small outer exe, with the real installer stored inside as a compressed
; payload, extracted to the temp folder on demand.

#define AppName      "Zendesk Warning Light"
#define AppId        "ZendeskWarningLight"
#define AppPublisher "Karl Almqvist"
#define AppVersion   "2.4.0"
#define InnerExe     "ZendeskWarningLight-Inner.exe"
; Must match the real installer's AppId, so we can find what it installed.
#define SetupAppId   "{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}"

[Setup]
; Its own AppId, distinct from the app's, because this wrapper is never itself
; "installed" - and with CreateAppDir and Uninstallable off it leaves no trace.
AppId={{2C7F41B9-6E3D-4A52-9F18-5D4B7E0C3A66}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}

CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

OutputDir=..\dist
OutputBaseFilename={#AppId}-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Files]
; dontcopy keeps it inside the exe until ExtractTemporaryFile asks for it.
Source: "..\build\{#InnerExe}"; Flags: dontcopy

[Code]

// Terminates this process with an exact exit code. Inno's own Abort always ends up
// as 1 ("failed to initialize"), which a deployment tool reads as failure - so
// relaying a command and reporting its true result is impossible without this.
procedure ExitProcess(uExitCode: Cardinal);
  external 'ExitProcess@kernel32.dll stdcall';

const
  UninstallSubkey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupAppId}_is1';
  RemovalTimeout = 120;

// Reads a command-line switch. Inno's own param constant only matches the
// /Name=Value form, so this also accepts a bare /Name (treated as "1").
// NB: // comments only in here - a brace comment ends at the first brace.
function SwitchValue(const Name, Default: String): String;
var
  I: Integer;
  Arg, Key: String;
begin
  Result := Default;
  Key := '/' + Uppercase(Name);
  for I := 1 to ParamCount do
  begin
    Arg := ParamStr(I);
    if Uppercase(Arg) = Key then
    begin
      Result := '1';
      Exit;
    end;
    if Copy(Uppercase(Arg), 1, Length(Key) + 1) = Key + '=' then
    begin
      Result := Copy(Arg, Length(Key) + 2, Length(Arg));
      Exit;
    end;
  end;
end;

function SwitchIsOn(const Name: String): Boolean;
var
  Value: String;
begin
  Value := Uppercase(Trim(SwitchValue(Name, '0')));
  Result := not ((Value = '0') or (Value = '') or (Value = 'NO') or (Value = 'FALSE'));
end;

function WantsUninstall: Boolean;
begin
  Result := SwitchIsOn('UNINSTALL') or SwitchIsOn('U') or SwitchIsOn('REMOVE');
end;

function WantsSilence: Boolean;
begin
  Result := SwitchIsOn('S') or SwitchIsOn('SILENT') or SwitchIsOn('VERYSILENT');
end;

// True when running as LocalSystem. Detected by where a per-user install would
// land rather than by identifying the account: the service profile is the actual
// problem, and this is the signal that matters.
function RunningAsSystem: Boolean;
begin
  Result := Pos('\SYSTEMPROFILE\',
                Uppercase(ExpandConstant('{localappdata}'))) > 0;
end;

function FindInstalledCopy(var Exe, Location: String; var Root: Integer): Boolean;
var
  Raw: String;
begin
  Result := False;
  Root := HKEY_LOCAL_MACHINE;
  if not RegQueryStringValue(Root, UninstallSubkey, 'UninstallString', Raw) then
  begin
    Root := HKEY_CURRENT_USER;
    if not RegQueryStringValue(Root, UninstallSubkey, 'UninstallString', Raw) then
      Exit;
  end;
  Exe := RemoveQuotes(Trim(Raw));
  if not RegQueryStringValue(Root, UninstallSubkey, 'InstallLocation', Location) then
    Location := '';
  Result := Exe <> '';
end;

// Hand off to the uninstaller written at install time, wait for the app to really
// be gone, and exit with a code that reflects reality. Never returns.
procedure RelayUninstall;
var
  Exe, Location, Params: String;
  Root, Code, Waited: Integer;
begin
  if not FindInstalledCopy(Exe, Location, Root) then
  begin
    Log('uninstall: not installed, nothing to do');
    ExitProcess(0);
  end;

  if WantsSilence then
    Params := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
  else
    Params := '';

  Log('uninstall: running ' + Exe + ' ' + Params);
  if not Exec(Exe, Params, '', SW_SHOW, ewWaitUntilTerminated, Code) then
  begin
    Log('uninstall: could not start ' + Exe);
    ExitProcess(1);
  end;

  // Inno's uninstaller copies itself to the temp folder and lets that copy finish,
  // so it returns before the files are gone - about three seconds. A deployment
  // tool checks detection the moment we exit, so wait for it to actually go.
  Waited := 0;
  while (Waited < RemovalTimeout)
        and (RegKeyExists(Root, UninstallSubkey)
             or ((Location <> '') and DirExists(Location))) do
  begin
    Sleep(1000);
    Waited := Waited + 1;
  end;

  if RegKeyExists(Root, UninstallSubkey) then
  begin
    Log('uninstall: still registered after ' + IntToStr(Waited) + 's');
    ExitProcess(1);
  end;
  Log('uninstall: removed after ' + IntToStr(Waited) + 's');
  ExitProcess(0);
end;

// Extract the real installer and run it. Never returns.
procedure RelayInstall;
var
  Inner, Params, Arg, Upper: String;
  I, Code: Integer;
begin
  ExtractTemporaryFile('{#InnerExe}');
  Inner := ExpandConstant('{tmp}\{#InnerExe}');

  if WantsSilence then
    Params := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
  else
    Params := '';

  // Carry everything else through. Written as one positive test on purpose: an
  // empty "then" before an "else" is the sort of thing a dialect may read
  // differently, and a leaked /S would have the inner installer reject itself.
  for I := 1 to ParamCount do
  begin
    Arg := ParamStr(I);
    Upper := Uppercase(Arg);
    if not ((Upper = '/S') or (Upper = '/SILENT') or (Upper = '/VERYSILENT')
            or (Upper = '/SUPPRESSMSGBOXES') or (Upper = '/NORESTART')
            or (Copy(Upper, 1, 5) = '/SL5=')) then
    begin
      // We already hold the requested log file open, so handing the inner
      // installer the same path makes it fail to initialize - which looks exactly
      // like a broken install. Give it its own file beside the requested one.
      if Copy(Upper, 1, 5) = '/LOG=' then
        Params := Params + ' "/LOG=' + Copy(Arg, 6, Length(Arg)) + '.install.log"'
      else
        Params := Params + ' "' + Arg + '"';
    end;
  end;

  // Nobody said which scope, so choose the one that can actually work: SYSTEM has
  // no usable per-user profile, everyone else gets a per-user install.
  if not (SwitchIsOn('ALLUSERS') or SwitchIsOn('CURRENTUSER')) then
  begin
    if RunningAsSystem then
      Params := Params + ' /ALLUSERS'
    else
      Params := Params + ' /CURRENTUSER';
  end;

  Log('launcher: running the installer as' + Params);
  if SwitchValue('LOG', '') <> '' then
    Log('launcher: the detailed install log is '
        + SwitchValue('LOG', '') + '.install.log');

  if not Exec(Inner, Params, '', SW_SHOW, ewWaitUntilTerminated, Code) then
  begin
    Log('launcher: could not start ' + Inner);
    ExitProcess(1);
  end;
  Log('launcher: installer finished with exit code ' + IntToStr(Code));
  ExitProcess(Cardinal(Code));
end;

function InitializeSetup: Boolean;
begin
  if WantsUninstall then
    RelayUninstall    // never returns
  else
    RelayInstall;     // never returns
  Result := False;    // unreachable; keeps the compiler happy
end;
