"""
SEACE Scraper — main entry point.

Usage
─────
  # Minimal run — keyword scrape only, no PDF download, no AI
  python main.py scrape --no-pdf --no-ai

  # Download PDFs but skip AI scoring
  python main.py scrape --no-ai

  # Full pipeline (PDF + AI scoring) — requires ANTHROPIC_API_KEY in .env
  python main.py scrape

  # Launch the review dashboard
  python main.py dashboard

  # Export leads to Excel
  python main.py export --min-score 0 --out leads.xlsx

  # Show recent run history
  python main.py runs
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

app_cli = typer.Typer(help="SEACE government contracts scraper.")
console = Console()


# ── Logging ───────────────────────────────────────────────────────────────────

def _configure_logging(verbose: bool = False) -> None:
    import sys
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr, level=level, colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )
    logger.add(
        "logs/seace_{time:YYYY-MM-DD}.log",
        level="DEBUG", rotation="00:00", retention="14 days", encoding="utf-8",
    )


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_pipeline(
    verbose: bool = False,
    use_ai: bool = False,
    download_pdf: bool = True,
    search_query: str = "",
    user_id: int = 0,
    keywords: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    max_pages: int | None = None,
    job_id: int = 0,
) -> dict:
    """
    Full async scraping pipeline.

    Modes
    ─────
    --no-pdf --no-ai   Fast mode: keyword scan + save metadata only.
                       Runs in minutes, no external APIs, no disk writes.

    --no-ai            Download PDFs, extract text, save — no scoring.
                       Good for building a local corpus.

    (default)          Full pipeline: PDF + Claude AI scoring.
                       Requires ANTHROPIC_API_KEY in .env.
    """
    _configure_logging(verbose)

    from src.config import settings
    from src.scraper.browser import managed_browser
    from src.scraper.search import SEACESearch
    from src.scraper.detail import FichaNavigator
    from src.scraper.downloader import PDFDownloader
    from src.parser.pdf_parser import parse_pdf
    from src.ai.filter import analyse_lead
    from src.storage import repository as repo
    from src.storage.models import Lead

    repo.init_db()
    run_id = str(uuid.uuid4())
    repo.create_run(run_id, user_id=user_id)

    rows_scanned   = 0
    keyword_matches = 0
    leads_saved    = 0

    mode_label = (
        "keyword-only (no PDF, no AI)"  if (not download_pdf and not use_ai)
        else "PDF + no AI"              if (download_pdf and not use_ai)
        else "full (PDF + AI)"
    )

    from src.storage.repository import get_user_setting
    # Direct params override user settings (used by worker.py per-job config)
    live_keywords  = keywords  if keywords  is not None else (
        get_user_setting(user_id, "keywords") or settings.keywords
    )
    live_date_from = date_from if date_from else (get_user_setting(user_id, "date_from") or "")
    live_date_to   = date_to   if date_to   else (get_user_setting(user_id, "date_to")   or "")

    logger.info("═" * 60)
    logger.info("SEACE scraper run  id={}  mode={}  user_id={}", run_id, mode_label, user_id)
    logger.info("Keywords : {}", live_keywords)
    if live_date_from or live_date_to:
        logger.info("Date range: {} → {}", live_date_from or "any", live_date_to or "any")
    if search_query:
        logger.info("SEACE query: \"{}\"  (keyword filter bypassed)", search_query)
    logger.info("═" * 60)

    try:
        async with managed_browser() as browser:
            page = await browser.new_page()
            search = SEACESearch(page)

            # ── Step A: Navigate & search ─────────────────────────────────────
            if search_query:
                search.search_query = search_query
            if live_date_from:
                search.date_from = live_date_from
            if live_date_to:
                search.date_to = live_date_to
            if live_keywords is not None:
                search.keywords = live_keywords
            if max_pages is not None:
                search.max_pages = max_pages
            await search.goto_search()
            await search.open_search_tab()
            await search.execute_search()

            navigator = FichaNavigator(page)
            downloader = PDFDownloader(page)

            # ══════════════════════════════════════════════════════════════════
            # PHASE 1 — Keyword scan (stay on search results — no navigation)
            #
            # Collect ALL matching rows across all pages first so the browser
            # never leaves the search-results page during pagination.
            # This fixes the bug where go_back() after a ficha visit would
            # reset the PrimeFaces table state and lose subsequent pages.
            # ══════════════════════════════════════════════════════════════════
            all_matches: list = []
            async for raw_row in search.iter_matching_rows(accept_all=bool(search_query)):
                all_matches.append(raw_row)
                keyword_matches += 1

            rows_scanned = search.rows_scanned
            logger.info(
                "Phase 1 complete — scanned {} rows, {} keyword match(es).",
                rows_scanned, keyword_matches,
            )

            # ── Keyword-only mode: save leads directly (no ficha needed) ──────
            if not download_pdf:
                for raw_row in all_matches:
                    lead = Lead(
                        run_id=run_id, user_id=user_id, job_id=job_id,
                        entity=raw_row.entity,
                        nomenclature=raw_row.nomenclature,
                        object_type=raw_row.object_type,
                        description=raw_row.description,
                        ficha_url="", pdf_local_path="",
                        pdf_page_count=0, tech_specs_text="",
                        match_score=0, match_level="SKIPPED", ai_summary="",
                    )
                    lead.key_requirements = []
                    lead.disqualifiers    = []
                    lead.cronograma       = []
                    repo.save_lead(lead)
                    leads_saved += 1
                    logger.info(
                        "Lead #{} saved  entity={}  nomenclature={}",
                        leads_saved, raw_row.entity[:40], raw_row.nomenclature,
                    )

            elif all_matches:
                # ══════════════════════════════════════════════════════════════
                # PHASE 2 — Ficha + PDF processing
                #
                # Re-navigate to the search page once, then visit each ficha
                # grouped by page number (forward only, no backward navigation
                # between pages).  After each ficha we go_back() to the SAME
                # results page, so the next match on that page is still live.
                # ══════════════════════════════════════════════════════════════
                from collections import defaultdict
                matches_by_page: dict[int, list] = defaultdict(list)
                for rr in all_matches:
                    matches_by_page[rr.page_num].append(rr)

                logger.info(
                    "Phase 2 — {} match(es) on {} page(s). Re-navigating to SEACE…",
                    keyword_matches, len(matches_by_page),
                )
                # ── Re-navigate with retry ──────────────────────────────
                # Verify rows appear before processing fichas. Retries once.
                async def _do_search_with_retry() -> bool:
                    for attempt in range(1, 3):
                        await search.goto_search()
                        await search.open_search_tab()
                        await search.execute_search()
                        has_rows = await page.evaluate(
                            "() => document.querySelectorAll("
                            "'[id*=\"dtProcesos\"] tbody tr[data-ri]').length > 0"
                        )
                        if has_rows:
                            # SEACE's JSF session may restore a non-page-1 position
                            # after AJAX search; reset to page 1 so navigate_to_page
                            # can step forward from a known baseline.
                            await search.navigate_to_page(1)
                            logger.info(
                                "Search ready for Phase 2 (attempt {}).", attempt
                            )
                            return True
                        logger.warning(
                            "Phase 2 search attempt {} returned no rows — retrying…",
                            attempt,
                        )
                    return False

                async def _restore_to_page(target: int) -> None:
                    """After a failed ficha, re-execute search and jump to page."""
                    ok = await _do_search_with_retry()
                    if ok and target > 1:
                        await search.navigate_to_page(target)

                search_ok = await _do_search_with_retry()
                if not search_ok:
                    logger.error(
                        "Phase 2 search failed — saving {} matches as keyword-only.",
                        len(all_matches),
                    )
                    for rr in all_matches:
                        _kw_lead = Lead(
                            run_id=run_id, user_id=user_id, job_id=job_id, entity=rr.entity,
                            nomenclature=rr.nomenclature,
                            object_type=rr.object_type,
                            description=rr.description,
                            ficha_url="", pdf_local_path="",
                            pdf_page_count=0, tech_specs_text="",
                            match_score=0, match_level="SKIPPED", ai_summary="",
                        )
                        _kw_lead.key_requirements = []
                        _kw_lead.disqualifiers    = []
                        _kw_lead.cronograma       = []
                        repo.save_lead(_kw_lead)
                        leads_saved += 1
                else:
                    current_page = 1
                    for target_page in sorted(matches_by_page.keys()):
                        if target_page != current_page:
                            logger.info("Jumping to page {}…", target_page)
                            await search.navigate_to_page(target_page)
                            current_page = target_page

                        for raw_row in matches_by_page[target_page]:
                            ficha_url  = ""
                            pdf_path   = None
                            tech_specs = ""
                            page_count = 0
                            cronograma = []

                            # ── Step C: Open ficha detail ──────────────────
                            ficha = await navigator.open_ficha(raw_row)
                            if ficha is None:
                                # open_ficha returns None when we stay on the
                                # search page (wrong URL). Don't go_back — just
                                # re-execute the search and jump to target page.
                                logger.warning(
                                    "Ficha failed row {} p{}. Re-navigating…",
                                    raw_row.row_index, target_page,
                                )
                                await _restore_to_page(target_page)
                                continue

                            ficha_url  = ficha.ficha_url
                            cronograma = ficha.cronograma

                            # ── Step D: Download & parse PDF ──────────────
                            pdf_path = await downloader.download(
                                ficha.pdf_trigger_js, ficha.pdf_filename_hint
                            )
                            if pdf_path:
                                parsed = parse_pdf(
                                    pdf_path,
                                    spec_start_page=int(get_user_setting(user_id, "spec_start_page") or 20),
                                    spec_end_page=int(get_user_setting(user_id, "spec_end_page") or 30),
                                )
                                if parsed:
                                    tech_specs = parsed.tech_specs
                                    page_count = parsed.page_count

                            # Return to search results for next match on same page.
                            # Use a short page-verification timeout (15 s) because
                            # browser go_back() in PrimeFaces often restores page 1
                            # rather than the original page; if so, we quickly fall
                            # through to _restore_to_page instead of waiting 90 s.
                            try:
                                await page.go_back(
                                    wait_until="networkidle",
                                    timeout=settings.nav_timeout_ms,
                                )
                                await search._wait_for_table(
                                    expected_page=target_page,
                                    page_timeout_ms=15_000,
                                )
                            except Exception:
                                logger.warning(
                                    "go_back after ficha/PDF did not restore page {} "
                                    "— re-navigating.",
                                    target_page,
                                )
                                await _restore_to_page(target_page)

                            # ── Step E: AI scoring (optional) ──────────────────
                            ai_score   = 0
                            ai_level   = "SKIPPED"
                            ai_summary = ""
                            key_reqs   = []
                            disqs      = []

                            if use_ai:
                                result = analyse_lead(
                                    tech_specs=tech_specs,
                                    entity=raw_row.entity,
                                    description=raw_row.description,
                                    skip=False,
                                )
                                ai_score   = result.match_score
                                ai_level   = result.match_level
                                ai_summary = result.summary
                                key_reqs   = result.key_requirements
                                disqs      = result.disqualifiers

                            # ── Step F: Persist ────────────────────────────────
                            lead = Lead(
                                run_id=run_id, user_id=user_id, job_id=job_id,
                                entity=raw_row.entity,
                                nomenclature=raw_row.nomenclature,
                                object_type=raw_row.object_type,
                                description=raw_row.description,
                                ficha_url=ficha_url,
                                pdf_local_path=str(pdf_path) if pdf_path else "",
                                pdf_page_count=page_count,
                                tech_specs_text=tech_specs,
                                match_score=ai_score,
                                match_level=ai_level,
                                ai_summary=ai_summary,
                            )
                            lead.key_requirements = key_reqs
                            lead.disqualifiers    = disqs
                            lead.cronograma       = cronograma
                            repo.save_lead(lead)
                            leads_saved += 1
                            logger.info(
                                "Lead #{} saved  entity={}  nomenclature={}",
                                leads_saved, raw_row.entity[:40], raw_row.nomenclature,
                            )

        rows_scanned = search.rows_scanned   # final count after loop ends
        repo.finish_run(
            run_id,
            rows_scanned=rows_scanned,
            keyword_matches=keyword_matches,
            leads_saved=leads_saved,
            status="done",
        )
        logger.success(
            "Run complete — scanned={} matches={} saved={}",
            rows_scanned, keyword_matches, leads_saved,
        )

    except Exception as exc:
        logger.exception("Pipeline failed: {}", exc)
        repo.finish_run(
            run_id,
            rows_scanned=rows_scanned,
            keyword_matches=keyword_matches,
            leads_saved=leads_saved,
            status="error",
            error_message=str(exc),
        )
        raise

    return {
        "run_id": run_id,
        "rows_scanned": rows_scanned,
        "keyword_matches": keyword_matches,
        "leads_saved": leads_saved,
    }


# ── CLI Commands ──────────────────────────────────────────────────────────────

@app_cli.command()
def scrape(
    no_ai: bool  = typer.Option(False, "--no-ai",  help="Skip Claude AI scoring entirely."),
    no_pdf: bool = typer.Option(False, "--no-pdf", help="Skip PDF download & parsing."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
    search_query: str = typer.Option("", "--search-query", "-q",
                                     help="Text to type in SEACE 'Descripcion del Objeto' field."),
    user_id: int = typer.Option(0, "--user-id", help="Dashboard user ID (set by dashboard)."),
) -> None:
    """
    Scrape SEACE, apply keyword filter, optionally download PDFs and AI-score results.

    \b
    Recommended starting point (fast, free, no API key needed):
        python main.py scrape --no-pdf --no-ai

    Add PDF parsing when you want to inspect document contents:
        python main.py scrape --no-ai

    Full pipeline once you have an Anthropic API key:
        python main.py scrape
    """
    if no_pdf and not no_ai:
        # Can't score with AI if there's no text to score
        console.print(
            "[yellow]Note: --no-pdf implies no tech specs text, so AI scoring "
            "will produce empty results. Forcing --no-ai.[/yellow]"
        )
        no_ai = True

    summary = asyncio.run(
        run_pipeline(
            verbose=verbose,
            use_ai=not no_ai,
            download_pdf=not no_pdf,
            search_query=search_query.strip(),
            user_id=user_id,
        )
    )

    console.print("\n[bold green]Run complete![/bold green]")
    console.print(f"  Run ID          : {summary['run_id']}")
    console.print(f"  Rows scanned    : {summary['rows_scanned']}")
    console.print(f"  Keyword matches : {summary['keyword_matches']}")
    console.print(f"  Leads saved     : {summary['leads_saved']}")
    console.print(
        "\nReview results: [bold]python main.py dashboard[/bold]  "
        "or  [bold]python main.py export[/bold]\n"
    )


@app_cli.command()
def dashboard(
    host: str = typer.Option("0.0.0.0", help="Host to bind"),
    port: int = typer.Option(8000, help="Port"),
) -> None:
    """Start the FastAPI review dashboard (http://localhost:8000)."""
    _configure_logging()
    import uvicorn
    from src.storage.repository import init_db
    from src.dashboard.app import app as fastapi_app

    init_db()
    console.print(f"\n[bold cyan]Dashboard → http://localhost:{port}[/bold cyan]\n")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@app_cli.command()
def export(
    out: Path = typer.Option(
        Path(f"seace_leads_{datetime.now().strftime('%Y%m%d')}.xlsx"),
        help="Output .xlsx path",
    ),
    min_score: int = typer.Option(0, help="Only include leads with score >= this value"),
) -> None:
    """Export all leads to a colour-coded Excel spreadsheet."""
    _configure_logging()
    from src.storage.repository import export_to_excel, init_db

    init_db()
    path = export_to_excel(str(out), min_score=min_score)
    console.print(f"[green]Exported → {path}[/green]")


@app_cli.command()
def runs() -> None:
    """Print the last 20 scraper run logs."""
    _configure_logging()
    from src.storage.repository import get_recent_runs, init_db

    init_db()
    logs = get_recent_runs(20)
    if not logs:
        console.print("[yellow]No runs recorded yet.[/yellow]")
        return

    table = Table(title="Recent Scraper Runs", show_lines=True)
    table.add_column("Run ID",   style="dim", width=12)
    table.add_column("Started",  width=18)
    table.add_column("Status",   width=9)
    table.add_column("Scanned",  justify="right")
    table.add_column("Matches",  justify="right")
    table.add_column("Saved",    justify="right")

    for r in logs:
        style = {"done": "green", "error": "red", "running": "yellow"}.get(r.status, "")
        table.add_row(
            r.run_id[:8] + "…",
            r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "—",
            f"[{style}]{r.status}[/{style}]",
            str(r.rows_scanned),
            str(r.keyword_matches),
            str(r.leads_saved),
        )
    console.print(table)


if __name__ == "__main__":
    app_cli()
