"""
Navigate to the "Ficha de Selección" detail page for a matched row and
extract document metadata (entity, title, PDF download trigger info).

The ficha link submits a PrimeFaces form via its onclick JS handler.
We re-use the onclick string captured during the search-results scrape
(stored in RawRow.ficha_anchor_onclick) and evaluate it directly in the
page context — this is more reliable than trying to re-locate and click
a potentially stale DOM element.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from loguru import logger
from playwright.async_api import Page, TimeoutError as PWTimeout

from src.config import settings
from src.scraper.search import RawRow


@dataclass
class FichaDetail:
    """Metadata extracted from the detail (ficha) page."""
    entity: str
    nomenclature: str
    description: str
    object_type: str
    ficha_url: str           # URL of the detail page after navigation
    pdf_trigger_js: str      # The JS snippet that triggers the PDF download
    pdf_filename_hint: str   # Filename hint parsed from the JS call
    cronograma: list[dict] = field(default_factory=list)  # schedule rows


class FichaNavigator:
    """Opens a ficha detail page and extracts metadata + PDF trigger."""

    def __init__(self, page: Page) -> None:
        self.page = page

    async def open_ficha(self, row: RawRow, row_locator=None) -> FichaDetail | None:
        """
        Navigate to the ficha detail page for *row*.

        Strategy A (preferred): evaluate row.ficha_anchor_onclick directly —
          this is the onclick JS captured during search scraping. It submits
          the PrimeFaces form and triggers a full-page navigation.

        Strategy B (fallback): locate and click the ficha anchor inside
          row_locator if the onclick string is empty.

        Returns None if navigation fails.
        """
        onclick = (row.ficha_anchor_onclick or "").strip()
        logger.debug("Opening ficha for {} (onclick len={})", row.nomenclature, len(onclick))

        # ── Extract permanent SEACE process identifiers from the onclick JS ──
        # nidProceso / nidConvocatoria are stable DB keys.
        # The ?id=UUID we get AFTER navigation is a server-side session ref that
        # expires when the Playwright session ends, so we must NOT use it as a
        # permanent link.
        import re as _re
        _seace: dict[str, str] = {}
        for _k in ("ntipo", "nidConvocatoria", "nidProceso", "nidSistema"):
            _m = _re.search(rf"'{_re.escape(_k)}'\s*:\s*'([^']*)'", onclick)
            if _m:
                _seace[_k] = _m.group(1)
        if _seace.get("nidProceso"):
            logger.debug("Extracted SEACE params: nidProceso={} nidSistema={}",
                         _seace["nidProceso"], _seace.get("nidSistema"))

        try:
            async with self.page.expect_navigation(
                wait_until="networkidle",
                timeout=settings.nav_timeout_ms,
            ):
                if onclick:
                    # Strip leading "javascript:" if present, then evaluate
                    js = onclick.lstrip()
                    if js.lower().startswith("javascript:"):
                        js = js[len("javascript:"):]
                    await self.page.evaluate(f"() => {{ {js} }}")
                elif row_locator is not None:
                    # Fallback: try clicking the ficha anchor in the row
                    anchor = row_locator.locator(
                        'a:has(img[src*="fichaSeleccion"]), '
                        'a[onclick*="addSubmitParam"]:has(img)'
                    ).first
                    await anchor.click()
                else:
                    logger.warning("No onclick JS and no row_locator — cannot open ficha.")
                    return None

        except PWTimeout:
            logger.warning("Timeout navigating to ficha for row {}.", row.row_index)
            return None
        except Exception as exc:
            logger.error("Error opening ficha: {}", exc)
            return None

        _landed_url = self.page.url
        logger.info("Landed on ficha: {}", _landed_url)

        # ── Build the stored ficha URL using permanent SEACE identifiers ──────
        # Preferred: encode nidProceso + nidConvocatoria (extracted from onclick).
        # These are permanent DB keys; the desktop app replays the POST via
        # Playwright to open the page correctly.
        # Fallback: keep the UUID URL but add ptoRetorno=LOCAL which SEACE
        # requires to render the ficha in standalone mode.
        _base_url = "https://prod2.seace.gob.pe/seacebus-uiwd-pub/fichaSeleccion/fichaSeleccion.xhtml"
        if _seace.get("nidProceso"):
            # Store only the permanent identifiers.
            # nidConvocatoria is session-specific and changes every search —
            # the desktop app fetches a fresh one at open-time via Playwright.
            ficha_url = (
                f"{_base_url}"
                f"?nidProceso={_seace['nidProceso']}"
                f"&nidSistema={_seace.get('nidSistema', '3')}"
                f"&ntipo={_seace.get('ntipo', '1')}"
                f"&ptoRetorno=LOCAL"
            )
            logger.info("Stored permanent ficha URL (nidProceso={}): {}",
                        _seace["nidProceso"], ficha_url)
        else:
            # Fallback: UUID URL — add ptoRetorno=LOCAL
            _parsed = urllib.parse.urlparse(_landed_url)
            _params  = dict(urllib.parse.parse_qsl(_parsed.query))
            _params["ptoRetorno"] = "LOCAL"
            ficha_url = _parsed._replace(query=urllib.parse.urlencode(_params)).geturl()
            logger.info("Stored ficha URL (UUID fallback): {}", ficha_url)

        # ── Verify we actually landed on the ficha page ───────────────────────
        # If the server didn't recognise the form submission (e.g. view state
        # expired, table was still loading, row index out of range) it re-renders
        # the search page.  Detect this early instead of waiting 60 s for the
        # documents table that will never appear.
        if "fichaSeleccion" not in _landed_url:
            logger.warning(
                "Ficha navigation did not reach fichaSeleccion — landed on {} instead. "
                "The search results were probably still loading when the form was submitted. "
                "Returning None so Phase 2 recovery logic can retry.",
                _landed_url,
            )
            return None

        # Wait for the documents table specifically so PDF links are present.
        try:
            await self.page.wait_for_selector(
                '[id*="dtDocumentos"] tbody tr, '
                '[id*="pnlContenedorGral"]',
                state="visible",
                timeout=settings.timeout_ms,
            )
            # Extra settle for AJAX-loaded document rows
            await self.page.wait_for_timeout(1_000)
        except PWTimeout:
            logger.warning("Documents table not found on {}, proceeding anyway.", ficha_url)

        pdf_trigger_js, pdf_filename_hint = await self._extract_pdf_trigger()
        cronograma = await self._extract_cronograma()

        if not pdf_trigger_js:
            logger.warning("No PDF trigger found on ficha {}.", ficha_url)
        else:
            logger.info("PDF trigger extracted: {!r}", pdf_filename_hint)

        if cronograma:
            logger.info("Cronograma: {} stages extracted.", len(cronograma))
        else:
            logger.debug("No cronograma found on ficha.")

        return FichaDetail(
            entity=row.entity,
            nomenclature=row.nomenclature,
            description=row.description,
            object_type=row.object_type,
            ficha_url=ficha_url,
            pdf_trigger_js=pdf_trigger_js,
            pdf_filename_hint=pdf_filename_hint,
            cronograma=cronograma,
        )

    async def _extract_pdf_trigger(self) -> tuple[str, str]:
        """
        Find the PDF download link inside a gridcell.

        SEACE renders the link as:
            <a href="#" onclick="javascript:descargaDocGeneral('UUID','3','BASES.pdf');;...">

        The call is in onclick, NOT href.  We search onclick first,
        then fall back to the legacy href-based format.
        """
        try:
            js_data: dict = await self.page.evaluate(
                r"""() => {
                    // Primary: SEACE puts descargaDocGeneral in onclick, href="#"
                    let links = document.querySelectorAll(
                        'td[role="gridcell"] a[onclick*="descargaDocGeneral"], ' +
                        'a[onclick*="descargaDocGeneral"]'
                    );
                    if (links.length > 0) {
                        for (const a of links) {
                            const onclick = a.getAttribute('onclick') || '';
                            const m = onclick.match(/descargaDocGeneral\([^)]+\)/);
                            if (m) return { src: 'onclick', val: 'javascript:' + m[0] };
                        }
                    }
                    // Fallback: legacy href-based format
                    links = document.querySelectorAll('a[href*="descargaDocGeneral"]');
                    if (links.length > 0) {
                        return { src: 'href', val: links[0].getAttribute('href') || '' };
                    }
                    return { src: 'none', val: '' };
                }"""
            )
        except Exception as exc:
            logger.warning("Could not extract PDF trigger JS: {}", exc)
            return "", ""

        js_href = js_data.get("val", "")
        logger.debug(
            "PDF trigger source={!r}  val={!r}",
            js_data.get("src"), js_href[:80],
        )

        filename_hint = ""
        m = re.search(r"'([^']*\.pdf)'", js_href, re.IGNORECASE)
        if m:
            filename_hint = m.group(1)

        return js_href, filename_hint

    async def _extract_cronograma(self) -> list[dict]:
        """
        Extract the procurement schedule (cronograma) from the ficha page.

        SEACE renders a PrimeFaces DataTable whose ID contains 'ronograma'
        (matches both 'Cronograma' and 'cronograma').  Each row is a
        procurement stage with start/end date and time columns.

        Returns a list of dicts like:
            {"Etapa": "Convocatoria", "Fecha Inicio": "01/08/2026", ...}
        """
        try:
            data: list[dict] = await self.page.evaluate(
                r"""() => {
                    // Strategy 1: table inside an element whose ID contains 'ronograma'
                    let wrapper = document.querySelector('[id*="ronograma"]');
                    let table = wrapper ? wrapper.querySelector('table') : null;

                    // Strategy 2: look for a panel whose title mentions 'cronograma'
                    if (!table) {
                        for (const panel of document.querySelectorAll('.ui-panel,.ui-fieldset')) {
                            const title = (panel.querySelector(
                                '.ui-panel-title,.ui-fieldset-legend'
                            ) || {}).textContent || '';
                            if (title.toLowerCase().includes('cronograma')) {
                                table = panel.querySelector('table');
                                break;
                            }
                        }
                    }

                    if (!table) return [];

                    // Extract column headers
                    const ths  = table.querySelectorAll('thead th');
                    const hdrs = Array.from(ths).map(th => th.innerText.trim()).filter(Boolean);
                    if (!hdrs.length) return [];

                    // Extract data rows
                    const result = [];
                    for (const tr of table.querySelectorAll('tbody tr')) {
                        const cells = tr.querySelectorAll('td');
                        const row   = {};
                        cells.forEach((td, i) => {
                            const key = hdrs[i] || `col${i}`;
                            row[key]  = td.innerText.trim();
                        });
                        // Skip empty rows (e.g. PrimeFaces empty-message row)
                        const vals = Object.values(row).join('').trim();
                        if (vals) result.push(row);
                    }
                    return result;
                }"""
            )
            return data or []
        except Exception as exc:
            logger.warning("Could not extract cronograma: {}", exc)
            return []

    async def go_back(self) -> None:
        """Navigate back to the search results listing."""
        await self.page.go_back(wait_until="networkidle", timeout=settings.nav_timeout_ms)
        try:
            await self.page.wait_for_selector(
                '[id*="dtProcesos"]',
                state="visible",
                timeout=settings.timeout_ms,
            )
        except PWTimeout:
            logger.warning("Results table not visible after go_back.")
