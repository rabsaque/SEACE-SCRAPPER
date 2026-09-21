"""
SQLAlchemy ORM models.

Single table `leads` holds everything the scraper discovers.
A second table `run_log` records each scraper execution for auditing.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lead(Base):
    """One government procurement opportunity."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Scraper metadata ──────────────────────────────────────────────────────
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    # ── SEACE data ────────────────────────────────────────────────────────────
    entity: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    nomenclature: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    object_type: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    ficha_url: Mapped[str] = mapped_column(Text, default="")

    # ── Document ──────────────────────────────────────────────────────────────
    pdf_local_path: Mapped[str] = mapped_column(Text, default="")
    pdf_page_count: Mapped[int] = mapped_column(Integer, default=0)
    tech_specs_text: Mapped[str] = mapped_column(Text, default="")

    # ── AI filter ─────────────────────────────────────────────────────────────
    match_score: Mapped[int] = mapped_column(Integer, default=0)
    match_level: Mapped[str] = mapped_column(String(16), default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    key_requirements_json: Mapped[str] = mapped_column(Text, default="[]")
    disqualifiers_json: Mapped[str] = mapped_column(Text, default="[]")

    # ── Cronograma (schedule extracted from ficha page) ───────────────────────
    cronograma_json: Mapped[str] = mapped_column(Text, default="[]")

    # ── Review status (set by employee via dashboard) ─────────────────────────
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    bid_decision: Mapped[str] = mapped_column(
        String(16), default=""
    )  # "BID" | "SKIP" | "PENDING"

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def key_requirements(self) -> list[str]:
        try:
            return json.loads(self.key_requirements_json)
        except Exception:
            return []

    @key_requirements.setter
    def key_requirements(self, value: list[str]) -> None:
        self.key_requirements_json = json.dumps(value, ensure_ascii=False)

    @property
    def disqualifiers(self) -> list[str]:
        try:
            return json.loads(self.disqualifiers_json)
        except Exception:
            return []

    @disqualifiers.setter
    def disqualifiers(self, value: list[str]) -> None:
        self.disqualifiers_json = json.dumps(value, ensure_ascii=False)

    @property
    def cronograma(self) -> list[dict]:
        try:
            return json.loads(self.cronograma_json)
        except Exception:
            return []

    @cronograma.setter
    def cronograma(self, value: list[dict]) -> None:
        self.cronograma_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "run_id": self.run_id,
            "user_id": self.user_id,
            "entity": self.entity,
            "nomenclature": self.nomenclature,
            "object_type": self.object_type,
            "description": self.description,
            "ficha_url": self.ficha_url,
            "pdf_local_path": self.pdf_local_path,
            "pdf_page_count": self.pdf_page_count,
            "tech_specs_text": self.tech_specs_text,
            "match_score": self.match_score,
            "match_level": self.match_level,
            "ai_summary": self.ai_summary,
            "key_requirements": self.key_requirements,
            "disqualifiers": self.disqualifiers,
            "reviewed": self.reviewed,
            "review_notes": self.review_notes,
            "bid_decision": self.bid_decision,
            "cronograma": self.cronograma,
        }


class User(Base):
    """Dashboard user account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class UserSession(Base):
    """Active login session."""

    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AppSettings(Base):
    """
    Simple key-value store for runtime configuration.
    Values are always stored as JSON strings so they can hold any type
    (strings, lists, numbers).

    Keys used by the scraper:
      "keywords"        → JSON array of strings
      "spec_start_page" → integer (default 20)
      "spec_end_page"   → integer (default 30)
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ScrapeJob(Base):
    """One scraping session requested via the PHP dashboard."""

    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | running | done | error | stopped

    # Job configuration (serialised)
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    date_from: Mapped[str] = mapped_column(String(20), default="")  # DD/MM/YYYY
    date_to: Mapped[str] = mapped_column(String(20), default="")    # DD/MM/YYYY
    search_query: Mapped[str] = mapped_column(Text, default="")
    download_pdf: Mapped[bool] = mapped_column(Boolean, default=True)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    max_pages: Mapped[int] = mapped_column(Integer, default=0)

    # Runtime
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_scanned: Mapped[int] = mapped_column(Integer, default=0)
    matches_found: Mapped[int] = mapped_column(Integer, default=0)
    leads_saved: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_msg: Mapped[str] = mapped_column(Text, default="")

    @property
    def keywords(self) -> list[str]:
        try:
            return json.loads(self.keywords_json)
        except Exception:
            return []

    @keywords.setter
    def keywords(self, value: list[str]) -> None:
        self.keywords_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "keywords": self.keywords,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "search_query": self.search_query,
            "download_pdf": self.download_pdf,
            "use_ai": self.use_ai,
            "max_pages": self.max_pages,
            "pid": self.pid,
            "rows_scanned": self.rows_scanned,
            "matches_found": self.matches_found,
            "leads_saved": self.leads_saved,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_msg": self.error_msg,
        }


class JobLog(Base):
    """Real-time log messages written by a worker process."""

    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "level": self.level,
            "message": self.message,
        }


class ScheduledScan(Base):
    """A recurring scrape job configured by the user."""

    __tablename__ = "scheduled_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    # Scraper settings
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    use_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    download_pdf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    date_from: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    date_to: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Schedule
    frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")  # daily | weekly
    time_of_day: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")  # HH:MM
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0=Mon…6=Sun
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Notification
    notify_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notify_emails_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Runtime tracking
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def keywords(self) -> list[str]:
        try:
            return json.loads(self.keywords_json)
        except Exception:
            return []

    @keywords.setter
    def keywords(self, value: list[str]) -> None:
        self.keywords_json = json.dumps(value, ensure_ascii=False)

    @property
    def notify_keywords(self) -> list[str]:
        try:
            return json.loads(self.notify_keywords_json)
        except Exception:
            return []

    @notify_keywords.setter
    def notify_keywords(self, value: list[str]) -> None:
        self.notify_keywords_json = json.dumps(value, ensure_ascii=False)

    @property
    def notify_emails(self) -> list[str]:
        try:
            return json.loads(self.notify_emails_json)
        except Exception:
            return []

    @notify_emails.setter
    def notify_emails(self, value: list[str]) -> None:
        self.notify_emails_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "keywords": self.keywords,
            "use_ai": self.use_ai,
            "download_pdf": self.download_pdf,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "max_pages": self.max_pages,
            "frequency": self.frequency,
            "time_of_day": self.time_of_day,
            "day_of_week": self.day_of_week,
            "enabled": self.enabled,
            "notify_keywords": self.notify_keywords,
            "notify_emails": self.notify_emails,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
        }


class RunLog(Base):
    """Audit log — one row per scraper execution."""

    __tablename__ = "run_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rows_scanned: Mapped[int] = mapped_column(Integer, default=0)
    keyword_matches: Mapped[int] = mapped_column(Integer, default=0)
    leads_saved: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|done|error
    error_message: Mapped[str] = mapped_column(Text, default="")
