@echo off
cd /d "%~dp0"
title SEACE Buscador
echo.
echo  ============================================
echo          SEACE Buscador
echo      Iniciando aplicacion, espere...
echo  ============================================
echo.

py --version >nul 2>&1
if errorlevel 1 goto sinpython

echo Usando Python:
py --version
echo.

:: Recrear venv si no existe o si esta incompleto
if not exist ".venv\Scripts\activate.bat" (
    echo Configurando entorno por primera vez...
    echo Esto puede tardar 2-3 minutos, espere...
    echo.
    if exist ".venv" rmdir /s /q .venv
    py -m venv .venv
)

call .venv\Scripts\activate.bat

:: Instalar dependencias si falta cualquier modulo clave
python -c "import customtkinter, bcrypt, sqlalchemy" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    python -m pip install --quiet --upgrade pip
    python -m pip install -r requirements.txt
    echo Dependencias instaladas.
    echo.
)

echo Iniciando SEACE Buscador...
echo.
python desktop_app.py
if errorlevel 1 (
    echo.
    echo La aplicacion se cerro con un error.
    pause
)
goto fin

:sinpython
echo ERROR: Python no esta instalado.
echo Descargue Python desde: https://www.python.org/downloads/
echo Durante la instalacion marque "Add Python to PATH"
echo.
pause

:fin
