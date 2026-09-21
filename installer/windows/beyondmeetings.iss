; beyondMeetings — offline Windows installer (64-bit).
;
; Produces one file the user double-clicks. It needs no Python, no git, no
; curl, no PowerShell one-liner and no network connection: the interpreter,
; every wheel and ffmpeg are all inside it. See build_payload.py for how they
; get there, and setup-finish.ps1 for what happens once they are on disk.
;
; No administrator rights, by design. Everything lands under %LOCALAPPDATA%,
; which the user owns, so installing never raises a UAC prompt — the same
; rule install.ps1 follows.
;
; Build:  ISCC.exe /DPayload=<...>\payload /DAppVersion=0.1.0 beyondmeetings.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef Payload
  #define Payload "..\..\build\windows\payload"
#endif
#ifndef IconFile
  #define IconFile "..\..\src\beyondmeetings\assets\icon.ico"
#endif

#define AppName "beyondMeetings"
#define AppPublisher "beyondMeetings"
#define AppURL "https://github.com/nikhilm55/beyondmeetings"

[Setup]
; Fixed, so a later version upgrades this install instead of sitting beside it.
AppId={{2F8B6A14-9C3D-4E57-B0A1-7D2E5C9F4B68}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
UninstallDisplayName={#AppName}

; %LOCALAPPDATA%\beyondMeetings is ALSO where the application keeps its data
; — recordings, transcripts, config — because platformdirs resolves
; "beyondmeetings" to that path and Windows filenames are case-insensitive,
; so the two names are one directory. The program therefore installs into an
; `app` subdirectory and the uninstaller removes only that. Pointing {app} at
; the parent would make "uninstall" mean "delete every meeting you recorded".
DefaultDirName={localappdata}\{#AppName}\app

; No directory page: the paths above are not a preference. `doctor`,
; uninstall.ps1 and the application's own ffmpeg lookup all resolve
; %LOCALAPPDATA%\beyondMeetings\bin, and an install somewhere else would
; leave them looking at an empty directory.
DisableDirPage=yes
DisableProgramGroupPage=yes

; Never elevate. Combined with the install location this means no UAC prompt
; at any point, which is also what makes the install removable by the person
; who made it.
PrivilegesRequired=lowest

; 64-bit only, as asked. x64compatible rather than plain x64 so an ARM64
; Windows, which runs x64 binaries under emulation, is not turned away.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputBaseFilename={#AppName}-Setup-x64
OutputDir=.
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\beyondmeetings.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; The payload is ~300 MB unpacked and every byte of it is ours, so Inno's own
; in-use detection has nothing useful to say. Stopping a running instance is
; handled in [Code], where it can be scoped to processes inside {app}.
CloseApplications=no
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
; The relocatable CPython. python.exe sits at the root of this directory.
Source: "{#Payload}\runtime\*"; DestDir: "{app}\runtime"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; Read once, by setup-finish.ps1, which then deletes them.
Source: "{#Payload}\wheels\*"; DestDir: "{app}\wheels"; Flags: ignoreversion

; Into the bin directory the application searches for tools, NOT into {app}:
; beyondmeetings.tools.which_tool looks in %LOCALAPPDATA%\beyondMeetings\bin,
; which is how ffmpeg is found without touching the user's PATH.
Source: "{#Payload}\bin\ffmpeg.exe"; DestDir: "{localappdata}\{#AppName}\bin"; \
    Flags: ignoreversion
Source: "{#Payload}\bin\ffprobe.exe"; DestDir: "{localappdata}\{#AppName}\bin"; \
    Flags: ignoreversion

Source: "setup-finish.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "beyondmeetings.ico"; \
    Flags: ignoreversion

[Icons]
; pythonw.exe, not beyondmeetings.exe: the console script flashes a black
; window on the way up. `open` rather than `serve` because it is idempotent —
; it connects to a server that is already running instead of failing to bind
; the port — and because the app is used in a browser, so there is no native
; window to open and no WebView2 runtime to depend on.
Name: "{userprograms}\{#AppName}"; Filename: "{app}\venv\Scripts\pythonw.exe"; \
    Parameters: "-m beyondmeetings open"; WorkingDir: "{app}"; \
    IconFilename: "{app}\beyondmeetings.ico"; \
    Comment: "Record meetings and keep structured notes locally"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\venv\Scripts\pythonw.exe"; \
    Parameters: "-m beyondmeetings open"; WorkingDir: "{app}"; \
    IconFilename: "{app}\beyondmeetings.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: "-m beyondmeetings open"; \
    Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The venv and the interpreter. Safe to remove wholesale: the user's
; recordings are a *sibling* of {app}, never inside it.
Type: filesandordirs; Name: "{app}"
; Written by setup-finish.ps1, so Inno does not know about it.
Type: files; Name: "{localappdata}\{#AppName}\bin\beyondmeetings.cmd"
; Only present if the user turned start-at-login on from the wizard.
Type: files; Name: "{userstartup}\{#AppName}.lnk"
Type: dirifempty; Name: "{localappdata}\{#AppName}\bin"
; Deliberately no rule for {localappdata}\beyondMeetings itself — see the
; note on DefaultDirName. That directory holds the meetings.

[Code]

(* Stop anything running out of the install directory.

   An upgrade cannot overwrite a locked python .dll, and an uninstall cannot
   delete one. Scoping the match to executables inside the install directory
   is what makes this safe: the user's own Python, and anyone else's, is left
   alone. Note for editors: Pascal brace comments do not nest, so an Inno
   constant written out in one would end the comment early — hence (* *). *)
procedure StopRunningApp();
var
  ResultCode: Integer;
  Command: String;
begin
  Command :=
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ' +
    '"$ErrorActionPreference = ''SilentlyContinue''; ' +
    '$root = ''' + ExpandConstant('{app}') + '''; ' +
    'Get-Process | Where-Object { $_.Path -and ' +
    '$_.Path.StartsWith($root, ''OrdinalIgnoreCase'') } | ' +
    'Stop-Process -Force"';
  Exec('powershell.exe', Command, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

{ Build the environment out of the wheels that were just copied. }
function RunSetupFinish(): Integer;
var
  ResultCode: Integer;
begin
  if Exec('powershell.exe',
      '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{app}\setup-finish.ps1') + '" -Root "' +
        ExpandConstant('{app}') + '" -BinDir "' +
        ExpandConstant('{localappdata}\{#AppName}\bin') + '"',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := ResultCode
  else
    Result := -1;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption :=
      'Setting up the Python environment. This takes about a minute...';
    Code := RunSetupFinish();
    if Code <> 0 then
      { Not a fatal error: the files are on disk and re-running the setup is a
        real fix. What matters is that the user is told, and told where to
        look, rather than being handed a Start Menu icon that does nothing. }
      MsgBox('{#AppName} was copied, but its Python environment could not be'
        + ' built (code ' + IntToStr(Code) + ').' + #13#10#13#10
        + 'The log is at ' + ExpandConstant('{%TEMP}\beyondmeetings-setup.log')
        + #13#10#13#10 + 'Running this installer again usually fixes it.',
        mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopRunningApp();
end;
