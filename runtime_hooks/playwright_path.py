"""
Runtime hook — executed by PyInstaller before any app code runs.
Points Playwright to the Chromium binary bundled inside the installer.
"""
import os
import sys

if getattr(sys, "frozen", False):
    # In a COLLECT build the data files sit next to the .exe
    app_dir = os.path.dirname(sys.executable)
    browsers_path = os.path.join(app_dir, "playwright_browsers")
    if os.path.isdir(browsers_path):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
