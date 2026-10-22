; installer/ModbusReader.iss — the installer.
;
; Build: python tools/build_installer.py   (the one-folder PyInstaller build,
; the launcher, then ISCC with /DAppVersion from version.py). Output:
; dist\ModbusReader-Setup.exe — the same name in every release, so one link
; always downloads the latest.
;
; LAYOUT (since 26.10.3) — every version in its own folder:
;   {app}\ModbusReader.exe        the launcher (installer/launcher): starts the
;                                 newest finished version; shortcuts, taskbar
;                                 pins and .mbproj files point here
;   {app}\app-<version>\…         the program (the PyInstaller folder); the
;                                 file ".installed" is written into it last
;   {app}\unins000.exe            the uninstaller
; An update therefore never replaces a file in use: the running app installs
; the next version beside itself in the background (/VERYSILENT, see
; core/updater.py) and "restart" just starts the new folder. The app removes
; the folders of older versions on its next start.
;
; Two install modes, asked first (/ALLUSERS or /CURRENTUSER skip the
; question): for me only — %LOCALAPPDATA%\Programs\ModbusReader, no rights
; needed, updates install without a single question (the default) — or for
; all users — C:\Program Files\ModbusReader; Windows then asks for permission
; at the install and at every update. Start-menu shortcut, desktop shortcut,
; .mbproj opens in the app, an uninstaller in «Apps». Settings live in
; %APPDATA%\ModbusReader of each user, untouched by updates and uninstalls.
;
; Looks: the app's palette (light or dark, as Windows is), no bevels, no
; stock images; one page of our own (where, a desktop shortcut) instead of
; Inno's directory and task pages. /PROGRESS=<file> receives the progress
; ("progress <done> <max>", at the end "done <folder>") for the app's own
; progress bar during a background update.
;
; Started by an older app (≤ 26.10.2) as /SILENT … /WAITPID=<pid>: the
; progress window only, then the launcher starts the new version.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "ModbusReader"
#define AppExe "ModbusReader.exe"
#define VersionDir "app-" + AppVersion
#define AppUserModelID "Mercurrial.ModbusReader"

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
DisableReadyPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
UsePreviousPrivileges=yes
OutputDir=..\dist
OutputBaseFilename=ModbusReader-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; The app's palette: bg_1 of the light / dark theme. dynamic follows Windows.
WizardStyle=modern dynamic windows11 hidebevels
WizardBackColor=#f6f4f2
WizardBackColorDynamicDark=#0e1114
WizardImageFile=
WizardSmallImageFile=
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
; The install-mode question, shorter than Inno's stock wording; chosen by the
; user out of four mock-ups. The default is now "for me only" (updates need
; no permission then); the framed button is the one Enter picks.
ru.PrivilegesRequiredOverrideTitle=Установка — {#AppName}
ru.PrivilegesRequiredOverrideInstruction=Выберите режим установки
ru.PrivilegesRequiredOverrideText1=Для всех пользователей нужны права администратора — и при каждом обновлении тоже.
ru.PrivilegesRequiredOverrideText2=Для всех пользователей нужны права администратора — и при каждом обновлении тоже.
ru.PrivilegesRequiredOverrideAllUsers=Для &всех пользователей
ru.PrivilegesRequiredOverrideAllUsersRecommended=Для &всех пользователей
ru.PrivilegesRequiredOverrideCurrentUser=Только для &меня
ru.PrivilegesRequiredOverrideCurrentUserRecommended=Только для &меня
en.PrivilegesRequiredOverrideTitle=Setup — {#AppName}
en.PrivilegesRequiredOverrideInstruction=Choose how to install
en.PrivilegesRequiredOverrideText1=Installing for all users needs administrator rights — at every update too.
en.PrivilegesRequiredOverrideText2=Installing for all users needs administrator rights — at every update too.
en.PrivilegesRequiredOverrideAllUsers=For &all users
en.PrivilegesRequiredOverrideAllUsersRecommended=For &all users
en.PrivilegesRequiredOverrideCurrentUser=For &me only
en.PrivilegesRequiredOverrideCurrentUserRecommended=For &me only
; The pages Inno still shows, in the app's words.
ru.WizardInstalling=Установка
ru.InstallingLabel=Ставлю {#AppName} — это займёт меньше минуты.
ru.FinishedHeadingLabel={#AppName} установлен
ru.FinishedLabelNoIcons=Программа готова к работе. Новые версии она поставит сама.
ru.FinishedLabel=Программа есть в меню «Пуск». Новые версии она поставит сама.
ru.ClickFinish=
en.WizardInstalling=Installing
en.InstallingLabel=Installing {#AppName} — this takes less than a minute.
en.FinishedHeadingLabel={#AppName} is installed
en.FinishedLabelNoIcons=The program is ready. It installs new versions by itself.
en.FinishedLabel=The program is in the Start menu. It installs new versions by itself.
en.ClickFinish=

[CustomMessages]
ru.ProjectFile=Проект ModbusReader
en.ProjectFile=ModbusReader project
ru.PageTitle=Установка {#AppName} {#AppVersion}
en.PageTitle=Install {#AppName} {#AppVersion}
ru.PageTitleUpdate=Обновление {#AppName} до {#AppVersion}
en.PageTitleUpdate=Update {#AppName} to {#AppVersion}
ru.Tagline=Наладка и мониторинг приборов по Modbus RTU и TCP
en.Tagline=Commissioning and monitoring of Modbus RTU and TCP devices
ru.FolderLabel=Папка
en.FolderLabel=Folder
ru.Browse=Изменить…
en.Browse=Change…
ru.DesktopShortcut=Ярлык на рабочем столе
en.DesktopShortcut=Desktop shortcut
ru.UpdateNote=Будет обновлена установленная версия. Настройки, проекты и карты останутся как есть.
en.UpdateNote=The installed version will be updated. Settings, projects and maps stay as they are.
ru.InstallButton=Установить
en.InstallButton=Install
ru.UpdateButton=Обновить
en.UpdateButton=Update
ru.LicenseNote=Бесплатно · открытый код (GPL-3.0)
en.LicenseNote=Free · open source (GPL-3.0)
ru.NeedFolder=Укажите папку для установки.
en.NeedFolder=Choose a folder to install into.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; ≤ 26.10.2 kept the program in the root; the launcher takes its exe's place
; and the old bundle goes.
Type: filesandordirs; Name: "{app}\_internal"
; This version is not "installed" until the very end (the launcher would
; start a half-copied folder otherwise).
Type: files; Name: "{app}\{#VersionDir}\.installed"

[Files]
Source: "..\build\launcher\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ModbusReader\*"; DestDir: "{app}\{#VersionDir}"; Flags: ignoreversion recursesubdirs createallsubdirs
; GPL: the licence goes with the program, readable without digging into _internal.
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_LICENSES.txt"; Flags: ignoreversion
; The logo on our page (never installed).
Source: "..\assets\app.png"; Flags: dontcopy

[Icons]
; The AppUserModelID is the one the app gives its windows: pinning the running
; app to the taskbar pins this shortcut (the launcher), not a version folder
; that the next update removes.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.mbproj"; ValueType: string; ValueName: ""; ValueData: "ModbusReader.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\ModbusReader.Project"; ValueType: string; ValueName: ""; ValueData: "{cm:ProjectFile}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\ModbusReader.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\ModbusReader.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
; No skipifsilent: after an update started by an older app (/SILENT) the new
; version starts by itself. /NOLAUNCH (background updates, roll-outs, tests)
; installs without starting it.
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

{ A switch's value from this process's command line ('' when absent):
  /NAME=value. Works in Setup and in the uninstaller alike. }
function SwitchValue(Name: String): String;
var
  I: Integer;
  Prefix: String;
begin
  Result := '';
  Prefix := '/' + Uppercase(Name) + '=';
  for I := 1 to ParamCount do
    if Pos(Prefix, Uppercase(ParamStr(I))) = 1 then
      Result := Copy(ParamStr(I), Length(Prefix) + 1, MaxInt);
end;

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

{ /WAITPID=<pid>: the app that started this run is still closing; touch
  nothing until it is gone (at most two minutes). }
procedure WaitForPid();
var
  Pid: Integer;
  H: THandle;
begin
  Pid := StrToIntDef(SwitchValue('WAITPID'), 0);
  if Pid > 0 then
  begin
    H := OpenProcess(SYNCHRONIZE, 0, Pid);
    if H <> 0 then
    begin
      WaitForSingleObject(H, 120000);
      CloseHandle(H);
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  WaitForPid();
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  WaitForPid();
  Result := True;
end;

{ ── the app's progress bar (/PROGRESS=<file>) ─────────────────────────── }
procedure WriteProgress(Text: String);
var
  F: String;
begin
  F := SwitchValue('PROGRESS');
  if F <> '' then
    SaveStringToFile(F, Text, False);
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
begin
  WriteProgress('progress ' + IntToStr(CurProgress) + ' ' + IntToStr(MaxProgress));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Last: from now on the launcher may start this version. }
    SaveStringToFile(ExpandConstant('{app}\{#VersionDir}\.installed'), '{#AppVersion}', False);
    WriteProgress('done ' + ExpandConstant('{app}'));
  end;
end;

{ Uninstall: every version folder goes, including the ones later updates
  added and the markers written by code (not in the uninstall log). }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  FindRec: TFindRec;
  Root: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  Root := ExpandConstant('{app}');
  if FindFirst(Root + '\app-*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          DelTree(Root + '\' + FindRec.Name, True, True, True);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  RemoveDir(Root);
end;

{ ── the folder picker ─────────────────────────────────────────────────
  The Explorer folder picker — new folders, right-click menu, address bar;
  the chosen folder gets \ModbusReader appended (D:\Tools →
  D:\Tools\ModbusReader). The classic one if it cannot be created. }
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

{ The folder to open the picker in: the nearest existing parent. }
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

{ ── our page: where, and a desktop shortcut ──────────────────────────── }
var
  MainPage: TWizardPage;
  FolderEdit: TNewEdit;
  BrowseButton: TNewButton;
  DesktopCheck: TNewCheckBox;
  FinishLogo: TBitmapImage;
  IsUpdate: Boolean;
  InnerTop, InnerHeight: Integer;

procedure BrowseClick(Sender: TObject);
var
  Dir: String;
  Picked: Boolean;
begin
  Dir := ExistingParent(FolderEdit.Text);
  try
    Picked := PickFolderModern(Dir);
  except
    Log('Explorer folder picker unavailable: ' + GetExceptionMessage);
    Dir := ExistingParent(FolderEdit.Text);
    Picked := BrowseForFolder(SetupMessage(msgBrowseDialogLabel), Dir, True);
  end;
  if Picked then
    FolderEdit.Text := WithAppFolder(Dir);
end;

function NewLabel(Parent: TWinControl; Top: Integer; Text: String; Size: Integer;
  Bold: Boolean): TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := Parent;
  Result.Top := Top;
  Result.Left := 0;
  Result.AutoSize := True;
  Result.WordWrap := False;
  Result.Caption := Text;
  if Size > 0 then
    Result.Font.Size := Size;
  if Bold then
    Result.Font.Style := [fsBold];
end;

procedure BuildMainPage();
var
  Logo: TBitmapImage;
  Title, Tagline, Lbl, Note: TNewStaticText;
  Surface: TNewNotebookPage;
  Y: Integer;
begin
  IsUpdate := WizardForm.PrevAppDir <> '';
  MainPage := CreateCustomPage(wpWelcome, '', '');
  Surface := MainPage.Surface;

  ExtractTemporaryFile('app.png');
  Logo := TBitmapImage.Create(WizardForm);
  Logo.Parent := Surface;
  Logo.Left := 0;
  Logo.Top := ScaleY(4);
  Logo.Width := ScaleX(52);
  Logo.Height := ScaleY(52);
  Logo.Stretch := True;
  Logo.BackColor := clNone;                 { the PNG's own transparency }
  Logo.PngImage.LoadFromFile(ExpandConstant('{tmp}\app.png'));

  if IsUpdate then
    Title := NewLabel(Surface, ScaleY(6), CustomMessage('PageTitleUpdate'), 15, True)
  else
    Title := NewLabel(Surface, ScaleY(6), CustomMessage('PageTitle'), 15, True);
  Title.Left := ScaleX(68);
  Tagline := NewLabel(Surface, Title.Top + Title.Height + ScaleY(4), CustomMessage('Tagline'), 0, False);
  Tagline.Left := ScaleX(68);

  Y := ScaleY(92);
  Lbl := NewLabel(Surface, Y, CustomMessage('FolderLabel'), 0, False);
  Y := Y + Lbl.Height + ScaleY(6);

  BrowseButton := TNewButton.Create(WizardForm);
  BrowseButton.Parent := Surface;
  BrowseButton.Caption := CustomMessage('Browse');
  BrowseButton.Width := ScaleX(110);
  BrowseButton.Height := WizardForm.NextButton.Height;
  BrowseButton.Top := Y - ScaleY(1);
  BrowseButton.Left := Surface.Width - BrowseButton.Width;
  BrowseButton.OnClick := @BrowseClick;

  FolderEdit := TNewEdit.Create(WizardForm);
  FolderEdit.Parent := Surface;
  FolderEdit.Top := Y;
  FolderEdit.Left := 0;
  FolderEdit.Width := BrowseButton.Left - ScaleX(10);
  FolderEdit.Text := WizardForm.DirEdit.Text;
  Y := Y + BrowseButton.Height + ScaleY(18);

  DesktopCheck := TNewCheckBox.Create(WizardForm);
  DesktopCheck.Parent := Surface;
  DesktopCheck.Top := Y;
  DesktopCheck.Left := 0;
  DesktopCheck.Width := Surface.Width;
  DesktopCheck.Height := ScaleY(22);
  DesktopCheck.Caption := CustomMessage('DesktopShortcut');
  DesktopCheck.Checked := True;

  if IsUpdate then
  begin
    { An update keeps its place and its shortcuts. }
    FolderEdit.Enabled := False;
    BrowseButton.Visible := False;
    FolderEdit.Width := Surface.Width;
    DesktopCheck.Visible := False;
    Note := NewLabel(Surface, Y, CustomMessage('UpdateNote'), 0, False);
    Note.AutoSize := False;
    Note.WordWrap := True;
    Note.Width := Surface.Width;
    Note.Height := ScaleY(40);
  end;

  Note := NewLabel(Surface, Surface.Height - ScaleY(20), CustomMessage('LicenseNote'), 0, False);
  Note.Font.Color := clGrayText;
end;

{ The finished page: no picture column — the logo and the words on the
  left, like our page. }
procedure BuildFinishedPage();
var
  Left: Integer;
begin
  FinishLogo := TBitmapImage.Create(WizardForm);
  FinishLogo.Parent := WizardForm.FinishedPage;
  FinishLogo.Left := ScaleX(40);
  FinishLogo.Top := WizardForm.FinishedHeadingLabel.Top;
  FinishLogo.Width := ScaleX(52);
  FinishLogo.Height := ScaleY(52);
  FinishLogo.Stretch := True;
  FinishLogo.BackColor := clNone;
  FinishLogo.PngImage.LoadFromFile(ExpandConstant('{tmp}\app.png'));
  Left := ScaleX(40 + 52 + 16);
  WizardForm.WizardBitmapImage2.Visible := False;
  WizardForm.FinishedHeadingLabel.Left := Left;
  WizardForm.FinishedHeadingLabel.Width := WizardForm.FinishedPage.ClientWidth - Left - ScaleX(40);
  WizardForm.FinishedLabel.Left := Left;
  WizardForm.FinishedLabel.Width := WizardForm.FinishedHeadingLabel.Width;
  WizardForm.RunList.Left := Left;
  WizardForm.RunList.Width := WizardForm.FinishedHeadingLabel.Width;
  WizardForm.YesRadio.Left := Left;
  WizardForm.NoRadio.Left := Left;
end;

procedure InitializeWizard();
begin
  BuildMainPage();
  BuildFinishedPage();
  InnerTop := WizardForm.InnerNotebook.Top;
  InnerHeight := WizardForm.InnerNotebook.Height;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Our page carries the folder and the shortcut. }
  Result := (PageID = wpSelectDir) or (PageID = wpSelectTasks);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { Our page has its own heading (logo, title): no stock header strip
    above it — the page takes that room. }
  WizardForm.MainPanel.Visible := CurPageID <> MainPage.ID;
  if CurPageID = MainPage.ID then
  begin
    WizardForm.InnerNotebook.Top := InnerTop - WizardForm.MainPanel.Height + ScaleY(12);
    WizardForm.InnerNotebook.Height := InnerHeight + WizardForm.MainPanel.Height - ScaleY(12);
  end
  else
  begin
    WizardForm.InnerNotebook.Top := InnerTop;
    WizardForm.InnerNotebook.Height := InnerHeight;
  end;
  if CurPageID = MainPage.ID then
  begin
    if IsUpdate then
      WizardForm.NextButton.Caption := CustomMessage('UpdateButton')
    else
      WizardForm.NextButton.Caption := CustomMessage('InstallButton');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID = MainPage.ID then
  begin
    Dir := Trim(FolderEdit.Text);
    if (Length(Dir) < 3) or ((Copy(Dir, 2, 2) <> ':\') and (Copy(Dir, 1, 2) <> '\\')) then
    begin
      MsgBox(CustomMessage('NeedFolder'), mbError, MB_OK);
      Result := False;
      Exit;
    end;
    WizardForm.DirEdit.Text := Dir;
    if not IsUpdate then
    begin
      if DesktopCheck.Checked then
        WizardSelectTasks('desktopicon')
      else
        WizardSelectTasks('!desktopicon');
    end;
  end;
end;
