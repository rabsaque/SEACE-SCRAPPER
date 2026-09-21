"""
Diagnostic phase 4 — networkidle load, correct CSS class name ui-helper-h.
"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://prod2.seace.gob.pe/seacebus-uiwd-pub/buscadorPublico/buscadorPublico.xhtml"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(
            locale="es-PE",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page.set_default_timeout(90_000)
        page.set_default_navigation_timeout(90_000)

        print("Navigating (networkidle)…")
        await page.goto(URL, wait_until="networkidle")
        print("Page loaded.")

        # Dump tab1 panel classes BEFORE click
        cls_before = await page.evaluate(
            "() => document.getElementById('tbBuscador:tab1')?.className || 'NOT FOUND'"
        )
        print(f"tab1 panel class BEFORE click: {cls_before}")

        # Try a real Playwright click on the tab anchor
        print("Clicking tab…")
        tab_link = page.locator('a[href="#tbBuscador\\:tab1"]')
        n = await tab_link.count()
        print(f"Tab link count: {n}")
        if n > 0:
            await tab_link.first.click(force=True)
        else:
            print("Tab link not found! Trying text selector…")
            await page.locator('text=Buscador de Procedimientos de Selección').first.click(force=True)

        await page.wait_for_timeout(3000)

        cls_after = await page.evaluate(
            "() => document.getElementById('tbBuscador:tab1')?.className || 'NOT FOUND'"
        )
        print(f"tab1 panel class AFTER click:  {cls_after}")

        # Check Buscar button visibility
        btn_info = await page.evaluate("""
            () => {
                const b = document.getElementById('tbBuscador:idFormBuscarProceso:btnBuscarSel');
                if (!b) return 'BUTTON NOT FOUND';
                const rect = b.getBoundingClientRect();
                const cs = window.getComputedStyle(b);
                return {
                    display:    cs.display,
                    visibility: cs.visibility,
                    opacity:    cs.opacity,
                    top: rect.top, left: rect.left,
                    width: rect.width, height: rect.height,
                    inViewport: rect.top >= 0 && rect.top < window.innerHeight,
                };
            }
        """)
        print(f"Buscar button info: {btn_info}")

        # Try clicking via JavaScript directly
        print("Clicking Buscar via JS evaluate…")
        await page.evaluate(
            "() => document.getElementById('tbBuscador:idFormBuscarProceso:btnBuscarSel')?.click()"
        )
        await page.wait_for_timeout(10000)

        # Check for results
        row_count = await page.evaluate("""
            () => document.querySelectorAll('[id*="dtProcesos"] tbody tr[data-ri]').length
        """)
        print(f"\nResult rows found: {row_count}")

        if row_count > 0:
            print("\n── Table headers ───────────────────────────────────")
            headers = await page.evaluate("""
                () => Array.from(document.querySelectorAll('[id*="dtProcesos"] thead th'))
                           .map((th, i) => ({ index: i, text: th.innerText.trim() }))
            """)
            for h in headers:
                print(h)

            print("\n── First 2 rows ────────────────────────────────────")
            rows = await page.evaluate("""
                () => Array.from(document.querySelectorAll('[id*="dtProcesos"] tbody tr[data-ri]'))
                           .slice(0,2)
                           .map(tr => ({
                               ri: tr.getAttribute('data-ri'),
                               cells: Array.from(tr.querySelectorAll('td')).map((td,i) => ({
                                   idx: i,
                                   text: td.innerText.trim().substring(0,55),
                                   imgSrc: (td.querySelector('img')?.src||'').split('/').pop(),
                                   onclick: (td.querySelector('a[onclick]')?.getAttribute('onclick')||'').substring(0,80),
                               }))
                           }))
            """)
            for r in rows:
                print(f"\n  Row ri={r['ri']}:")
                for c in r['cells']:
                    print(f"    [{c['idx']}] {c['text']!r:50} img={c['imgSrc']:20} onclick={c['onclick'][:50]}")

        print("\n── Screenshot → diagnose2.png ──────────────────────────")
        await page.screenshot(path="diagnose2.png", full_page=False)
        await browser.close()
        print("Done.")

asyncio.run(main())
