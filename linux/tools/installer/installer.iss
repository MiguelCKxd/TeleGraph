; Inno Setup 6 script for TG-ASCII (per-user install, no administrator rights).
; Based on the 1.3.1 script (same AppId, so 1.3.2 upgrades 1.3.1 in place).
; Paths are passed by tools/installer/build_installer_vm.ps1:
;   ISCC /DMyAppVersion=1.3.2 /DSourceDir=<unzipped app> /DOutputDir=<dir> installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error SourceDir must point to the unzipped TG-ASCII-<version>-windows-x64 folder
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#define MyAppName "TeleGraph"
#define MyAppPublisher "TeleGraph"
#define MyAppExeName "TG-ASCII.exe"

[Setup]
AppId={{D37E6B41-7A85-42F3-9118-B5490AE84A22}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-Setup
SetupIconFile={#SourcePath}app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; TG-ASCII keeps running in the tray for notifications: close it (Restart
; Manager) before replacing its files, and offer to reopen it afterwards.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; New in 1.3.2: remove the previous version's bundled runtime before copying,
; so stale modules/DLLs from an older build are never mixed with the new ones.
; User data lives in %USERPROFILE%\.tg-ascii and is never touched.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "org.tgas.desktop"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "org.tgas.desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure RemoveLegacyShortcut(const LinkPath: String);
var
  Shell, Link, Files: Variant;
  Target, Arguments: String;
begin
  try
    { Use the same Windows shell filesystem view that created the shortcut. }
    Files := CreateOleObject('Scripting.FileSystemObject');
    if not Files.FileExists(LinkPath) then Exit;
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(LinkPath);
    Target := Link.TargetPath;
    Arguments := Link.Arguments;
    if (CompareText(Target, ExpandConstant('{app}\{#MyAppExeName}')) = 0) and
       (Arguments = '') and (Link.Description = '') and (Link.Hotkey = '') and
       (Link.WindowStyle = 1) and (Link.IconLocation = ',0') and
       (CompareText(Link.WorkingDirectory, ExpandConstant('{app}')) = 0) then
    begin
      Files.DeleteFile(LinkPath);
      Log('Removed the previous application shortcut: ' + LinkPath);
    end;
  except
    Log('Could not check the previous application shortcut: ' + GetExceptionMessage);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
  begin
    RemoveLegacyShortcut(ExpandConstant('{autoprograms}\TG-ASCII.lnk'));
    RemoveLegacyShortcut(ExpandConstant('{autodesktop}\TG-ASCII.lnk'));
  end;
end;
