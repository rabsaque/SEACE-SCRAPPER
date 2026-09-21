"""
PDF download handler for SEACE.

The site uses `javascript:descargaDocGeneral(...)` which internally submits a
hidden form or makes a POST request.  Playwright's download-event interception
captures it regardless of how the response is triggered.

Two strategies are attempted in order:
  1. Evaluate the JS href directly in the page context (triggers the download).
  2. Fall back to clicking the anchor element so Playwright intercepts natively.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from loguru import logger
from playwright.async_api import Page, TimeoutError as PWTimeout

from src.config import settings


def _safe_filename(name: str, fallback: str = "document.pdf") -> str:
    """Convert a raw string into a safe filesystem filename."""
    if not name:
        return fallback
    # Normalise unicode → ASCII-safe
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    # Replace path-unsafe chars
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = name.strip(". ")
    return name or fallback


class PDFDownloader:
    """Downloads the Base/Invitation PDF from a ficha detail page."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.download_dir = settings.download_dir

    async def download(self, pdf_trigger_js: str, filename_hint: str) -> Path | None:
        """
        Trigger the PDF download and save it to *download_dir*.

        Returns the local Path on success, None on failure.
        """
        if not pdf_trigger_js:
            logger.warning("No PDF trigger JS available — skipping download.")
            return None

        safe_name = _safe_filename(filename_hint)
        dest = self.download_dir / safe_name

        # If already downloaded (re-run scenario) skip
        if dest.exists() and dest.stat().st_size > 0:
            logger.info("PDF already exists, reusing: {}", dest)
            return dest

        logger.info("Downloading PDF → {}", safe_name)

        # ── Strategy 1: evaluate the JS href inside the page ─────────────────
        try:
            async with self.page.expect_download(timeout=60_000) as dl_info:
                # Strip the leading "javascript:" if present
                js_to_run = pdf_trigger_js.removeprefix("javascript:")
                await self.page.evaluate(js_to_run)

            download = await dl_info.value
            suggested = download.suggested_filename
            if suggested:
                dest = self.download_dir / _safe_filename(suggested, safe_name)
            await download.save_as(str(dest))
            logger.success("PDF saved: {}", dest)
            return dest

        except PWTimeout:
            logger.warning("Strategy 1 timed out — trying click-based fallback.")
        except Exception as exc:
            logger.warning("Strategy 1 failed ({}), trying fallback.", exc)

        # ── Strategy 2: click the anchor element ─────────────────────────────
        try:
            # SEACE puts descargaDocGeneral in onclick, not href
            anchor = self.page.locator(
                'a[onclick*="descargaDocGeneral"]:has(img[src*="pdf.png"]), '
                'a[onclick*="descargaDocGeneral"], '
                'a[href*="descargaDocGeneral"]'
            ).first

            async with self.page.expect_download(timeout=60_000) as dl_info:
                await anchor.click()

            download = await dl_info.value
            suggested = download.suggested_filename
            if suggested:
                dest = self.download_dir / _safe_filename(suggested, safe_name)
            await download.save_as(str(dest))
            logger.success("PDF saved (fallback): {}", dest)
            return dest

        except Exception as exc:
            logger.error("PDF download failed completely: {}", exc)
            return None

    async def find_and_download_all(self) -> list[Path]:
        """
        Convenience method: discover ALL PDF download links on the current page
        and download each one.  Returns a list of saved paths.
        """
        hrefs: list[str] = await self.page.evaluate(
            r"""() => {
                return Array.from(
                    document.querySelectorAll('a[href*="descargaDocGeneral"]')
                ).map(a => a.getAttribute('href') || '');
            }"""
        )

        saved: list[Path] = []
        for href in hrefs:
            m = re.search(r"'([^']*\.pdf)'", href, re.IGNORECASE)
            hint = m.group(1) if m else ""
            path = await self.download(href, hint)
            if path:
                saved.append(path)

        return saved
