"""
PDF parsing module — no AI required.

Two extraction strategies (both available independently):

1. extract_page_range(path, start, end)
   ─────────────────────────────────────
   Pulls raw text from a specific page range (default pages 20–30, 1-indexed).
   This is where SEACE base documents typically put technical specs.
   Fast, deterministic, zero API cost.

2. extract_section(full_text)
   ───────────────────────────
   Scans the full document text for heading patterns like
   "Especificaciones Técnicas" / "Términos de Referencia" and slices out
   that section.  Falls back to the page-range text when no heading is found.

Public API
──────────
  parse_pdf(path)              → ParsedPDF  (uses both strategies)
  extract_page_range(path, …)  → str        (raw text from a page window)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from loguru import logger

# ── Section-heading patterns ──────────────────────────────────────────────────
SECTION_START_PATTERNS: list[str] = [
    r"especificaciones?\s+t[eé]cnicas",
    r"t[eé]rminos?\s+de\s+referencia",
    r"requerimientos?\s+t[eé]cnicos",
    r"descripci[oó]n\s+t[eé]cnica",
    r"caracter[ií]sticas?\s+t[eé]cnicas",
    r"alcance\s+del\s+servicio",
    r"alcance\s+de\s+la\s+obra",
]

SECTION_END_PATTERNS: list[str] = [
    r"requisitos?\s+de\s+calificaci[oó]n",
    r"factor(?:es)?\s+de\s+evaluaci[oó]n",
    r"criterios?\s+de\s+evaluaci[oó]n",
    r"condiciones?\s+del\s+contrato",
    r"garant[ií]as?\s+requeridas",
    r"formato\s+n?[°o]?\s*\d+",
]

MAX_CHARS = 15_000   # cap sent to the dashboard / AI

_RE_START = re.compile(
    "|".join(f"(?:{p})" for p in SECTION_START_PATTERNS), re.IGNORECASE
)
_RE_END = re.compile(
    "|".join(f"(?:{p})" for p in SECTION_END_PATTERNS), re.IGNORECASE
)


# ── Result type ───────────────────────────────────────────────────────────────

class ParsedPDF(NamedTuple):
    full_text: str            # entire document text (all pages)
    tech_specs: str           # best-effort technical specs section
    page_range_text: str      # raw text from pages 20-30 (always populated)
    page_count: int
    extraction_engine: str    # "pdfplumber" | "pypdf"


# ── Page-range extraction (primary no-AI output) ──────────────────────────────

def extract_page_range(
    path: Path,
    start_page: int = 20,   # 1-indexed, inclusive
    end_page: int = 30,     # 1-indexed, inclusive
) -> tuple[str, int]:
    """
    Extract raw text from pages [start_page … end_page] (1-indexed).

    Returns (text, total_page_count).
    Uses pdfplumber first, falls back to pypdf.
    """
    text, n_pages = "", 0

    # ── pdfplumber ────────────────────────────────────────────────────────────
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            n_pages = len(pdf.pages)
            # Clamp to actual page count
            s = max(0, start_page - 1)          # to 0-indexed
            e = min(n_pages, end_page)           # to 0-indexed exclusive
            chunks = []
            for pdf_page in pdf.pages[s:e]:
                t = pdf_page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                if t:
                    chunks.append(t)
            text = "\n\n".join(chunks)
            logger.debug(
                "pdfplumber pages {}-{} of {}: {} chars",
                start_page, end_page, n_pages, len(text),
            )
            return text[:MAX_CHARS], n_pages
    except Exception as exc:
        logger.warning("pdfplumber page-range failed: {}", exc)

    # ── pypdf fallback ────────────────────────────────────────────────────────
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        n_pages = len(reader.pages)
        s = max(0, start_page - 1)
        e = min(n_pages, end_page)
        chunks = [(reader.pages[i].extract_text() or "") for i in range(s, e)]
        text = "\n\n".join(chunks)
        logger.debug(
            "pypdf pages {}-{} of {}: {} chars",
            start_page, end_page, n_pages, len(text),
        )
        return text[:MAX_CHARS], n_pages
    except Exception as exc:
        logger.warning("pypdf page-range failed: {}", exc)

    return "", n_pages


# ── Full-document extraction ───────────────────────────────────────────────────

def _extract_full_text(path: Path) -> tuple[str, int, str]:
    """Returns (full_text, page_count, engine_name)."""
    try:
        import pdfplumber
        chunks = []
        with pdfplumber.open(str(path)) as pdf:
            n = len(pdf.pages)
            for p in pdf.pages:
                t = p.extract_text(x_tolerance=2, y_tolerance=2) or ""
                if t:
                    chunks.append(t)
        full = "\n".join(chunks)
        if len(full) >= 100:
            return full, n, "pdfplumber"
    except Exception as exc:
        logger.warning("pdfplumber full-text failed: {}", exc)

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        n = len(reader.pages)
        full = "\n".join(p.extract_text() or "" for p in reader.pages)
        return full, n, "pypdf"
    except Exception as exc:
        logger.warning("pypdf full-text failed: {}", exc)

    return "", 0, "none"


# ── Section detection ─────────────────────────────────────────────────────────

def _find_section(full_text: str) -> str:
    start_m = _RE_START.search(full_text)
    if not start_m:
        return ""
    start_idx = start_m.start()
    end_m = _RE_END.search(full_text, start_idx + len(start_m.group()))
    section = full_text[start_idx: end_m.start()] if end_m else full_text[start_idx: start_idx + MAX_CHARS]
    return section.strip()[:MAX_CHARS]


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_pdf(
    path: Path,
    spec_start_page: int = 20,
    spec_end_page: int = 30,
) -> ParsedPDF | None:
    """
    Parse a downloaded SEACE PDF.

    Always extracts pages spec_start_page–spec_end_page (no AI needed).
    Also attempts heading-based section detection across the full document.

    Returns None if the file cannot be read at all.
    """
    if not path.exists():
        logger.error("PDF not found: {}", path)
        return None

    logger.info("Parsing PDF: {} (pages {}-{})", path.name, spec_start_page, spec_end_page)

    # 1. Page-range text — fast, always run
    page_range_text, page_count_pr = extract_page_range(path, spec_start_page, spec_end_page)

    # 2. Full text + section detection
    full_text, page_count, engine = _extract_full_text(path)
    page_count = page_count or page_count_pr

    tech_specs = _find_section(full_text) if full_text else ""

    if not tech_specs:
        # Fall back: use the page-range text as the specs
        tech_specs = page_range_text
        logger.info(
            "No section heading found — using pages {}-{} text as specs ({} chars).",
            spec_start_page, spec_end_page, len(tech_specs),
        )
    else:
        logger.info(
            "Section heading found — {} chars extracted (engine={}).",
            len(tech_specs), engine,
        )

    return ParsedPDF(
        full_text=full_text,
        tech_specs=tech_specs,
        page_range_text=page_range_text,
        page_count=page_count,
        extraction_engine=engine,
    )
