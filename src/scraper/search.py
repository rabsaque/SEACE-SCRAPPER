"""
Search execution and row-level scraping on the SEACE buscadorPublico page.

Real page structure (verified 2026-07-09 via diagnose.py)
──────────────────────────────────────────────────────────
URL  : buscadorPublico.xhtml
Tab  : a[href="#tbBuscador:tab1"]  → panel id="tbBuscador:tab1"
       Panel hides via CSS class "ui-helper-hidden" (not inline style).
       Clicking the tab anchor via JS does NOT reliably toggle the class,
       but clicking the Buscar *button* via JS still fires the AJAX search.

Buscar button id : tbBuscador:idFormBuscarProceso:btnBuscarSel
Results table id  : tbBuscador:idFormBuscarProceso:dtProcesos
  (matched with partial selector [id*="dtProcesos"])

Confirmed column layout (0-based):
  0  N°
  1  Nombre o Sigla de la Entidad        ← COL_ENTITY
  2  Fecha y Hora de Publicacion
  3  Nomenclatura                         ← COL_NOMENCLATURE
  4  Reiniciado Desde                     ← COL_RESTARTED
  5  Objeto de Contratación               ← COL_OBJ_TYPE
  6  Descripción de Objeto                ← COL_DESCRIPTION
  7  Código SNIP
  8  Código Único de Inversión
  9  VR / VE / Cuantía
 10  Moneda
 11  Versión SEACE
 12  Acciones (ficha / historial icons)   ← COL_ACTIONS
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from playwright.async_api import Page, TimeoutError as PWTimeout

from src.config import settings

# ── Column indices (0-based, verified against live site) ──────────────────────
COL_ENTITY       = 1
COL_PUB_DATE     = 2   # "Fecha y Hora de Publicacion" e.g. "22/09/2026 19:54"
COL_NOMENCLATURE = 3
COL_RESTARTED    = 4
COL_OBJ_TYPE     = 5
COL_DESCRIPTION  = 6
COL_ACTIONS      = 12   # contains ficha/historial icon anchors


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RawRow:
    entity: str = ""
    nomenclature: str = ""
    restarted_from: str = ""
    object_type: str = ""
    description: str = ""
    pub_date: str = ""               # "Fecha y Hora de Publicacion" from col 2
    row_index: int = 0
    page_num: int = 0                # which search-results page this row came from
    ficha_anchor_onclick: str = ""   # raw onclick attr for the ficha icon
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def keyword_blob(self) -> str:
        return " ".join(
            [self.entity, self.nomenclature, self.object_type, self.description]
        ).lower()


def _get_max_pages() -> int:
    """Read max_pages from DB at runtime (0 = unlimited)."""
    try:
        from src.storage.repository import get_setting
        val = get_setting("max_pages")
        if isinstance(val, int):
            return val
    except Exception:
        pass
    return settings.max_pages  # fallback to config/env


def _get_keywords() -> list[str]:
    """
    Load keywords at runtime — DB value takes priority over .env / config.
    Falls back to settings.keywords if the DB hasn't been seeded yet.
    """
    try:
        from src.storage.repository import get_setting
        kws = get_setting("keywords")
        if kws and isinstance(kws, list):
            return [k.lower() for k in kws]
    except Exception:
        pass
    return [k.lower() for k in settings.keywords]


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics so 'informatica' matches 'informática'."""
    return (
        unicodedata.normalize("NFD", text.lower())
        .encode("ascii", "ignore")
        .decode()
    )


def _matches_keywords(row: RawRow) -> bool:
    blob = _normalize(row.keyword_blob)
    return any(_normalize(kw) in blob for kw in _get_keywords())


# ── Main search class ─────────────────────────────────────────────────────────

class SEACESearch:

    def __init__(self, page: Page) -> None:
        self.page = page
        self.rows_scanned: int = 0        # total rows visited across all pages
        self.search_query: str = ""       # optional SEACE-side description filter
        self.date_from: str = ""          # "DD/MM/YYYY" – fecha publicación desde
        self.date_to: str = ""            # "DD/MM/YYYY" – fecha publicación hasta
        self.keywords: list[str] | None = None   # override DB keywords when set
        self.max_pages: int | None = None        # override DB max_pages when set

    def _row_matches(self, row: "RawRow") -> bool:
        """Check keyword match — uses self.keywords if set, else reads from DB."""
        if self.keywords is not None:
            blob = _normalize(row.keyword_blob)
            return any(_normalize(kw) in blob for kw in self.keywords)
        return _matches_keywords(row)

    def _date_in_range(self, pub_date: str) -> bool:
        """
        Return True if pub_date (e.g. '22/09/2026 19:54') falls within
        self.date_from … self.date_to.  If either bound is unset, that side
        is open.  Parsing failures are treated as in-range (don't discard).
        """
        if not pub_date or (not self.date_from and not self.date_to):
            return True
        try:
            # pub_date from SEACE: "DD/MM/YYYY HH:MM" or "DD/MM/YYYY"
            dt = datetime.strptime(pub_date.strip()[:10], "%d/%m/%Y")
            if self.date_from:
                df = datetime.strptime(self.date_from.strip()[:10], "%d/%m/%Y")
                if dt < df:
                    return False
            if self.date_to:
                dt2 = datetime.strptime(self.date_to.strip()[:10], "%d/%m/%Y")
                if dt > dt2:
                    return False
            return True
        except ValueError:
            return True  # unparseable → don't discard

    # ── Navigation ────────────────────────────────────────────────────────────

    async def goto_search(self) -> None:
        logger.info("Navigating to SEACE buscadorPublico…")
        await self.page.goto(settings.base_url, wait_until="networkidle")
        logger.debug("Page loaded: {}", self.page.url)

    async def open_search_tab(self) -> None:
        """
        Switch to the 'Buscador de Procedimientos de Selección' tab.

        PrimeFaces hides inactive panels with the CSS class 'ui-helper-hidden'
        (display:none via stylesheet).  A native Playwright click on the <a>
        fails because the element is considered not-visible while within a
        scrollable container off-screen.  We dispatch the click via JS instead,
        which triggers PrimeFaces' jQuery tab handler.
        """
        logger.debug("Switching to Procedimientos tab…")
        await self.page.evaluate(
            "() => document.querySelector('a[href=\"#tbBuscador:tab1\"]')?.click()"
        )
        await self.page.wait_for_timeout(1500)

    async def execute_search(self) -> None:
        """
        Optionally fill the 'Descripción del Objeto' field, then click Buscar.

        If *self.search_query* is set the text is injected into the SEACE input
        before every search so Phase 2 re-searches preserve the same filter.

        We do NOT pass expected_page=1 here — when SEACE returns only one page
        of results the paginator renders no page-number links and the condition
        would never be satisfied.  Plain row-existence check is enough.
        """
        import json as _json
        if self.search_query:
            q = _json.dumps(self.search_query)
            await self.page.evaluate(
                f"""() => {{
                    const inp = document.getElementById(
                        'tbBuscador:idFormBuscarProceso:descripcionObjeto'
                    );
                    if (!inp) return;
                    inp.value = {q};
                    inp.dispatchEvent(new Event('input',  {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}"""
            )
            await self.page.wait_for_timeout(300)
            logger.info("Descripcion del Objeto set to: {}", self.search_query)

        if self.date_from or self.date_to:
            # SEACE date fields: calendar inputs for "Fecha Publicación Desde/Hasta"
            # Strategy: find inputs by partial ID pattern or by nearby label text.
            date_js = _json.dumps({"from": self.date_from, "to": self.date_to})
            await self.page.evaluate(
                f"""() => {{
                    const vals = {date_js};

                    function fillDate(id, value) {{
                        if (!value) return;
                        // Try exact ID first, then partial match
                        let inp = document.getElementById(id);
                        if (!inp) {{
                            const all = document.querySelectorAll('input[id*="' + id + '"]');
                            inp = all.length ? all[0] : null;
                        }}
                        if (!inp) return;
                        inp.value = value;
                        inp.dispatchEvent(new Event('input',  {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur',   {{bubbles: true}}));
                    }}

                    // Common SEACE date field IDs (try both patterns)
                    fillDate('tbBuscador:idFormBuscarProceso:CalFechaPublicacionDesde_input', vals.from);
                    fillDate('tbBuscador:idFormBuscarProceso:CalFechaPublicacionHasta_input', vals.to);
                    // Alternative IDs seen on some SEACE versions
                    fillDate('tbBuscador:idFormBuscarProceso:fechaPublicacionDesde_input', vals.from);
                    fillDate('tbBuscador:idFormBuscarProceso:fechaPublicacionHasta_input', vals.to);
                }}"""
            )
            await self.page.wait_for_timeout(400)
            logger.info("Date range set: {} → {}", self.date_from or "any", self.date_to or "any")

        logger.info("Executing Buscar…")
        await self.page.evaluate(
            "() => document.getElementById("
            "'tbBuscador:idFormBuscarProceso:btnBuscarSel')?.click()"
        )
        await self._wait_for_table()   # just wait for rows — no page-number assertion

    # ── Table helpers ─────────────────────────────────────────────────────────

    async def _wait_for_table(
        self,
        expected_page: int | None = None,
        page_timeout_ms: int | None = None,
    ) -> None:
        """
        Wait for the results table to be ready.

        If *expected_page* is given, block until the paginator shows that page
        number — this prevents scraping stale rows while PrimeFaces AJAX is
        mid-flight after a "Next" click.

        *page_timeout_ms* overrides settings.nav_timeout_ms for the page-number
        check only.  Pass a short value (e.g. 15_000) in contexts where failure
        is expected to be common (e.g. after go_back()) so the caller can quickly
        fall through to a recovery path.
        """
        logger.debug("Waiting for results table (expected_page={})…", expected_page)

        # 1. Wait for any PrimeFaces loading overlay/spinner to disappear first
        try:
            await self.page.wait_for_selector(
                '.ui-datatable-loading, .ui-blockui',
                state="hidden", timeout=10_000,
            )
        except PWTimeout:
            pass  # no spinner — fine

        # 2. If we know which page we should land on, wait for it explicitly.
        #    Accept two conditions:
        #      a) The paginator shows an active link with the expected number, OR
        #      b) expected_page == 1 AND rows exist but no page links are rendered
        #         (single-page result — PrimeFaces omits page-number links).
        if expected_page is not None:
            timeout = page_timeout_ms if page_timeout_ms is not None else settings.nav_timeout_ms
            try:
                await self.page.wait_for_function(
                    f"""() => {{
                        const rows = document.querySelectorAll(
                            '[id*="dtProcesos"] tbody tr[data-ri]'
                        );
                        if (!rows.length) return false;

                        const pag = document.querySelector(
                            '[id*="dtProcesos_paginator"], [id*="dtProcesos"] .ui-paginator'
                        );
                        if (!pag) return {expected_page} === 1;  // no paginator = single page

                        const active = pag.querySelector('.ui-paginator-page.ui-state-active');
                        if (!active) return {expected_page} === 1; // no page links = single page

                        return parseInt(active.textContent.trim(), 10) === {expected_page};
                    }}""",
                    timeout=timeout,
                )
                logger.debug("Paginator confirmed page {}.", expected_page)
            except PWTimeout:
                logger.warning(
                    "Timeout waiting for paginator to show page {}. "
                    "Proceeding anyway — rows may be stale.",
                    expected_page,
                )

        # 3. Ensure at least one row is present
        try:
            await self.page.wait_for_function(
                "() => document.querySelectorAll('[id*=\"dtProcesos\"] tbody tr[data-ri]').length > 0",
                timeout=settings.nav_timeout_ms,
            )
        except PWTimeout:
            logger.warning("Timed out waiting for result rows — proceeding anyway.")

        await self.page.wait_for_timeout(300)  # brief settle
        logger.debug("Results table ready.")

    async def _get_paginator_info(self) -> dict:
        """
        Read paginator state via JS — returns current page, total pages,
        total records, and whether the Next button is disabled.
        """
        try:
            return await self.page.evaluate(
                r"""() => {
                    // PrimeFaces paginator text: "(1 - 15 of 375)" or "Mostrando 1-15 de 375"
                    const pag = document.querySelector(
                        '[id*="dtProcesos_paginator"], [id*="dtProcesos"] .ui-paginator'
                    );
                    if (!pag) return { found: false };

                    const nextBtn = pag.querySelector('.ui-paginator-next');
                    const curText = (pag.querySelector('.ui-paginator-current') || {}).textContent || '';

                    // Extract total count from "(X - Y of Z)" or "de Z"
                    const m = curText.match(/(?:of|de)\s+([\d,]+)/i);
                    const total = m ? parseInt(m[1].replace(/,/g,''), 10) : null;

                    // Current page = number of active page link
                    const activePage = pag.querySelector('.ui-paginator-page.ui-state-active');
                    const curPage = activePage ? parseInt(activePage.textContent.trim(), 10) : null;

                    // Total pages = last page link number
                    const pages = pag.querySelectorAll('.ui-paginator-page');
                    const lastPage = pages.length
                        ? parseInt(pages[pages.length-1].textContent.trim(), 10)
                        : null;

                    const nextDisabled = nextBtn
                        ? nextBtn.classList.contains('ui-state-disabled')
                        : true;

                    return {
                        found:        true,
                        curPage:      curPage,
                        lastPage:     lastPage,
                        total:        total,
                        curText:      curText.trim(),
                        nextDisabled: nextDisabled,
                    };
                }"""
            )
        except Exception as exc:
            logger.debug("Could not read paginator info: {}", exc)
            return {"found": False}

    async def _go_to_next_page(self) -> bool:
        """
        Click the paginator Next button.  Returns False on the last page.

        Strategy:
          1. Read paginator state via JS to get current/last page numbers and
             whether the Next button is disabled — this is more reliable than
             relying on a Playwright locator that may time out on hidden elements.
          2. If Next is available, evaluate a JS click (never fails due to
             CSS visibility issues the way Playwright native clicks can).
          3. Wait for the table to re-render.
        """
        info = await self._get_paginator_info()

        if not info.get("found"):
            logger.debug("Paginator not found in DOM — assuming last page.")
            return False

        logger.debug(
            "Paginator: page {}/{} | total={} | {}",
            info.get("curPage"), info.get("lastPage"),
            info.get("total"), info.get("curText"),
        )

        if info.get("nextDisabled", True):
            logger.info(
                "Last page reached (page {}/{}, {} total records).",
                info.get("curPage"), info.get("lastPage"), info.get("total"),
            )
            return False

        cur_page   = info.get("curPage")  or 0
        next_page  = cur_page + 1

        # Click Next via JS — immune to CSS visibility / overlay issues
        try:
            clicked = await self.page.evaluate(
                r"""() => {
                    const pag = document.querySelector(
                        '[id*="dtProcesos_paginator"], [id*="dtProcesos"] .ui-paginator'
                    );
                    if (!pag) return 'no_pag';
                    const btn = pag.querySelector('.ui-paginator-next');
                    if (!btn) return 'no_btn';
                    if (btn.classList.contains('ui-state-disabled')) return 'disabled';
                    btn.click();
                    return 'clicked';
                }"""
            )
            if clicked != "clicked":
                logger.info("Paginator Next not clickable ({}). Last page.", clicked)
                return False
        except Exception as exc:
            logger.warning("JS paginator click failed: {}", exc)
            return False

        # Wait until the paginator confirms the new page number — prevents
        # reading stale rows while PrimeFaces AJAX is still in flight.
        await self._wait_for_table(expected_page=next_page)
        return True

    async def _go_to_first_page(self) -> None:
        """Click the paginator First button to reset to page 1."""
        await self.page.evaluate(
            r"""() => {
                const pag = document.querySelector(
                    '[id*="dtProcesos_paginator"], [id*="dtProcesos"] .ui-paginator'
                );
                if (!pag) return;
                const btn = pag.querySelector('.ui-paginator-first');
                if (btn && !btn.classList.contains('ui-state-disabled')) btn.click();
            }"""
        )
        await self._wait_for_table(expected_page=1)

    async def navigate_to_page(self, target: int) -> None:
        """
        Jump to *target* (1-based) on the current search results.

        The SEACE server-side JSF session remembers the last paginator position,
        so after a full re-navigation + re-search the table may come back at an
        arbitrary page rather than page 1.  We therefore:

        1. Read the current page from the paginator.
        2. If already there, return immediately.
        3. Try clicking the page-number link directly (paginator window may show it).
        4. If the current page is *past* the target, reset to page 1 first via
           the First button, then step forward.
        5. Step forward using Next clicks as needed.
        """
        if target <= 1:
            # Ensure we're on page 1 (server might have restored a different page)
            info = await self._get_paginator_info()
            if (info.get("curPage") or 1) != 1:
                logger.debug("Currently on page {} — resetting to page 1.", info.get("curPage"))
                await self._go_to_first_page()
            return

        # Read where we are now
        info = await self._get_paginator_info()
        cur_page = info.get("curPage") or 1
        logger.debug("navigate_to_page: target={} current={}", target, cur_page)

        if cur_page == target:
            return  # already there

        # Try clicking the page-number link directly (fastest path)
        clicked = await self.page.evaluate(
            f"""() => {{
                const pags = document.querySelectorAll(
                    '[id*="dtProcesos"] .ui-paginator-page, '
                    + '[id*="dtProcesos_paginator"] .ui-paginator-page'
                );
                for (const p of pags) {{
                    if (parseInt(p.textContent.trim()) === {target}) {{
                        p.click();
                        return true;
                    }}
                }}
                return false;
            }}"""
        )
        if clicked:
            await self._wait_for_table(expected_page=target)
            return

        # If we're currently past the target, reset to page 1 first
        if cur_page > target:
            logger.debug(
                "Currently on page {} which is past target {} — resetting to page 1 first.",
                cur_page, target,
            )
            await self._go_to_first_page()
            cur_page = 1

        # Step forward from cur_page to target
        steps = target - cur_page
        logger.debug("Stepping forward {} page(s) via Next…", steps)
        for _ in range(steps):
            if not await self._go_to_next_page():
                break

    # ── Row scraping ──────────────────────────────────────────────────────────

    async def _scrape_current_page(self) -> list[RawRow]:
        rows_data: list[dict] = await self.page.evaluate(
            f"""() => {{
                const rows = document.querySelectorAll('[id*="dtProcesos"] tbody tr[data-ri]');
                return Array.from(rows).map((tr, idx) => {{
                    const cells = tr.querySelectorAll('td');
                    const g = (i) => cells[i]?.innerText?.trim() || '';
                    // Collect ALL anchor onclicks in the actions cell
                    const actionCell = cells[{COL_ACTIONS}];
                    const anchors = actionCell
                        ? Array.from(actionCell.querySelectorAll('a[onclick]'))
                              .map(a => ({{
                                  onclick: a.getAttribute('onclick') || '',
                                  imgSrc:  a.querySelector('img')?.src?.split('/').pop() || '',
                              }}))
                        : [];
                    return {{
                        ri:          tr.getAttribute('data-ri'),
                        idx:         idx,
                        entity:      g({COL_ENTITY}),
                        pub_date:    g({COL_PUB_DATE}),
                        nomenclature:g({COL_NOMENCLATURE}),
                        restarted:   g({COL_RESTARTED}),
                        obj_type:    g({COL_OBJ_TYPE}),
                        description: g({COL_DESCRIPTION}),
                        anchors:     anchors,
                    }};
                }});
            }}"""
        )

        results: list[RawRow] = []
        for d in rows_data:
            # Pick the ficha anchor: prefer fichaSeleccion.gif, fall back to first onclick
            ficha_onclick = ""
            for a in d.get("anchors", []):
                if "fichaSeleccion" in a["imgSrc"]:
                    ficha_onclick = a["onclick"]
                    break
            if not ficha_onclick and d.get("anchors"):
                ficha_onclick = d["anchors"][0]["onclick"]

            results.append(RawRow(
                entity=d["entity"],
                pub_date=d.get("pub_date", ""),
                nomenclature=d["nomenclature"],
                restarted_from=d["restarted"],
                object_type=d["obj_type"],
                description=d["description"],
                row_index=d["idx"],
                ficha_anchor_onclick=ficha_onclick,
            ))

        logger.debug("Scraped {} rows from current page.", len(results))
        return results

    # ── Public API ────────────────────────────────────────────────────────────

    async def iter_matching_rows(self, accept_all: bool = False):
        """
        Async generator — yields RawRow objects that pass the keyword filter,
        paginating automatically through all result pages.

        When *accept_all* is True (e.g. a SEACE-side search_query is active)
        every row is yielded without local keyword filtering.
        """
        page_num = 0

        # Log total result count before we start iterating
        info = await self._get_paginator_info()
        if info.get("found") and info.get("total"):
            max_p = settings.max_pages or info.get("lastPage") or "?"
            logger.info(
                "Search returned ~{} total records across {} page(s). "
                "Max pages cap: {}.",
                info["total"], info.get("lastPage", "?"),
                settings.max_pages or "none (all pages)",
            )

        max_pages = (
            self.max_pages if self.max_pages is not None else _get_max_pages()
        )

        while True:
            page_num += 1
            if max_pages and page_num > max_pages:
                logger.info(
                    "Límite de {} página(s) alcanzado — deteniendo. "
                    "Ajusta el límite en Configuración → Paginación para escanear más.",
                    max_pages,
                )
                break

            rows = await self._scrape_current_page()
            logger.info(
                "Page {} of {}: {} rows — scanning for keywords…",
                page_num, info.get("lastPage", "?"), len(rows),
            )

            for row in rows:
                self.rows_scanned += 1
                row.page_num = page_num   # stamp page number on every row

                # Local date filter — backup for when SEACE ignores form dates
                if not self._date_in_range(row.pub_date):
                    logger.debug(
                        "Skipping (out of date range): {} — {}",
                        row.pub_date, row.nomenclature
                    )
                    continue

                if accept_all or self._row_matches(row):
                    logger.success(
                        "MATCH [p{}/r{}] {} | {} | pub:{}",
                        page_num, row.row_index,
                        row.nomenclature,
                        row.description[:60],
                        row.pub_date,
                    )
                    yield row
                else:
                    logger.debug("no match: {}", row.description[:50])

            has_next = await self._go_to_next_page()
            if not has_next:
                break
