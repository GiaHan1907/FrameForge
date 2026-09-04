#define MyAppName "FrameForge"
#ifndef MyAppVersion
#define MyAppVersion "0.1.39"
#endif
#define MyAppPublisher "FrameForge"
#define MyAppExeName "VideoScreenshotFilter.exe"
#define DistDir "dist\VideoScreenshotFilter"

[Setup]
AppId={{B4D0F1D3-6F4A-4F3D-A61B-9A9D7A2B2E55}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=FrameForge-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
CompressionThreads=auto
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=yes
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "*.map,*.pdb,*.log,*.tmp"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "FrameForge windowed app"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "FrameForge windowed app"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\VideoScreenshotFilter\yt_dlp_updates"
