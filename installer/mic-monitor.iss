; Установщик mic-monitor (Inno Setup 6).
; Сборка: pwsh -File ..\build-installer.ps1
; Ставится без прав администратора в %LOCALAPPDATA%\Programs\mic-monitor,
; создаёт ярлык в «Пуск», запись в «Параметры → Приложения» и деинсталлятор.

#define AppName "mic-monitor"
#define AppExeName "MicMonitor.exe"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppPublisher "Col-Verger"
#define AppURL "https://github.com/Col-Verger/mic-monitor"

[Setup]
AppId={{6F1B2C7A-3D4E-4A55-9C21-8E7B5D0A1F33}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MicMonitor-Setup-{#AppVersion}
SetupIconFile=..\mic.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Установщик mic-monitor
VersionInfoProductName={#AppName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.AdditionalIcons=Additional shortcuts:
russian.AdditionalIcons=Дополнительные ярлыки:
english.AutostartTask=Start mic-monitor when Windows starts
russian.AutostartTask=Запускать mic-monitor при входе в Windows
english.AppComment=Mic volume, live level and who changed it
russian.AppComment=Громкость микрофона и кто её менял

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutostartTask}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\README.ru.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "{cm:AppComment}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "mic-monitor"; \
    ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExeName} /F"; Flags: runhidden; RunOnceId: "StopApp"
