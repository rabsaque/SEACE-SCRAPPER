@echo on
:: Cambiar al directorio donde esta este archivo
cd /d "%~dp0"
title SEACE Buscador - Diagnostico
echo.
echo ============================================
echo   SEACE Buscador - Modo Diagnostico
echo ============================================
echo.

echo [1] Buscando Python instalado...
where py 2>&1
where python 2>&1
where python3 2>&1
echo.

echo [2] Version de Python:
py --version 2>&1
python --version 2>&1
echo.

echo [3] Verificando pip:
py -m pip --version 2>&1
python -m pip --version 2>&1
echo.

echo [4] Creando entorno virtual...
py -m venv .venv_test 2>&1
if errorlevel 1 (
    python -m venv .venv_test 2>&1
)
echo.

echo [5] Activando entorno virtual...
call .venv_test\Scripts\activate.bat 2>&1
echo.

echo [6] Instalando customtkinter de prueba...
python -m pip install customtkinter 2>&1
echo.

echo [7] Probando importacion...
python -c "import customtkinter; print('customtkinter OK')" 2>&1
python -c "import tkinter; print('tkinter OK')" 2>&1
echo.

echo ============================================
echo   Diagnostico completado.
echo   Copie el texto de esta ventana y envielo
echo   al administrador del sistema.
echo ============================================
echo.
pause

:: Limpiar entorno de prueba
rmdir /s /q .venv_test 2>nul
