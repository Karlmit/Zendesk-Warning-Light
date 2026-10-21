; Inno Setup script for Zendesk Warning Light.
;
; Build with:  .\build.ps1 -Installer      (produces dist\ZendeskWarningLight-Setup.exe)
;
; Installs either per-user or machine-wide:
;
;   Setup.exe /VERYSILENT /CURRENTUSER   -> %LOCALAPPDATA%\Programs, HKCU, no admin
;   Setup.exe /VERYSILENT /ALLUSERS      -> Program Files, HKLM, needs admin/SYSTEM
;
; The {auto*} constants and the HKA registry root pick the right target for the
; mode in force, so one script serves both. See README.md for the Intune commands.
;
; THIS IS NOT THE FILE YOU SHIP. It compiles to build\ZendeskWarningLight-Inner.exe,
; which Launcher.iss embeds inside the exe that actually goes out. The launcher
; exists to translate /S and /S /uninstall, which an Inno installer cannot do for
; itself - see the long comment at the top of Launcher.iss for why.
;
; Consequently this script only ever sees switches Inno understands natively, and
; the guards below are belt and braces for anyone running the payload directly.

#define AppName      "Zendesk Warning Light"
#define AppId        "ZendeskWarningLight"
#define AppPublisher "Karl Almqvist"
#define AppExe       "ZendeskWarningLight.exe"
; Passed in by build.ps1 from zwl/__init__.py, the single source of truth.
; The fallback only applies when compiling this by hand, and is deliberately
; not a real version so a hand-built exe can never be mistaken for a release.
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
; The bare GUID, for building uninstall key paths in [Code].
#define SetupAppId   "{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}"

[Setup]
AppId={{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup

; Default to a per-user install, so a plain double-click needs no UAC prompt, and
; let /ALLUSERS switch to a machine-wide one. PrivilegesRequired=lowest means
; non-administrative mode *even when launched by an administrator*, so SYSTEM has
; to pass /ALLUSERS explicitly - see the guard in InitializeSetup.
;
; Overrides are "commandline" ONLY, deliberately not "dialog". With "dialog", an
; elevated launch carrying neither /ALLUSERS nor /CURRENTUSER makes Inno put up a
; "Select install mode" prompt - and it does so *before* InitializeSetup runs, so
; the guards below never get a chance and an admin passing a bad switch gets a
; window rather than an error. Command line only means the caller always decides
; the mode and Setup never asks anyone anything.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
DefaultDirName={autopf}\{#AppId}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; No folder page: uninstall deletes the whole {app} folder, so it must never be
; a folder that already held someone's files.
DisableDirPage=yes
AllowNoIcons=yes

; Built into build\ as an internal payload. The shipped, versioned filename is
; produced by Launcher.iss.
OutputDir=..\build
OutputBaseFilename={#AppId}-Inner
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

; No SetupMutex: relaying /S runs a second copy of Setup on purpose, and a mutex
; has no bypass switch, so it would block the very thing we are doing.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; These two drive the checkboxes in the INTERACTIVE wizard only.
;
; A silent install ignores them and reads /NOAUTOSTART and /DESKTOPICON instead -
; see WantAutostart and WantDesktopIcon in [Code]. That is deliberate: in silent
; mode Inno reuses the task selection recorded by a previous install, and
; dontinheritcheck does not prevent it, so a plain /VERYSILENT would otherwise
; depend on install history. The switches are the single source of truth.
Name: "autostart"; Description: "Start {#AppName} when I sign in to Windows"; \
    GroupDescription: "Startup:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; \
    GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppId}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppId}\*";         DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";     Filename: "{app}\{#AppExe}"; Check: WantDesktopIcon

[Registry]
; HKA resolves to HKLM in a machine-wide install and HKCU in a per-user one, so a
; machine-wide deployment starts the app for every user who logs in.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppId}"; ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Check: WantAutostart

; Skipping the entry above is not the same as removing one an earlier install left
; behind, so /NOAUTOSTART has to delete it explicitly. Without this the switch is
; not authoritative and the outcome depends on install history - the same trap as
; the task-inheritance one described in [Tasks].
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "{#AppId}"; \
    Flags: deletevalue; Check: NoAutostart

[Run]
; Interactive install: offer a "start now" checkbox on the final page.
; runasoriginaluser: an /ALLUSERS install elevates, but the tray app must run as the
; signed-in user, never with the installer's admin token.
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; \
    Flags: nowait postinstall skipifsilent runasoriginaluser

; Silent install: start it straight away unless /NOLAUNCH was passed.
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent runasoriginaluser; \
    Check: ShouldLaunchAfterSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
; Settings and logs in %APPDATA%\ZendeskWarningLight are deliberately left behind.
ConfirmUninstall=Remove {#AppName}?%n%nYour settings and logs in %APPDATA%\{#AppId} will be kept.

[Code]

// Reads a command-line switch. Inno's own param constant only matches the
// /Name=Value form, so this also accepts a bare /Name (treated as "1").
// NB: use // comments in this section - a brace comment would be closed early by
// any brace in the text.
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

// Honour /NOLAUNCH (or /NOLAUNCH=1) during a silent install. Never launch as
// SYSTEM (Intune system context): the app would sit invisibly in session 0 with
// SYSTEM's rights until reboot. Users get it from the Run key at their next login.
function ShouldLaunchAfterSilent: Boolean;
begin
  Result := not SwitchIsOn('NOLAUNCH')
    and (Pos('\SYSTEMPROFILE\', Uppercase(ExpandConstant('{localappdata}'))) = 0);
end;

// Interactive installs follow the wizard checkbox; silent installs follow the
// command line, so the outcome never depends on what a previous install selected.
function WantAutostart: Boolean;
begin
  if WizardSilent then
    Result := not SwitchIsOn('NOAUTOSTART')
  else
    Result := WizardIsTaskSelected('autostart');
end;

// [Registry] Check expressions take a function name, not an expression, so the
// negation needs its own function.
function NoAutostart: Boolean;
begin
  Result := not WantAutostart;
end;

function WantDesktopIcon: Boolean;
begin
  if WizardSilent then
    Result := SwitchIsOn('DESKTOPICON')
  else
    Result := WizardIsTaskSelected('desktopicon');
end;

// Refuse the command line that would otherwise fail in a way nobody can diagnose
// from a deployment report, and relay the NSIS-style switches to real ones.
function InitializeSetup: Boolean;
var
  LocalAppData: String;
begin
  Result := True;

  // The launcher translates these before we ever run, so seeing one here means
  // somebody is running the payload directly. Refuse rather than install: Inno
  // ignores switches it does not know, so /VERYSILENT /UNINSTALL would otherwise
  // install and report success.
  if SwitchIsOn('UNINSTALL') or SwitchIsOn('U') or SwitchIsOn('REMOVE') then
  begin
    Log('ABORT: this is the install payload and cannot uninstall. Use the shipped '
        + 'ZendeskWarningLight-Setup-*.exe with /S /uninstall.');
    Result := False;
    Exit;
  end;

  if SwitchIsOn('S') and not WizardSilent then
  begin
    Log('ABORT: /S is handled by the shipped launcher, not by this payload. '
        + 'Use /VERYSILENT here, or run the shipped exe.');
    Result := False;
    Exit;
  end;

  // Running as SYSTEM without /ALLUSERS would install into the service profile
  // at C:\Windows\System32\config\systemprofile, where no real user can ever
  // run it. Detect the outcome rather than trying to identify the account.
  if not IsAdminInstallMode then
  begin
    LocalAppData := Uppercase(ExpandConstant('{localappdata}'));
    if Pos('\SYSTEMPROFILE\', LocalAppData) > 0 then
    begin
      Log('ABORT: running as SYSTEM in per-user mode would install into '
          + LocalAppData + '. Pass /ALLUSERS for a machine-wide install.');
      Result := False;
      Exit;
    end;
  end;

  if IsAdminInstallMode then
    Log('install mode: machine-wide (all users)')
  else
    Log('install mode: per-user');
end;

// A machine-wide install alongside a leftover per-user one means two entries in
// Settings > Apps and two Run values. Say so in the log; it is the admin's call.
procedure WarnAboutOtherModeInstall;
begin
  if IsAdminInstallMode then
  begin
    if RegKeyExists(HKEY_CURRENT_USER,
        'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupAppId}_is1') then
      Log('NOTE: a per-user copy is also installed for this account. Uninstall it '
          + 'to avoid two entries in Settings > Apps.');
  end
  else
  begin
    if RegKeyExists(HKEY_LOCAL_MACHINE,
        'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupAppId}_is1') then
      Log('NOTE: a machine-wide copy is already installed. This per-user install '
          + 'will shadow it and the app may start twice at login.');
  end;
end;

// The app is a tray program that holds its own files open, so it has to be closed
// before we overwrite it. Runs after the wizard, before any file is copied.
procedure StopRunningApp;
var
  ResultCode: Integer;
begin
  // As SYSTEM this reaches every logged-in session, which is what a machine-wide
  // upgrade needs; as a normal user it only reaches that user's own copy.
  // Absolute path, no cmd.exe: cmd searches the current directory first, so a bare
  // "taskkill" could resolve to a planted exe when Setup runs elevated.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM "{#AppExe}" /F', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp;
  Result := '';
end;

function InitializeUninstall: Boolean;
begin
  StopRunningApp;
  Result := True;
end;

// Earlier versions were installed by install.ps1, which registered its own
// Add/Remove Programs entry and a loose Start menu shortcut. Clear those out so the
// app is not listed twice after upgrading to the wizard.
procedure RemoveLegacyScriptInstall;
begin
  // install.ps1 was always per-user, so these are always under HKCU.
  RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppId}');
  DeleteFile(ExpandConstant('{userprograms}\{#AppName}.lnk'));
  DeleteFile(ExpandConstant('{app}\uninstall.ps1'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RemoveLegacyScriptInstall;
    WarnAboutOtherModeInstall;
  end;
end;
