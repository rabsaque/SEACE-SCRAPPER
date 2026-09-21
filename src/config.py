"""Central configuration — loaded once at import time."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool = True) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


def _list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(key, "")
    if raw:
        return [k.strip() for k in raw.split(",") if k.strip()]
    return default or []


@dataclass
class Config:
    # ── Target site ───────────────────────────────────────────────────────────
    # The public search/listing page (NOT the ficha detail page)
    base_url: str = (
        "https://prod2.seace.gob.pe/seacebus-uiwd-pub/buscadorPublico/buscadorPublico.xhtml"
    )

    # ── Scraper ───────────────────────────────────────────────────────────────
    headless: bool = field(default_factory=lambda: _bool("HEADLESS", True))
    max_pages: int = field(default_factory=lambda: int(os.getenv("MAX_PAGES", "0")))
    timeout_ms: int = 60_000          # element-wait timeout
    nav_timeout_ms: int = 90_000      # page navigation / network idle timeout
    retry_attempts: int = 3

    # Keywords for the fast row-level filter (before sending to AI)
    keywords: list[str] = field(
        default_factory=lambda: _list(
            "KEYWORDS",
            [
                "limpieza",
                "seguridad",
                "mantenimiento",
                "servicios generales",
                "vigilancia",
                "fumigacion",
                "jardineria",
            ],
        )
    )

    # ── Storage ───────────────────────────────────────────────────────────────
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "seace_leads.db"))
    download_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DOWNLOAD_DIR", "downloads"))
    )

    # ── AI provider ───────────────────────────────────────────────────────────
    # Supported values: azure | groq | gemini
    ai_provider: str = field(
        default_factory=lambda: os.getenv("AI_PROVIDER", "groq")
    )

    # Azure OpenAI
    azure_api_key: str = field(default_factory=lambda: os.getenv("AZURE_API_KEY", ""))
    azure_api_base: str = field(default_factory=lambda: os.getenv("AZURE_API_BASE", ""))
    azure_api_version: str = field(
        default_factory=lambda: os.getenv("AZURE_API_VERSION", "2024-08-01-preview")
    )
    azure_deployment: str = field(default_factory=lambda: os.getenv("AZURE_DEPLOYMENT", "gpt-4o"))

    # Groq  (free tier — https://console.groq.com)
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    )

    # Google Gemini  (free tier — https://aistudio.google.com)
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    )

    company_capabilities: str = """
    Our company specialises in the following services:
    - Commercial and industrial cleaning / sanitation
    - Security and surveillance (guarding, CCTV)
    - Building and infrastructure maintenance
    - Green-space care / landscaping
    - Pest control / fumigation
    - General facility management
    """

    # ── Dashboard ─────────────────────────────────────────────────────────────
    dashboard_host: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_HOST", "0.0.0.0")
    )
    dashboard_port: int = field(
        default_factory=lambda: int(os.getenv("DASHBOARD_PORT", "8000"))
    )

    # ── Email / SMTP ──────────────────────────────────────────────────────────
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(
        default_factory=lambda: int(os.getenv("SMTP_PORT", "587"))
    )
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", ""))

    def __post_init__(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)


# Singleton
settings = Config()
