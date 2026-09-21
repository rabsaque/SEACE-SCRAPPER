"""
SEACE Scraper Worker
────────────────────
Runs a single scrape job identified by its DB id.  Launched by the PHP
dashboard via exec/shell_exec:

    nohup /path/to/.venv/bin/python /path/to/worker.py JOB_ID >> log 2>&1 &

Progress is written to the `job_logs` table in real time so the PHP UI can
poll for live updates.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python worker.py <job_id>", file=sys.stderr)
        sys.exit(1)

    try:
        job_id = int(sys.argv[1])
    except ValueError:
        print(f"Invalid job_id: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)

    # Change to the directory this file lives in so relative imports work
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    asyncio.run(_run(job_id))


async def _run(job_id: int) -> None:
    from loguru import logger

    from src.storage.repository import (
        add_job_log,
        get_scrape_job,
        init_db,
        update_scrape_job,
    )

    init_db()

    job = get_scrape_job(job_id)
    if job is None:
        print(f"Job {job_id} not found in DB.", file=sys.stderr)
        sys.exit(1)

    # ── Loguru setup ─────────────────────────────────────────────────────────
    # 1. Remove default handler
    logger.remove()
    # 2. Console output (for the nohup log file)
    logger.add(sys.stderr, level="DEBUG",
                format="{time:HH:mm:ss} | {level:<8} | {message}")
    # 3. Log-file for this job
    log_path = f"logs/worker_{job_id}.log"
    os.makedirs("logs", exist_ok=True)
    logger.add(log_path, level="DEBUG", rotation=None, encoding="utf-8")
    # 4. DB sink — writes to job_logs table so PHP can poll in real time
    def _db_sink(message):  # noqa: E306
        rec = message.record
        try:
            add_job_log(job_id, rec["level"].name, rec["message"])
        except Exception:
            pass  # never crash the scraper because of a logging failure
    logger.add(_db_sink, level="INFO")

    # ── Mark job as running ───────────────────────────────────────────────────
    update_scrape_job(
        job_id,
        status="running",
        pid=os.getpid(),
        started_at=datetime.utcnow(),
    )

    logger.info("Worker started for job_id={} pid={}", job_id, os.getpid())

    # ── Re-read job config (fresh after status update) ────────────────────────
    job = get_scrape_job(job_id)
    keywords   = job.keywords          # list[str]
    date_from  = job.date_from         # "DD/MM/YYYY" or ""
    date_to    = job.date_to           # "DD/MM/YYYY" or ""
    search_q   = job.search_query
    dl_pdf     = job.download_pdf
    use_ai     = job.use_ai
    max_pgs    = job.max_pages or None  # 0 → None (unlimited)
    user_id    = job.user_id

    # ── Run the pipeline ──────────────────────────────────────────────────────
    try:
        from main import run_pipeline  # noqa: E402

        result = await run_pipeline(
            verbose=False,
            use_ai=use_ai,
            download_pdf=dl_pdf,
            search_query=search_q,
            user_id=user_id,
            keywords=keywords,
            date_from=date_from,
            date_to=date_to,
            max_pages=max_pgs,
            job_id=job_id,
        )

        update_scrape_job(
            job_id,
            status="done",
            rows_scanned=result.get("rows_scanned", 0),
            matches_found=result.get("keyword_matches", 0),
            leads_saved=result.get("leads_saved", 0),
            completed_at=datetime.utcnow(),
            error_msg="",
        )
        logger.info(
            "Job {} done — scanned={} matches={} saved={}",
            job_id,
            result.get("rows_scanned", 0),
            result.get("keyword_matches", 0),
            result.get("leads_saved", 0),
        )

    except Exception as exc:
        import traceback
        err = traceback.format_exc()
        logger.error("Job {} failed: {}", job_id, err)
        update_scrape_job(
            job_id,
            status="error",
            completed_at=datetime.utcnow(),
            error_msg=str(exc)[:2000],
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
