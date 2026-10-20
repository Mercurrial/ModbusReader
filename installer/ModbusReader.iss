; installer/ModbusReader.iss — the installer.
;
; Build: python tools/build_installer.py   (one-folder PyInstaller build, then
; ISCC with /DAppVersion from version.py). Output: dist\ModbusReader-Setup.exe —
; the same name in every release, so one link always downloads the latest
; (releases/latest/download/ModbusReader-Setup.exe). The version is in the
; file's properties and on the wizard's pages.
;
; Two install modes, asked at the start (/ALLUSERS or /CURRENTUSER skip the
; question): for all users — C:\Program Files\ModbusReader, administrator
; rights (the default, the usual place) — or for me only —
; %LOCALAPPDATA%\Programs\ModbusReader, no rights needed. Either way: Start-menu
; shortcut, desktop shortcut (a checkbox), .mbproj opens in the app, an
; uninstaller in "Apps & features". Settings live in %APPDATA%\ModbusReader of
; each user (the app sees unins000.exe beside itself and keeps its files
; there), so an update or an uninstall never touches them.
;
; Self-update (updater.py): the running app starts the new installer with
;   /SILENT /SUPPRESSMSGBOXES /NORESTART /SP- /WAITPID=<its pid>
; and quits; InitializeSetup below waits for that pid, the install runs with
; only a progress bar, and the [Run] entry (no skipifsilent) starts the app.
; An update keeps the install mode (UsePreviousPrivileges); for an all-users
; install Setup elevates itself, so Windows asks for confirmation (UAC), and
; the postinstall [Run] entry still starts the app WITHOUT admin rights — the
; reason the app must never start the installer elevated itself.

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
AppPublisherURL=https://github.com/Mercurrial/ModbusReader
AppSupportURL=https://github.com/Mercurrial/ModbusReader/issues
AppUpdatesURL=https://github.com/Mercurrial/ModbusReader/releases/latest
AppCopyright=© 2026 Mercurrial
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCopyright=© 2026 Mercurrial
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=yes
OutputDir=..\dist
OutputBaseFilename=ModbusReader-Setup
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

[Messages]
; The install-mode question, shorter than Inno's stock wording ("… может быть
; установлена либо для всех пользователей (требуются привилегии
; администратора), либо только для вас"): the shield icon on the first choice
; already says that it needs administrator rights.
ru.PrivilegesRequiredOverrideTitle=Установка — {#AppName}
ru.PrivilegesRequiredOverrideInstruction=Для кого установить {#AppName}?
ru.PrivilegesRequiredOverrideText1=
ru.PrivilegesRequiredOverrideText2=
ru.PrivilegesRequiredOverrideAllUsers=Для &всех пользователей
ru.PrivilegesRequiredOverrideAllUsersRecommended=Для &всех пользователей (рекомендуется)
ru.PrivilegesRequiredOverrideCurrentUser=Только для &меня
ru.PrivilegesRequiredOverrideCurrentUserRecommended=Только для &меня (рекомендуется)
en.PrivilegesRequiredOverrideTitle=Setup — {#AppName}
en.PrivilegesRequiredOverrideInstruction=Install {#AppName} for
en.PrivilegesRequiredOverrideText1=
en.PrivilegesRequiredOverrideText2=
en.PrivilegesRequiredOverrideAllUsers=&All users
en.PrivilegesRequiredOverrideAllUsersRecommended=&All users (recommended)
en.PrivilegesRequiredOverrideCurrentUser=Only &me
en.PrivilegesRequiredOverrideCurrentUserRecommended=Only &me (recommended)

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

{ ── «Обзор…» on the destination page ──────────────────────────────────
  Inno's own folder dialog has no «New folder» and no context menu (and its
  «Make New Folder» variant stops appending the program's folder name). This
  is the Explorer folder picker instead — new folders, right-click menu,
  address bar — and the chosen folder still gets \ModbusReader appended, so
  picking D:\Tools installs into D:\Tools\ModbusReader. If the picker cannot
  be created (very old Windows), the classic one with a «New folder» button. }
const
  CLSID_FileOpenDialog = '{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}';
  IID_IShellItem = '{43826D1E-E718-42EE-BC55-A1E261C37BFE}';
  FOS_PICKFOLDERS = $20;
  FOS_FORCEFILESYSTEM = $40;
  FOS_PATHMUSTEXIST = $800;
  SIGDN_FILESYSPATH = $80058000;

type
  { Only the methods called here are typed; the dummies keep the vtable order. }
  IShellItem = interface(IUnknown)
    '{43826D1E-E718-42EE-BC55-A1E261C37BFE}'
    procedure DummyBindToHandler;
    procedure DummyGetParent;
    { The name comes back as a CoTaskMem LPWSTR: taken as a raw pointer —
      declared "out String" it crashed (access violation). Setup is 32-bit. }
    function GetDisplayName(sigdnName: DWORD; out ppszName: Cardinal): HResult;
    procedure DummyGetAttributes;
    procedure DummyCompare;
  end;

  IFileDialog = interface(IUnknown)
    '{42F85136-DB7E-439C-85F1-E4075D135FC8}'
    function Show(hwndOwner: HWND): HResult;
    procedure DummySetFileTypes;
    procedure DummySetFileTypeIndex;
    procedure DummyGetFileTypeIndex;
    procedure DummyAdvise;
    procedure DummyUnadvise;
    function SetOptions(fos: DWORD): HResult;
    function GetOptions(out pfos: DWORD): HResult;
    procedure DummySetDefaultFolder;
    function SetFolder(psi: IShellItem): HResult;
    procedure DummyGetFolder;
    procedure DummyGetCurrentSelection;
    procedure DummySetFileName;
    procedure DummyGetFileName;
    function SetTitle(pszTitle: String): HResult;
    procedure DummySetOkButtonLabel;
    procedure DummySetFileNameLabel;
    function GetResult(out ppsi: IShellItem): HResult;
  end;

function SHCreateItemFromParsingName(pszPath: String; pbc: Cardinal;
  var riid: TGUID; out ppv: IShellItem): HResult;
  external 'SHCreateItemFromParsingName@shell32.dll stdcall';
function lstrlenW(lpString: Cardinal): Integer;
  external 'lstrlenW@kernel32.dll stdcall';
function lstrcpynW(lpString1: String; lpString2: Cardinal; iMaxLength: Integer): Cardinal;
  external 'lstrcpynW@kernel32.dll stdcall';
procedure CoTaskMemFree(pv: Cardinal);
  external 'CoTaskMemFree@ole32.dll stdcall';

{ A CoTaskMem-allocated LPWSTR into a String; frees it. }
function TakeWideString(P: Cardinal): String;
var
  N: Integer;
begin
  Result := '';
  if P = 0 then
    Exit;
  N := lstrlenW(P);
  SetLength(Result, N);
  if N > 0 then
    lstrcpynW(Result, P, N + 1);
  CoTaskMemFree(P);
end;

{ The folder to open the picker in: the nearest existing parent of the path
  in the box (C:\Program Files for the default). }
function ExistingParent(Path: String): String;
begin
  Result := RemoveBackslashUnlessRoot(ExtractFileDir(RemoveBackslashUnlessRoot(Path)));
  while (Result <> '') and not DirExists(Result) do
  begin
    if Result = ExtractFileDir(Result) then
    begin
      Result := '';
      Break;
    end;
    Result := ExtractFileDir(Result);
  end;
end;

{ D:\Tools → D:\Tools\ModbusReader; a folder already called ModbusReader is
  taken as it is (reinstalling into the old place). }
function WithAppFolder(Dir: String): String;
begin
  Dir := RemoveBackslashUnlessRoot(Dir);
  if CompareText(ExtractFileName(Dir), '{#AppName}') = 0 then
    Result := Dir
  else
    Result := AddBackslash(Dir) + '{#AppName}';
end;

function PickFolderModern(var Dir: String): Boolean;
var
  Dlg: IFileDialog;
  Item, Start: IShellItem;
  Opts: DWORD;
  Path: String;
  Raw: Cardinal;
  Iid: TGUID;
  Hr: HResult;
begin
  Result := False;
  Dlg := IFileDialog(CreateComObject(StringToGUID(CLSID_FileOpenDialog)));
  OleCheck(Dlg.GetOptions(Opts));
  OleCheck(Dlg.SetOptions(Opts or FOS_PICKFOLDERS or FOS_FORCEFILESYSTEM or FOS_PATHMUSTEXIST));
  Dlg.SetTitle(SetupMessage(msgBrowseDialogTitle));
  if Dir <> '' then
  begin
    Iid := StringToGUID(IID_IShellItem);
    if SHCreateItemFromParsingName(Dir, 0, Iid, Start) = 0 then
      Dlg.SetFolder(Start);
  end;
  Hr := Dlg.Show(WizardForm.Handle);
  if Hr <> 0 then
    Exit;                                  { cancelled (or failed): keep the path }
  OleCheck(Dlg.GetResult(Item));
  OleCheck(Item.GetDisplayName(SIGDN_FILESYSPATH, Raw));
  Path := TakeWideString(Raw);
  if Path = '' then
    Exit;
  Dir := Path;
  Result := True;
end;

procedure DirBrowseClick(Sender: TObject);
var
  Dir: String;
  Picked: Boolean;
begin
  Dir := ExistingParent(WizardForm.DirEdit.Text);
  try
    Picked := PickFolderModern(Dir);
  except
    Log('Explorer folder picker unavailable: ' + GetExceptionMessage);
    Dir := ExistingParent(WizardForm.DirEdit.Text);
    Picked := BrowseForFolder(SetupMessage(msgBrowseDialogLabel), Dir, True);
  end;
  if Picked then
    WizardForm.DirEdit.Text := WithAppFolder(Dir);
end;

procedure InitializeWizard();
begin
  WizardForm.DirBrowseButton.OnClick := @DirBrowseClick;
end;
