"""
FastAPI dashboard for reviewing and managing SEACE leads.

Endpoints
─────────
GET  /                        Dashboard HTML (or login page)
POST /api/auth/login          Login → session cookie
POST /api/auth/logout         Clear session cookie
GET  /api/auth/me             Current user info

GET  /api/leads               Paginated lead list (current user)
GET  /api/leads/{id}          Single lead
PATCH /api/leads/{id}         Update review / bid decision
DELETE /api/leads             Clear all leads for current user

GET  /api/stats               Aggregate counts (current user)
GET  /api/export/excel        Download .xlsx (current user)
GET  /api/runs                Recent run log (current user)

GET  /api/settings            Current scraper settings (current user)
PUT  /api/settings            Save settings for current user

POST /api/scrape/start        Launch scraper subprocess
GET  /api/scrape/status       Running state + live log tail
POST /api/scrape/stop         Kill running scraper

GET  /api/users               List users (admin only)
POST /api/users               Create user (admin only)
DELETE /api/users/{id}        Delete user (admin only)
"""
from __future__ import annotations

import os
import re
import sys
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Cookie
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from src.storage import repository as repo

app = FastAPI(title="SEACE Lead Dashboard", version="2.0")

_here    = Path(__file__).parent
_project = _here.parent.parent

templates = Jinja2Templates(directory=str(_here / "templates"))


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_current_user(session_token: str | None = None):
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = repo.get_session_user(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return user


def _require_admin(session_token: str | None = None):
    user = _get_current_user(session_token)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── HTML Dashboard ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# ── API: Auth ─────────────────────────────────────────────────────────────────

class LoginPayload(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(body: LoginPayload):
    user = repo.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")
    token = repo.create_session(user.id)
    response = JSONResponse(
        content={"ok": True, "username": user.username, "is_admin": user.is_admin}
    )
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


@app.post("/api/auth/logout")
async def logout(session: str | None = Cookie(default=None)):
    if session:
        repo.delete_session(session)
    response = JSONResponse(content={"ok": True})
    response.delete_cookie("session")
    return response


@app.get("/api/auth/me")
async def me(session: str | None = Cookie(default=None)):
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = repo.get_session_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}


# ── API: User management (admin only) ────────────────────────────────────────

class NewUserPayload(BaseModel):
    username: str
    password: str
    is_admin: bool = False


@app.get("/api/users")
async def list_users(session: str | None = Cookie(default=None)):
    _require_admin(session)
    users = repo.get_all_users()
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin,
             "created_at": u.created_at.isoformat()} for u in users]


@app.post("/api/users")
async def create_user(body: NewUserPayload, session: str | None = Cookie(default=None)):
    _require_admin(session)
    if repo.get_user_by_username(body.username):
        raise HTTPException(status_code=409, detail="El usuario ya existe")
    if len(body.password) < 6:
        raise HTTPException(status_code=422, detail="La contrasena debe tener al menos 6 caracteres")
    user = repo.create_user(body.username, body.password, body.is_admin)
    return {"ok": True, "id": user.id}


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, session: str | None = Cookie(default=None)):
    admin = _require_admin(session)
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta")
    repo.delete_user(user_id)
    return {"ok": True}


# ── API: Leads ────────────────────────────────────────────────────────────────

@app.get("/api/leads")
async def list_leads(
    min_score: int = Query(0, ge=0, le=100),
    reviewed: Optional[bool] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: str | None = Cookie(default=None),
):
    user = _get_current_user(session)
    leads = repo.get_leads(
        min_score=min_score, reviewed=reviewed, limit=limit,
        offset=offset, user_id=user.id,
    )
    total = repo.count_leads(min_score=min_score, user_id=user.id)
    return {"total": total, "offset": offset, "limit": limit,
            "items": [l.to_dict() for l in leads]}


@app.get("/api/leads/{lead_id}")
async def get_lead(lead_id: int, session: str | None = Cookie(default=None)):
    _get_current_user(session)
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead.to_dict()


class ReviewUpdate(BaseModel):
    reviewed: bool = True
    review_notes: str = ""
    bid_decision: str = ""


@app.patch("/api/leads/{lead_id}")
async def update_lead(lead_id: int, body: ReviewUpdate, session: str | None = Cookie(default=None)):
    _get_current_user(session)
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    repo.update_review(lead_id=lead_id, reviewed=body.reviewed,
                       review_notes=body.review_notes, bid_decision=body.bid_decision)
    return {"ok": True}


@app.delete("/api/leads")
async def clear_all_leads(session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    deleted = repo.delete_all_leads(user_id=user.id)
    return {"deleted": deleted}


@app.get("/api/pdf/{lead_id}")
async def serve_pdf(lead_id: int, session: str | None = Cookie(default=None)):
    _get_current_user(session)
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    path = Path(lead.pdf_local_path) if lead.pdf_local_path else None
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")
    return FileResponse(path=str(path), media_type="application/pdf", filename=path.name)


# ── API: Stats ────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def stats(session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    all_leads = repo.get_leads(min_score=0, limit=10_000, user_id=user.id)
    return {
        "total":    len(all_leads),
        "high":     sum(1 for l in all_leads if l.match_level == "HIGH"),
        "medium":   sum(1 for l in all_leads if l.match_level == "MEDIUM"),
        "low":      sum(1 for l in all_leads if l.match_level == "LOW"),
        "no_match": sum(1 for l in all_leads if l.match_level in ("NO_MATCH", "SKIPPED")),
        "reviewed": sum(1 for l in all_leads if l.reviewed),
        "bid":      sum(1 for l in all_leads if l.bid_decision == "BID"),
    }


# ── API: Export ───────────────────────────────────────────────────────────────

@app.get("/api/export/excel")
async def export_excel(
    min_score: int = Query(0, ge=0, le=100),
    session: str | None = Cookie(default=None),
):
    user = _get_current_user(session)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp_path = f.name
    repo.export_to_excel(tmp_path, min_score=min_score, user_id=user.id)
    filename = f"seace_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return FileResponse(
        tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


# ── API: Runs ─────────────────────────────────────────────────────────────────

@app.get("/api/runs")
async def recent_runs(session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    runs = repo.get_recent_runs(limit=20, user_id=user.id)
    return [
        {
            "run_id":          r.run_id,
            "started_at":      r.started_at.isoformat() if r.started_at else None,
            "finished_at":     r.finished_at.isoformat() if r.finished_at else None,
            "rows_scanned":    r.rows_scanned,
            "keyword_matches": r.keyword_matches,
            "leads_saved":     r.leads_saved,
            "status":          r.status,
            "error_message":   r.error_message,
        }
        for r in runs
    ]


# ── API: Settings (per-user) ─────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    keywords: list[str] = []
    spec_start_page: int = 20
    spec_end_page: int = 30
    max_pages: int = 0
    date_from: str = ""
    date_to: str = ""


@app.get("/api/settings")
async def get_settings(session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    return repo.get_all_user_settings(user.id)


@app.put("/api/settings")
async def update_settings(body: SettingsPayload, session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    if body.spec_start_page < 1 or body.spec_end_page < body.spec_start_page:
        raise HTTPException(status_code=422, detail="Invalid page range.")
    if not body.keywords:
        raise HTTPException(status_code=422, detail="At least one keyword required.")
    if body.max_pages < 0:
        raise HTTPException(status_code=422, detail="max_pages must be >= 0.")
    repo.set_user_setting(user.id, "keywords",        [k.strip() for k in body.keywords if k.strip()])
    repo.set_user_setting(user.id, "spec_start_page", body.spec_start_page)
    repo.set_user_setting(user.id, "spec_end_page",   body.spec_end_page)
    repo.set_user_setting(user.id, "max_pages",       body.max_pages)
    repo.set_user_setting(user.id, "date_from",       body.date_from.strip())
    repo.set_user_setting(user.id, "date_to",         body.date_to.strip())
    return {"ok": True}


# ── Scraper subprocess management ─────────────────────────────────────────────
# Each user gets their own _states entry keyed by user_id.

_states: dict[int, dict] = {}
_lock = threading.Lock()


def _get_user_state(user_id: int) -> dict:
    if user_id not in _states:
        _states[user_id] = {
            "running": False, "started_at": None, "mode": "",
            "log": [], "returncode": None, "process": None,
        }
    return _states[user_id]


def _reader_thread(proc: subprocess.Popen, user_id: int) -> None:
    try:
        for raw in proc.stdout:   # type: ignore[union-attr]
            line = re.sub(r"\x1b\[[0-9;]*m", "", raw.rstrip())
            with _lock:
                st = _get_user_state(user_id)
                st["log"].append(line)
                if len(st["log"]) > 500:
                    st["log"] = st["log"][-500:]
        proc.wait()
    finally:
        with _lock:
            st = _get_user_state(user_id)
            st["running"]    = False
            st["returncode"] = proc.returncode
            st["process"]    = None
            st["log"].append(
                "Scraper finalizado correctamente."
                if proc.returncode == 0
                else f"Scraper termino con error (codigo {proc.returncode})."
            )


class ScrapeOptions(BaseModel):
    no_pdf: bool = True
    no_ai:  bool = True
    search_query: str = ""


@app.post("/api/scrape/start")
async def start_scrape(body: ScrapeOptions, session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    with _lock:
        st = _get_user_state(user.id)
        if st["running"]:
            raise HTTPException(status_code=409, detail="Tu scraper ya esta en ejecucion.")

        cmd = [sys.executable, str(_project / "main.py"), "scrape",
               "--user-id", str(user.id)]
        if body.no_pdf:
            cmd.append("--no-pdf")
        if body.no_ai:
            cmd.append("--no-ai")
        if body.search_query.strip():
            cmd += ["--search-query", body.search_query.strip()]

        mode_parts = []
        if not body.no_pdf: mode_parts.append("PDF")
        if not body.no_ai:  mode_parts.append("IA")
        if body.search_query.strip():
            mode_parts.append(f'Busqueda: "{body.search_query.strip()}"')
        mode = " + ".join(mode_parts) if mode_parts else "Solo palabras clave"

        proc = subprocess.Popen(
            cmd,
            cwd=str(_project),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        st["running"]    = True
        st["started_at"] = datetime.utcnow().isoformat()
        st["mode"]       = mode
        st["log"]        = [f"Iniciando scraper ({mode})..."]
        st["returncode"] = None
        st["process"]    = proc

    t = threading.Thread(target=_reader_thread, args=(proc, user.id), daemon=True)
    t.start()
    return {"ok": True, "mode": mode, "started_at": st["started_at"]}


@app.get("/api/scrape/status")
async def scrape_status(
    since: int = Query(0, ge=0),
    session: str | None = Cookie(default=None),
):
    user = _get_current_user(session)
    with _lock:
        st = _get_user_state(user.id)
        log = st["log"]
        return {
            "running":    st["running"],
            "started_at": st["started_at"],
            "mode":       st["mode"],
            "returncode": st["returncode"],
            "log_from":   since,
            "log_lines":  log[since:],
            "log_total":  len(log),
        }


@app.post("/api/scrape/stop")
async def stop_scrape(session: str | None = Cookie(default=None)):
    user = _get_current_user(session)
    with _lock:
        st = _get_user_state(user.id)
        proc = st.get("process")
        if not proc or not st["running"]:
            raise HTTPException(status_code=409, detail="No hay scraper en ejecucion.")
        proc.terminate()
        st["log"].append("Detenido por el usuario.")
    return {"ok": True}


# ── Entry point ───────────────────────────────────────────────────────────────

def run_dashboard() -> None:
    import uvicorn
    from src.config import settings
    from src.storage.repository import init_db, ensure_admin_user

    init_db()
    ensure_admin_user()
    uvicorn.run(app, host=settings.dashboard_host, port=settings.dashboard_port,
                log_level="info")
