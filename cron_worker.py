"""
cron_worker.py  –  Cron-based job runner for SEACE scraper.

Configure once in cPanel → Cron Jobs:
  * * * * *  /home5/zkcbvnvr/virtualenv/seace-scraper/3.11/bin/python \
             /home5/zkcbvnvr/seace-scraper/cron_worker.py >> \
             /home5/zkcbvnvr/seace-scraper/logs/cron.log 2>&1

This script runs every minute, claims one pending job from the DB, and
runs the worker in the same process.  A lock file prevents overlapping
runs when a job takes longer than one minute.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
LOCK_FILE = os.path.join(BASE_DIR, "logs", "cron_worker.pid")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _claim_pending_job() -> int | None:
    """Atomically claim one pending job; return job_id or None."""
    db_path = os.getenv("DB_PATH", os.path.join(BASE_DIR, "seace_leads.db"))

    con = sqlite3.connect(db_path, timeout=10)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT id FROM scrape_jobs WHERE status='pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            con.rollback()
            return None
        job_id = row[0]
        # Pre-mark as running so another cron instance won't claim it.
        # worker._run() will overwrite this with the actual PID shortly after.
        con.execute(
            "UPDATE scrape_jobs SET status='running' WHERE id=?", (job_id,)
        )
        con.commit()
        return job_id
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


def main() -> None:
    # ── Lock check ────────────────────────────────────────────────────────────
    if os.path.exists(LOCK_FILE):
        try:
            old_pid = int(open(LOCK_FILE).read().strip())
            if _pid_alive(old_pid):
                print(f"[cron_worker] Previous instance pid={old_pid} still running. Exiting.")
                return
        except Exception:
            pass  # stale or corrupt lock file — proceed

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        job_id = _claim_pending_job()
        if job_id is None:
            print("[cron_worker] No pending jobs.")
            return

        print(f"[cron_worker] Claimed job_id={job_id}. Running worker...")
        from worker import _run  # noqa: E402
        asyncio.run(_run(job_id))
        print(f"[cron_worker] job_id={job_id} finished.")

    except Exception as exc:
        import traceback
        print(f"[cron_worker] FATAL: {exc}", file=sys.stderr)
        traceback.print_exc()

    finally:
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass


if __name__ == "__main__":
    main()
