; ═══════════════════════════════════════════════════════════════════════════════
; SEACE Buscador — Script de instalación (Inno Setup 6)
;
; Requisitos previos:
;   1. Ejecutar PyInstaller:  pyinstaller desktop_app.spec
;      → genera dist\SEACE-Buscador\ con el .exe y todas las dependencias
;   2. Instalar Inno Setup 6:  https://jrsoftware.org/isdl.php
;   3. Abrir este archivo en Inno Setup IDE y presionar Compile
;      → genera installer\output\SEACEBuscador_Setup.exe
; ═══════════════════════════════════════════════════════════════════════════════

#define AppName      "SEACE Buscador"
#define AppVersion   "1.0.0"
#define AppPublisher "RxHub"
#define AppURL       "https://rxhub.tech"
#define AppExeName   "SEACE-Buscador.exe"
#define AppId        "{{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Instalar en Archivos de programa sin requerir admin
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Salida del instalador
OutputDir=output
OutputBaseFilename=SEACEBuscador_Setup_{#AppVersion}

; Icono del instalador (opcional — descomenta si tienes el archivo)
; SetupIconFile=..\assets\icon.ico

; Compresión
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Apariencia
WizardStyle=modern
WizardResizable=yes

; Privilegios — no requiere ser administrador
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

; Mostrar licencia (descomenta si creas un archivo LICENSE.txt)
; LicenseFile=..\LICENSE.txt

[Languages]
Name: "spanish";   MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english";   MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "Crear un icono en el &Escritorio"; \
    GroupDescription: "Iconos adicionales:"
Name: "quicklaunch"; \
    Description: "Agregar al men&ú de inicio rápido"; \
    GroupDescription: "Iconos adicionales:"; \
    Flags: unchecked

[Files]
; Todos los archivos generados por PyInstaller
Source: "..\dist\SEACE-Buscador\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Menú de inicio
Name: "{group}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    Comment: "Buscador de licitaciones SEACE"
Name: "{group}\Desinstalar {#AppName}"; \
    Filename: "{uninstallexe}"

; Escritorio (opcional, según tarea)
Name: "{commondesktop}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon; \
    Comment: "Buscador de licitaciones SEACE"

[Run]
; Ofrecer ejecutar la app al terminar la instalación
Filename: "{app}\{#AppExeName}"; \
    Description: "Iniciar {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Al desinstalar, eliminar la base de datos y el archivo .env si el usuario lo desea
; (solo si están dentro de la carpeta de la app — la BD por defecto está junto al .exe)
Type: filesandordirs; Name: "{app}\seace_leads.db"
Type: filesandordirs; Name: "{app}\.env"

[Code]
// Verificar que PyInstaller ya corrió antes de compilar el instalador
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
