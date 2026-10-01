; Installeur Inno Setup 6 de Claude Usage Tray.
; Compilé par la CI (ou build.ps1) : ISCC /DAppVersion=0.2.0 installer\ClaudeTracker.iss
; Attend le dossier PyInstaller dans dist\ClaudeTracker\.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Claude Usage Tray"
#define AppExe "ClaudeTracker.exe"

[Setup]
; AppId fixe : c'est ce qui permet aux mises à jour de remplacer l'installation existante.
AppId={{27E3A9DF-55DA-4D8F-AA88-CC08EA82A458}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=valentin1628
AppPublisherURL=https://github.com/valentin1628/claude-win-tracker
DefaultDirName={localappdata}\Programs\ClaudeTracker
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClaudeTracker-{#AppVersion}-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Ferme l'appli si elle tourne encore (mise à jour silencieuse).
CloseApplications=force
RestartApplications=no

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "autostart"; Description: "Lancer {#AppName} au démarrage de Windows"
Name: "desktopicon"; Description: "Créer un raccourci sur le bureau"; Flags: unchecked

[Files]
Source: "..\dist\ClaudeTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Repart d'un dossier propre (évite les vieilles bibliothèques d'une version précédente).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} - diagnostic"; Filename: "{app}\{#AppExe}"; Parameters: "--check"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Même valeur que autostart.py : la case « Lancer au démarrage » du menu reste cohérente.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "ClaudeUsageTray"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; Pas de skipifsilent : l'appli est relancée aussi après une mise à jour silencieuse.
Filename: "{app}\{#AppExe}"; Description: "Lancer {#AppName}"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
