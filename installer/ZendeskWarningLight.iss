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
; NOTE: /S is an NSIS switch and does nothing here - Inno wants /VERYSILENT.
; InitializeSetup below fails fast on /S rather than opening a wizard no
; unattended deployment can ever finish.

#define AppName      "Zendesk Warning Light"
#define AppId        "ZendeskWarningLight"
#define AppPublisher "Karl Almqvist"
#define AppExe       "ZendeskWarningLight.exe"
#define AppVersion   "2.3.0"
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

; Default to a per-user install so a plain double-click needs no UAC prompt, but
; allow /ALLUSERS (or the dialog) to switch to a machine-wide one. Note that
; PrivilegesRequired=lowest means non-administrative mode *even when launched by
; an administrator*, so SYSTEM must pass /ALLUSERS explicitly - see the guard in
; InitializeSetup.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
DefaultDirName={autopf}\{#AppId}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
AllowNoIcons=yes

OutputDir=..\dist
; Version in the filename, so a colleague can tell what they were sent and
; two releases never silently overwrite one another.
OutputBaseFilename={#AppId}-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

; Keep a single setup running at a time.
SetupMutex={#AppId}-setup-mutex

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

[Run]
; Interactive install: offer a "start now" checkbox on the final page.
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

; Silent install: start it straight away unless /NOLAUNCH was passed.
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent; Check: ShouldLaunchAfterSilent

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

// Honour /NOLAUNCH (or /NOLAUNCH=1) during a silent install.
function ShouldLaunchAfterSilent: Boolean;
begin
  Result := not SwitchIsOn('NOLAUNCH');
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

function WantDesktopIcon: Boolean;
begin
  if WizardSilent then
    Result := SwitchIsOn('DESKTOPICON')
  else
    Result := WizardIsTaskSelected('desktopicon');
end;

// Refuse the two command lines that would otherwise fail in a way nobody can
// diagnose from an Intune report. Both abort with exit code 1 (failed to
// initialize) and say why in the /LOG file.
function InitializeSetup: Boolean;
var
  LocalAppData: String;
begin
  Result := True;

  // /S is NSIS syntax. Inno ignores it, shows the wizard, and an unattended
  // deployment then hangs until it times out.
  if SwitchIsOn('S') and not WizardSilent then
  begin
    Log('ABORT: /S is not an Inno Setup switch. Use /VERYSILENT (and /ALLUSERS '
        + 'or /CURRENTUSER). See README.md.');
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
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM "{#AppExe}" /F', '',
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
