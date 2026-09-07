; Inno Setup script for Zendesk Warning Light.
;
; Build with:  .\build.ps1 -Installer      (produces dist\ZendeskWarningLight-Setup.exe)
;
; Installs per-user into %LOCALAPPDATA%\Programs, so it never asks for administrator
; rights. See the [Setup] notes below and README.md for the silent-install switches.

#define AppName      "Zendesk Warning Light"
#define AppId        "ZendeskWarningLight"
#define AppPublisher "Karl Almqvist"
#define AppExe       "ZendeskWarningLight.exe"
#define AppVersion   "2.0.0"

[Setup]
AppId={{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup

; Per-user install: no UAC prompt, no admin rights.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#AppId}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
AllowNoIcons=yes

OutputDir=..\dist
OutputBaseFilename={#AppId}-Setup
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
Name: "{userdesktop}\{#AppName}";     Filename: "{app}\{#AppExe}"; Check: WantDesktopIcon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
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

// The app is a tray program that holds its own files open, so it has to be closed
// before we overwrite it. Runs after the wizard, before any file is copied.
procedure StopRunningApp;
var
  ResultCode: Integer;
begin
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
  RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppId}');
  DeleteFile(ExpandConstant('{userprograms}\{#AppName}.lnk'));
  DeleteFile(ExpandConstant('{app}\uninstall.ps1'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveLegacyScriptInstall;
end;
