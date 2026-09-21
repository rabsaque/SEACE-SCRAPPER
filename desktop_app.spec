# desktop_app.spec — PyInstaller build spec for SEACE Buscador
# ─────────────────────────────────────────────────────────────
# Build (run from the project root on Windows):
#   pip install pyinstaller
#   pyinstaller desktop_app.spec
#
# Output: dist\SEACE-Buscador\   ← folder ready to hand to Inno Setup
#         (or wrap with Inno Setup → SEACEBuscador_Setup.exe)

import sys
from pathlib import Path
import customtkinter

block_cipher = None
PROJECT = Path(SPECPATH)

# CustomTkinter ships its own assets (themes, images) — include them
ctk_path = Path(customtkinter.__file__).parent

# Playwright browser binaries downloaded during CI build
playwright_browsers = PROJECT / "playwright_browsers"

datas = [
    # CustomTkinter assets (themes + icons)
    (str(ctk_path), "customtkinter"),
    # All project source modules
    (str(PROJECT / "src"), "src"),
]

# Bundle Chromium if it was downloaded during CI
if playwright_browsers.exists():
    datas.append((str(playwright_browsers), "playwright_browsers"))

a = Analysis(
    [str(PROJECT / "desktop_app.py")],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # UI
        "customtkinter",
        "PIL",
        "PIL._tkinter_finder",
        "tkcalendar",
        "babel.numbers",
        "babel.dates",
        # Database
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "aiosqlite",
        # Playwright
        "playwright",
        "playwright.async_api",
        "playwright.sync_api",
        "playwright._impl._api_types",
        "playwright._impl._connection",
        # Project modules
        "src.config",
        "src.storage.models",
        "src.storage.repository",
        "src.scraper.search",
        "src.scraper.detail",
        "src.scraper.browser",
        "src.scraper.downloader",
        "src.ai.filter",
        "src.notifications.email_sender",
        "src.scheduler.service",
        # Utilities
        "loguru",
        "openpyxl",
        "openpyxl.styles",
        "tenacity",
        "httpx",
        "bcrypt",
        "groq",
        "openai",
        "APScheduler",
        "apscheduler.schedulers.background",
        "apscheduler.triggers.cron",
        "typer",
        "rich",
        "click",
        "main",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hooks/playwright_path.py"],
    excludes=[
        "fastapi",
        "uvicorn",
        "jinja2",
        "python_multipart",
        "pytest",
        "numpy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SEACE-Buscador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no terminal window — pure GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets\\icon.ico" if (PROJECT / "assets" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SEACE-Buscador",
)
