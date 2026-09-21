"""
Runtime hook — executed by PyInstaller before any app code runs.
Points Playwright to the Chromium binary bundled inside the installer.

In PyInstaller 6.x COLLECT builds the data files live in _internal/
which is where sys._MEIPASS points — NOT next to the .exe.
"""
import os
import sys

if getattr(sys, "frozen", False):
    # sys._MEIPASS = <install_dir>\_internal\  (PyInstaller 6.x COLLECT build)
    internal_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    browsers_path = os.path.join(internal_dir, "playwright_browsers")
    if os.path.isdir(browsers_path):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
