"""
Scheduler service for SEACE Buscador.

Manages recurring scrape jobs using APScheduler. Runs as a background thread
while the desktop application is open. When a scheduled scan fires it:
  1. Calls run_pipeline() with the schedule's settings.
  2. Filters the newly saved leads against the schedule's notification keywords.
  3. Sends an email alert if matches are found and SMTP is configured.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from datetime import datetime

from loguru import logger


_DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class SchedulerService:
    """Wraps APScheduler and drives scheduled SEACE scans."""

    def __init__(self, msg_queue: queue.Queue) -> None:
        self._msg_queue = msg_queue
        self._scheduler = None
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the APScheduler background scheduler and register all enabled jobs."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler(timezone="America/Lima")
            self._scheduler.start()
            self._register_all()
            logger.info("SchedulerService started.")
        except ImportError:
            self._log("WARNING",
                "APScheduler no está instalado. Las búsquedas programadas no funcionarán. "
                "Ejecuta: pip install apscheduler")
        except Exception as exc:
            logger.error("SchedulerService failed to start: {}", exc)

    def stop(self) -> None:
        """Shut down the scheduler cleanly."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("SchedulerService stopped.")

    def reload(self) -> None:
        """Re-read all schedules from DB and re-register jobs (call after any DB change)."""
        if self._scheduler is None:
            return
        with self._lock:
            self._scheduler.remove_all_jobs()
            self._register_all()
        self._log("INFO", "Programaciones actualizadas.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _register_all(self) -> None:
        """Load all enabled ScheduledScan rows and register them as APScheduler jobs."""
        try:
            from src.storage.repository import list_scheduled_scans, init_db
            init_db()
            scans = list_scheduled_scans(enabled_only=True)
            for scan in scans:
                self._register(scan)
            logger.info("Registered {} scheduled scan(s).", len(scans))
        except Exception as exc:
            logger.error("Could not register schedules: {}", exc)

    def _register(self, scan) -> None:
        """Register a single ScheduledScan as a cron job."""
        try:
            from apscheduler.triggers.cron import CronTrigger
            h, m = scan.time_of_day.split(":")
            if scan.frequency == "weekly":
                trigger = CronTrigger(
                    day_of_week=scan.day_of_week, hour=int(h), minute=int(m)
                )
            else:  # daily
                trigger = CronTrigger(hour=int(h), minute=int(m))

            self._scheduler.add_job(
                func=self._execute_scan,
                trigger=trigger,
                args=[scan.id],
                id=f"scan_{scan.id}",
                name=scan.name,
                replace_existing=True,
                misfire_grace_time=None,  # skip missed fires instead of queuing
            )
            logger.info(
                "Scheduled '{}' — {} at {}{}",
                scan.name,
                scan.frequency,
                scan.time_of_day,
                f" ({_DAY_NAMES[scan.day_of_week]})" if scan.frequency == "weekly" else "",
            )
        except Exception as exc:
            logger.error("Failed to register scan id={}: {}", scan.id, exc)

    def _execute_scan(self, scan_id: int) -> None:
        """Job function called by APScheduler in a background thread."""
        from src.storage import repository as repo

        scan = repo.get_scheduled_scan(scan_id)
        if scan is None:
            return

        # Guard: skip if another scrape is already running
        # (We detect this by checking if any APScheduler job with id "running_scan" exists,
        #  or simply by catching the asyncio run exception from a busy browser.)
        self._log("INFO",
            f"Iniciando búsqueda programada: \"{scan.name}\" "
            f"({scan.frequency}, {scan.time_of_day})")

        try:
            from main import run_pipeline  # local import to avoid circular deps
            from datetime import timedelta

            # Combine search keywords + alert keywords so the scan finds
            # everything relevant (alert keywords also trigger email notifications)
            all_keywords = list(dict.fromkeys(
                [k for k in (scan.keywords + scan.notify_keywords) if k.strip()]
            ))

            # Always search the last 30 days to today — this ensures recent
            # open procedures are always included regardless of date settings
            date_from = (datetime.utcnow() - timedelta(days=30)).strftime("%d/%m/%Y")
            date_to = datetime.utcnow().strftime("%d/%m/%Y")

            result = asyncio.run(run_pipeline(
                verbose=False,
                use_ai=scan.use_ai,
                download_pdf=scan.download_pdf,
                keywords=all_keywords,
                date_from=date_from,
                date_to=date_to,
                max_pages=scan.max_pages if scan.max_pages > 0 else None,
                user_id=0,
                job_id=0,
            ))

            leads_saved = result.get("leads_saved", 0)
            run_id = result.get("run_id", "")
            self._log("SUCCESS",
                f"Búsqueda programada \"{scan.name}\" completada — "
                f"{leads_saved} lead(s) guardado(s).")

            # Update runtime tracking
            repo.update_scheduled_scan(scan_id, last_run_at=datetime.utcnow())

            # ── Notification check ────────────────────────────────────────────
            if scan.notify_keywords and scan.notify_emails and run_id:
                self._send_notifications(scan, run_id)

        except Exception as exc:
            self._log("ERROR",
                f"Error en búsqueda programada \"{scan.name}\": {exc}")
            logger.exception("Scheduled scan id={} failed: {}", scan_id, exc)

    def _send_notifications(self, scan, run_id: str) -> None:
        """Check new leads against notification keywords and send email if matched."""
        try:
            from src.storage.repository import get_leads_by_run_id
            from src.notifications.email_sender import send_lead_alert

            leads = get_leads_by_run_id(run_id)
            notify_kws = [k.upper() for k in scan.notify_keywords if k.strip()]

            matched = []
            for lead in leads:
                haystack = (
                    (lead.description or "") + " " + (lead.entity or "")
                ).upper()
                if any(kw in haystack for kw in notify_kws):
                    matched.append(lead.to_dict())

            if not matched:
                self._log("INFO",
                    f"Sin coincidencias de alerta en \"{scan.name}\" — "
                    "no se enviará correo.")
                return

            send_lead_alert(
                leads=matched,
                schedule_name=scan.name,
                recipients=scan.notify_emails,
            )
            self._log("SUCCESS",
                f"Correo de alerta enviado: {len(matched)} licitación(es) "
                f"a {', '.join(scan.notify_emails)}.")

        except Exception as exc:
            self._log("ERROR", f"Error al enviar correo de alerta: {exc}")

    def _log(self, level: str, message: str) -> None:
        """Push a log entry to the GUI's message queue."""
        try:
            self._msg_queue.put_nowait(("log", level, message))
        except Exception:
            pass
