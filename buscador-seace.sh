#!/usr/bin/env bash
# run_app.sh — Quick launcher for the SEACE desktop app
# Usage: bash run_app.sh

set -e
cd "$(dirname "$0")"
VENV=".venv"

echo "=== SEACE Buscador — Launcher ==="

# 1. Check tkinter (system package, must be installed once with sudo)
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo ""
    echo "ERROR: python3-tk no está instalado."
    echo "Ejecuta este comando UNA VEZ para instalarlo:"
    echo ""
    echo "  sudo apt install python3-tk -y"
    echo ""
    exit 1
fi

# 2. Create venv if missing
if [ ! -f "$VENV/bin/python" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv "$VENV"
fi

# 3. Install/update dependencies inside venv
echo "Verificando dependencias..."
"$VENV/bin/pip" install --quiet -r requirements.txt

# 4. Install Playwright Chromium if missing
if ! "$VENV/bin/python" -c "
from playwright.sync_api import sync_playwright
import os
with sync_playwright() as p:
    ok = os.path.exists(p.chromium.executable_path)
exit(0 if ok else 1)
" 2>/dev/null; then
    echo "Instalando navegador Chromium (solo la primera vez)..."
    "$VENV/bin/python" -m playwright install chromium
fi

# 5. Launch the app
echo "Iniciando aplicación..."
exec "$VENV/bin/python" desktop_app.py
