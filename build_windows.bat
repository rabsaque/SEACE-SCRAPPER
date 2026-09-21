@echo off
REM ═══════════════════════════════════════════════════════════════════════════════
REM  build_windows.bat — Compila SEACE Buscador en Windows
REM  Ejecutar desde la raíz del proyecto en una ventana de comandos normal.
REM ═══════════════════════════════════════════════════════════════════════════════

title SEACE Buscador — Compilación

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║       SEACE Buscador — Compilador de instalador      ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM ── 1. Verificar Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no encontrado. Descargalo desde https://www.python.org
    pause
    exit /b 1
)
echo [OK] Python encontrado.

REM ── 2. Instalar dependencias ─────────────────────────────────────────────────
echo.
echo Instalando dependencias...
pip install -r requirements-windows.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] No se pudieron instalar las dependencias.
    pause
    exit /b 1
)

pip install pyinstaller
if %ERRORLEVEL% neq 0 (
    echo [ERROR] No se pudo instalar PyInstaller.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.

REM ── 3. Instalar Chromium para Playwright ─────────────────────────────────────
echo.
echo Instalando navegador Chromium (Playwright)...
python -m playwright install chromium
echo [OK] Chromium instalado.

REM ── 4. Compilar con PyInstaller ──────────────────────────────────────────────
echo.
echo Compilando ejecutable con PyInstaller...
pyinstaller desktop_app.spec --clean
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller falló. Revisa los mensajes de error arriba.
    pause
    exit /b 1
)
echo [OK] Ejecutable generado en dist\SEACE-Buscador\

REM ── 5. Verificar que Inno Setup esté instalado ───────────────────────────────
echo.
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo [AVISO] Inno Setup no encontrado en %ISCC%
    echo         Descargalo desde https://jrsoftware.org/isdl.php
    echo         Luego ejecuta manualmente:
    echo           %ISCC% installer\seace_buscador.iss
    echo.
    echo El ejecutable ya está listo en dist\SEACE-Buscador\SEACE-Buscador.exe
    pause
    exit /b 0
)

REM ── 6. Compilar el instalador con Inno Setup ─────────────────────────────────
echo Compilando instalador con Inno Setup...
%ISCC% installer\seace_buscador.iss
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Inno Setup falló.
    pause
    exit /b 1
)

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║   ✓ Instalador listo:                                ║
echo ║   installer\output\SEACEBuscador_Setup_1.0.0.exe     ║
echo ╚══════════════════════════════════════════════════════╝
echo.
pause
