# SEACE Scraper & AI Filter

Automated pipeline that discovers, downloads, parses, and scores Peruvian government procurement opportunities from the [SEACE portal](https://prod2.seace.gob.pe/seacebus-uiwd-pub/fichaSeleccion/fichaSeleccion.xhtml).

```
Search SEACE → Keyword filter → Download PDF → Extract specs → Claude AI score → Dashboard
```

---

## Architecture

```
seace-scraper/
├── src/
│   ├── config.py                # All settings (env-driven)
│   ├── scraper/
│   │   ├── browser.py           # Playwright browser context manager
│   │   ├── search.py            # Search form automation + row scraping
│   │   ├── detail.py            # Ficha detail page navigation
│   │   └── downloader.py        # PDF download (JS interception)
│   ├── parser/
│   │   └── pdf_parser.py        # pdfplumber/pypdf + section extractor
│   ├── ai/
│   │   └── filter.py            # Claude API scoring (0-100)
│   ├── storage/
│   │   ├── models.py            # SQLAlchemy ORM (leads + run_log)
│   │   └── repository.py        # Data access + Excel export
│   └── dashboard/
│       ├── app.py               # FastAPI REST + serve HTML
│       └── templates/index.html # Bootstrap review dashboard
├── downloads/                   # Downloaded PDFs
├── logs/                        # Daily rotating log files
├── main.py                      # CLI entry point (Typer)
└── requirements.txt
```

### Tech Choices

| Layer | Library | Why |
|---|---|---|
| Browser automation | Playwright (async) | Handles PrimeFaces JSF, view states, JS downloads natively |
| PDF parsing | pdfplumber → pypdf fallback | pdfplumber preserves layout for better section detection |
| AI scoring | Anthropic Claude API | Structured JSON output, long context for large specs |
| Database | SQLite + SQLAlchemy | Zero-ops, portable, easy to inspect |
| Dashboard | FastAPI + Jinja2 + Bootstrap | Lightweight, no build step required |
| Excel export | openpyxl | Colour-coded sheets for easy review |

---

## Setup

### 1. Prerequisites

- Python 3.11+
- `pip`

### 2. Install dependencies

```bash
cd seace-scraper
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium      # Download the headless browser
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

Key settings in `.env`:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Claude API key |
| `KEYWORDS` | `limpieza,seguridad,...` | Comma-separated row-filter keywords |
| `HEADLESS` | `true` | Set `false` to watch the browser (debug) |
| `MAX_PAGES` | `0` (unlimited) | Limit pages scraped per run |
| `DB_PATH` | `seace_leads.db` | SQLite file location |

### 4. Customise company capabilities

Edit `src/config.py` → `company_capabilities` (or set via environment) to describe your company's services. Claude uses this to score each lead.

---

## Usage

### Run the scraper

```bash
python main.py scrape
# Add -v for verbose/debug output
python main.py scrape --verbose
```

The pipeline:
1. Opens SEACE in a headless Chromium browser
2. Clicks the search tab and executes the global search
3. Pages through all results, checking each row against your keywords
4. For matches: opens the ficha, downloads the base document PDF
5. Extracts the "Especificaciones Técnicas" section from the PDF
6. Sends the specs to Claude for scoring (0–100) and summary
7. Saves everything to `seace_leads.db`

### Launch the dashboard

```bash
python main.py dashboard
# Open http://localhost:8000
```

Dashboard features:
- Filter leads by score, match level, review status, or free text
- Click any row to see entity info, AI score, key requirements, and disqualifiers
- Record a bid decision (BID / SKIP / PENDING) and notes
- Export filtered results to a colour-coded Excel file

### Export to Excel directly

```bash
python main.py export --min-score 40 --out leads_q3.xlsx
```

### Show run history

```bash
python main.py runs
```

---

## How Resilient Selectors Work

PrimeFaces generates IDs like `tbBuscador:idFormBuscarProceso:pnlGrdResultadosProcesos`. These are *logical names* embedded in the generated ID, so we use **partial-match CSS selectors** (`[id*="pnlGrdResultadosProcesos"]`) instead of hardcoding full IDs.

Dynamic IDs like `j_idt471` are **never targeted directly**. Instead:
- Buttons → `button:has-text("Buscar")`
- Tabs → `a[href*="tab1"]`
- Ficha icons → `a:has(img[src*="fichaSeleccion"])`
- PDF links → `a[href*="descargaDocGeneral"]`
- Table rows → `tr[data-ri]` (PrimeFaces always emits `data-ri`)

---

## PDF Download Handling

`javascript:descargaDocGeneral(...)` triggers a hidden form POST. Playwright's `expect_download()` context manager intercepts the resulting HTTP response regardless of how it's triggered:

```python
async with page.expect_download(timeout=60_000) as dl_info:
    await page.evaluate("descargaDocGeneral('param1','param2','file.pdf',...)")
download = await dl_info.value
await download.save_as(str(dest_path))
```

A click-based fallback is attempted if JS evaluation fails.

---

## AI Scoring

Claude returns a JSON object with:

```json
{
  "match_score": 82,
  "summary": "El contrato requiere servicios de limpieza industrial...",
  "key_requirements": ["Certificación ISO 9001", "50 operarios mínimo"],
  "disqualifiers": ["Requiere experiencia en sector minero"]
}
```

Score bands:
- **90–100** — Perfect fit
- **70–89** — Strong fit
- **40–69** — Partial fit (worth reviewing)
- **15–39** — Weak fit
- **0–14** — No match

---

## Scheduling (daily automation)

### cron (Linux/macOS)
```bash
# Run every day at 7:00 AM Lima time
0 7 * * * cd /path/to/seace-scraper && .venv/bin/python main.py scrape >> logs/cron.log 2>&1
```

### Windows Task Scheduler
Create a task that runs `python main.py scrape` in the project directory.

---

## Database Schema

### `leads` table

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `run_id` | TEXT | Links to `run_log` |
| `scraped_at` | DATETIME | Timestamp |
| `entity` | TEXT | Government entity name |
| `nomenclature` | TEXT | Procurement reference code |
| `object_type` | TEXT | Type of contract |
| `description` | TEXT | Short description |
| `ficha_url` | TEXT | SEACE detail page URL |
| `pdf_local_path` | TEXT | Path to downloaded PDF |
| `tech_specs_text` | TEXT | Extracted specs section |
| `match_score` | INTEGER | 0–100 AI score |
| `match_level` | TEXT | HIGH / MEDIUM / LOW / NO_MATCH |
| `ai_summary` | TEXT | Claude's explanation |
| `key_requirements_json` | TEXT | JSON array of requirements |
| `disqualifiers_json` | TEXT | JSON array of concerns |
| `reviewed` | BOOLEAN | Has an employee reviewed it? |
| `bid_decision` | TEXT | BID / SKIP / PENDING |
| `review_notes` | TEXT | Employee notes |

### `run_log` table

Tracks each scraper execution: start/end time, row counts, status, errors.
# SEACE-SCRAPPER
