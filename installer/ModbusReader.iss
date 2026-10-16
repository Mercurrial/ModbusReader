; installer/ModbusReader.iss — the per-user installer.
;
; Build: python tools/build_installer.py   (one-folder PyInstaller build, then
; ISCC with /DAppVersion from version.py). Output: dist\ModbusReader-Setup-X.Y.Z.exe
;
; Per user, no administrator rights: %LOCALAPPDATA%\Programs\ModbusReader,
; Start-menu shortcut, desktop shortcut (a checkbox), .mbproj opens in the app,
; an uninstaller in "Apps & features". Settings live in %APPDATA%\ModbusReader
; (the app sees unins000.exe beside itself and keeps its files there), so an
; update or an uninstall never touches them.
;
; Self-update (updater.py): the running app starts the new installer with
;   /SILENT /SUPPRESSMSGBOXES /NORESTART /SP- /WAITPID=<its pid>
; and quits; InitializeSetup below waits for that pid, the install runs with
; only a progress bar, and the [Run] entry (no skipifsilent) starts the app.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "ModbusReader"
#define AppExe "ModbusReader.exe"

[Setup]
AppId={{A571CF74-F203-4766-AF18-6780232E6CC4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Mercurrial
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ModbusReader-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.ProjectFile=Проект ModbusReader
en.ProjectFile=ModbusReader project

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; A new version's bundle replaces the old one completely — a module left
; over from the previous version must not be picked up.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\ModbusReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; GPL: the licence goes with the program, readable without digging into _internal.
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_LICENSES.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.mbproj"; ValueType: string; ValueName: ""; ValueData: "ModbusReader.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\ModbusReader.Project"; ValueType: string; ValueName: ""; ValueData: "{cm:ProjectFile}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\ModbusReader.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\ModbusReader.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
; No skipifsilent: after a silent self-update the app starts again by itself.
; /NOLAUNCH (unattended roll-outs, tests) installs without starting it.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall; Check: not NoLaunch

[Code]
const
  SYNCHRONIZE = $00100000;

function OpenProcess(dwDesiredAccess: Cardinal; bInheritHandle: Cardinal;
  dwProcessId: Cardinal): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle: THandle; dwMilliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Cardinal;
  external 'CloseHandle@kernel32.dll stdcall';

function NoLaunch(): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if (CompareText(ParamStr(I), '/NOLAUNCH') = 0) or
       (Pos('/NOLAUNCH=', Uppercase(ParamStr(I))) = 1) then
      Result := True;
end;

{ /WAITPID=<pid>: the app that started this update is still closing; copy
  nothing until it is gone (at most two minutes). }
function InitializeSetup(): Boolean;
var
  Pid: Integer;
  H: THandle;
begin
  Pid := StrToIntDef(ExpandConstant('{param:WAITPID|0}'), 0);
  if Pid > 0 then
  begin
    H := OpenProcess(SYNCHRONIZE, 0, Pid);
    if H <> 0 then
    begin
      WaitForSingleObject(H, 120000);
      CloseHandle(H);
    end;
  end;
  Result := True;
end;
