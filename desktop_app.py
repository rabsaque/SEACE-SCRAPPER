"""
desktop_app.py — SEACE Buscador (aplicación de escritorio)
Cross-platform: Windows y Linux.

Uso:
    python desktop_app.py

Para generar el ejecutable:
    pip install pyinstaller
    pyinstaller desktop_app.spec
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Paths — must be set before any local import ───────────────────────────────
# When packaged with PyInstaller, __file__ points to the temp extraction folder.
# Use sys.executable so DB and .env always live next to the installed .exe.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent
# DB lives next to the project files so the scraper and UI always share it.
# User data (logs, etc.) go to ~/.seace-scraper/ to keep the app folder clean.
DATA_DIR = Path.home() / ".seace-scraper"
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "logs").mkdir(exist_ok=True)
os.environ.setdefault("DB_PATH", str(BASE_DIR / "seace_leads.db"))
sys.path.insert(0, str(BASE_DIR))

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk

# ── Theme ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

DEFAULT_KEYWORDS: list[str] = [
    "DATALOGGER", "MACROMEDIDOR", "MEDIDOR DE FLUJO", "CAUDALIMETRO ULTRASONICO",
    "MEDIDOR DE NIVEL", "TRANSMISOR DE FLUJO", "GEOFONO", "CORRELADOR",
    "SENSOR DE PRESION", "TRANSMISOR DE PRESION", "CALIBRADOR DE PRESION",
    "MULTICALIBRADOR DE PRESION", "CAMARA DE INSPECCION", "INDICADOR DE PRESION",
    "LOCALIZADOR DE AVERIAS", "LOCALIZADOR DE CABLES", "MANOMETRO",
    "TRANSDUCTOR DE PRESION", "MANIFOLD", "DETECTOR DE FUGA", "LOCALIZADOR DE FUGA",
    "DETECTOR DE METALES", "GEORADAR", "MULTIPARAMETRO", "MEDIDOR DE CLORO",
    "DETECTOR DE GAS", "EXPLOSIMETRO", "DETECTOR MULTIGAS", "CABINA DE FLUJO",
    "CABINA DE BIOSEGURIDAD", "MANTENIMIENTO DE MACROMEDIDORES",
    "CALIBRACION DE MEDIDORES", "CONTROL DE SECTORES IMPLEMENTADOS",
    "CALIBRACION", "INSTALACION DE MACROMEDIDORES", "DETECCION DE FUGAS",
    "MANTENIMIENTO",
]

_LEVEL_COLOR = {
    "ERROR":   "#e74c3c",
    "WARNING": "#e67e22",
    "SUCCESS": "#27ae60",
    "INFO":    "#1a1a2e",
    "DEBUG":   "#7f8c8d",
}


class SEACEApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SEACE — Buscador de Licitaciones")
        self.geometry("1080x740")
        self.minsize(820, 580)

        self._msg_queue: queue.Queue = queue.Queue()
        self._scraper_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._leads: list[dict] = []
        self._run_job_id: int = 0   # DB job_id for the current run

        self._build_ui()
        self._poll_queue()

        # Start the background scheduler (runs while the app is open)
        from src.scheduler.service import SchedulerService
        self._scheduler_service = SchedulerService(self._msg_queue)
        self._scheduler_service.start()

        # Override close handler to shut scheduler down cleanly
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Deferred first-run check so the window appears first
        self.after(500, self._check_playwright_async)

    def _on_close(self) -> None:
        self._scheduler_service.stop()
        self.destroy()

    # ══════════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header bar
        hdr = ctk.CTkFrame(self, height=48, corner_radius=0,
                           fg_color=("#1d4ed8", "#1d4ed8"))
        hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            hdr,
            text="  SEACE Buscador de Licitaciones",
            font=ctk.CTkFont(size=21, weight="bold"),
            text_color="white",
        ).pack(side="left", padx=12, pady=10)

        self._status_bar = ctk.CTkLabel(
            hdr, text="Listo.", text_color="#93c5fd",
            font=ctk.CTkFont(size=17),
        )
        self._status_bar.pack(side="right", padx=16)

        # Tabs
        self._tabs = ctk.CTkTabview(self)
        self._tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        self._build_search_tab(self._tabs.add("Nueva Búsqueda"))
        self._build_progress_tab(self._tabs.add("Progreso"))
        self._build_results_tab(self._tabs.add("Resultados"))
        self._build_scheduler_tab(self._tabs.add("📅 Programar"))
        self._build_settings_tab(self._tabs.add("⚙️ Configuración"))

    # ── Search tab ────────────────────────────────────────────────────────────

    def _build_search_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(1, weight=1)

        r = 0

        # Keywords
        ctk.CTkLabel(tab, text="Palabras clave:", anchor="w").grid(
            row=r, column=0, sticky="nw", padx=12, pady=(12, 2))

        kf = ctk.CTkFrame(tab, fg_color="transparent")
        kf.grid(row=r, column=1, sticky="ew", padx=12, pady=(12, 2))
        kf.grid_columnconfigure(0, weight=1)

        self._kw_box = ctk.CTkTextbox(kf, height=190, font=ctk.CTkFont(family="Courier", size=15))
        self._kw_box.grid(row=0, column=0, sticky="ew")
        self._kw_box.insert("1.0", "\n".join(DEFAULT_KEYWORDS))

        ctk.CTkButton(kf, text="Restaurar predeterminadas", width=210,
                      fg_color="gray", hover_color="#555",
                      command=self._reset_keywords).grid(row=1, column=0, sticky="e", pady=(3, 0))
        r += 1

        # Description search
        ctk.CTkLabel(tab, text="Buscar descripción:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._desc_entry = ctk.CTkEntry(
            tab, placeholder_text="Término opcional en campo descripción SEACE")
        self._desc_entry.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        # Dates — DateEntry gives a popup calendar
        try:
            from tkcalendar import DateEntry as _DE
            _have_cal = True
        except ImportError:
            _have_cal = False

        ctk.CTkLabel(tab, text="Fecha desde:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        if _have_cal:
            df = tk.Frame(tab, bg="white")
            df.grid(row=r, column=1, sticky="w", padx=12, pady=5)
            self._date_from = _DE(
                df, date_pattern="dd/MM/yyyy", width=14,
                background="#1d4ed8", foreground="white",
                headersbackground="#1e3a8a", headersforeground="white",
                selectbackground="#2563eb", selectforeground="white",
                font=("Segoe UI", 14),
            )
            self._date_from.pack(side="left")
            # "Clear" button so the field can be left blank (no date filter)
            def _clear_from():
                self._date_from.delete(0, "end")
            tk.Button(df, text="✕", relief="flat", fg="#6b7280", cursor="hand2",
                      command=_clear_from).pack(side="left", padx=(4,0))
        else:
            self._date_from = ctk.CTkEntry(tab, placeholder_text="DD/MM/AAAA  (opcional)")
            self._date_from.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        ctk.CTkLabel(tab, text="Fecha hasta:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        if _have_cal:
            dt = tk.Frame(tab, bg="white")
            dt.grid(row=r, column=1, sticky="w", padx=12, pady=5)
            self._date_to = _DE(
                dt, date_pattern="dd/MM/yyyy", width=14,
                background="#1d4ed8", foreground="white",
                headersbackground="#1e3a8a", headersforeground="white",
                selectbackground="#2563eb", selectforeground="white",
                font=("Segoe UI", 14),
            )
            self._date_to.pack(side="left")
            def _clear_to():
                self._date_to.delete(0, "end")
            tk.Button(dt, text="✕", relief="flat", fg="#6b7280", cursor="hand2",
                      command=_clear_to).pack(side="left", padx=(4,0))
        else:
            self._date_to = ctk.CTkEntry(tab, placeholder_text="DD/MM/AAAA  (opcional)")
            self._date_to.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        # Max pages
        ctk.CTkLabel(tab, text="Máx. páginas:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        pf = ctk.CTkFrame(tab, fg_color="transparent")
        pf.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        self._max_pages = ctk.CTkEntry(pf, width=90, placeholder_text="0 = sin límite")
        self._max_pages.grid(row=0, column=0)
        ctk.CTkLabel(pf, text="  (0 = escanea todo)", text_color="gray").grid(row=0, column=1)
        r += 1

        # Options
        of = ctk.CTkFrame(tab, fg_color="transparent")
        of.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        self._use_ai_var = ctk.BooleanVar(value=True)
        self._dl_pdf_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(of, text="Usar IA para resumir", variable=self._use_ai_var).grid(
            row=0, column=0, padx=(0, 20))
        ctk.CTkCheckBox(of, text="Descargar PDFs", variable=self._dl_pdf_var).grid(
            row=0, column=1)
        r += 1

        # Buttons
        bf = ctk.CTkFrame(tab, fg_color="transparent")
        bf.grid(row=r, column=0, columnspan=2, pady=18)

        self._start_btn = ctk.CTkButton(
            bf, text="▶  Iniciar búsqueda", width=190, height=42,
            font=ctk.CTkFont(size=20, weight="bold"),
            command=self._start_scrape)
        self._start_btn.grid(row=0, column=0, padx=8)

        self._stop_btn = ctk.CTkButton(
            bf, text="⏹  Detener", width=130, height=42,
            fg_color="#dc2626", hover_color="#b91c1c",
            state="disabled", command=self._stop_scrape)
        self._stop_btn.grid(row=0, column=1, padx=8)

    # ── Scheduler tab ─────────────────────────────────────────────────────────

    def _build_scheduler_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Info banner
        info = ctk.CTkLabel(
            tab,
            text="ℹ️  La aplicación debe estar abierta para que las búsquedas "
                 "programadas se ejecuten automáticamente.",
            fg_color="#eff6ff", text_color="#1d4ed8", corner_radius=6,
            wraplength=700, anchor="w", justify="left",
        )
        info.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        # Treeview
        cols = ("name", "freq", "time", "enabled", "last_run", "next_run")
        self._sched_tree = ttk.Treeview(
            tab, columns=cols, show="headings", height=14, selectmode="browse"
        )
        for col, heading, width in [
            ("name",     "Nombre",          200),
            ("freq",     "Frecuencia",       100),
            ("time",     "Hora",              70),
            ("enabled",  "Habilitado",        90),
            ("last_run", "Último ejecución", 150),
            ("next_run", "Próxima ejecución",150),
        ]:
            self._sched_tree.heading(col, text=heading)
            self._sched_tree.column(col, width=width, anchor="center")
        self._sched_tree.column("name", anchor="w")
        self._sched_tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)

        # Scrollbar
        sb = ttk.Scrollbar(tab, orient="vertical", command=self._sched_tree.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=4)
        self._sched_tree.configure(yscrollcommand=sb.set)

        # Buttons
        bf = ctk.CTkFrame(tab, fg_color="transparent")
        bf.grid(row=2, column=0, pady=6)
        ctk.CTkButton(bf, text="➕  Nueva programación",
                      command=self._sched_new).pack(side="left", padx=6)
        ctk.CTkButton(bf, text="✏️  Editar",
                      fg_color="gray", hover_color="#555",
                      command=self._sched_edit).pack(side="left", padx=6)
        ctk.CTkButton(bf, text="▶  Ejecutar ahora",
                      fg_color="#0891b2", hover_color="#0e7490",
                      command=self._sched_run_now).pack(side="left", padx=6)
        ctk.CTkButton(bf, text="🗑️  Eliminar",
                      fg_color="#dc2626", hover_color="#b91c1c",
                      command=self._sched_delete).pack(side="left", padx=6)

        self._sched_refresh()

    def _sched_refresh(self) -> None:
        """Reload scheduled scans from DB into the treeview."""
        for row in self._sched_tree.get_children():
            self._sched_tree.delete(row)
        try:
            from src.storage.repository import list_scheduled_scans, init_db
            init_db()
            for scan in list_scheduled_scans():
                day_names = ["lunes", "martes", "miércoles", "jueves",
                             "viernes", "sábado", "domingo"]
                freq = (
                    f"Semanal ({day_names[scan.day_of_week]})"
                    if scan.frequency == "weekly"
                    else "Diaria"
                )
                last = (scan.last_run_at.strftime("%d/%m/%Y %H:%M")
                        if scan.last_run_at else "—")
                nxt  = (scan.next_run_at.strftime("%d/%m/%Y %H:%M")
                        if scan.next_run_at else "—")
                self._sched_tree.insert("", "end", iid=str(scan.id), values=(
                    scan.name, freq, scan.time_of_day,
                    "Sí" if scan.enabled else "No",
                    last, nxt,
                ))
        except Exception as exc:
            self._log_append("ERROR", f"Error cargando programaciones: {exc}")

    def _sched_selected_id(self) -> int | None:
        sel = self._sched_tree.selection()
        return int(sel[0]) if sel else None

    def _sched_new(self) -> None:
        self._sched_open_form(None)

    def _sched_edit(self) -> None:
        scan_id = self._sched_selected_id()
        if scan_id is None:
            messagebox.showwarning("Sin selección",
                                   "Selecciona una programación para editar.")
            return
        self._sched_open_form(scan_id)

    def _sched_delete(self) -> None:
        scan_id = self._sched_selected_id()
        if scan_id is None:
            messagebox.showwarning("Sin selección",
                                   "Selecciona una programación para eliminar.")
            return
        if not messagebox.askyesno("Confirmar eliminación",
                                   "¿Eliminar esta programación?", icon="warning"):
            return
        try:
            from src.storage.repository import delete_scheduled_scan
            delete_scheduled_scan(scan_id)
            if hasattr(self, "_scheduler_service"):
                self._scheduler_service.reload()
            self._sched_refresh()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo eliminar:\n{exc}")

    def _sched_run_now(self) -> None:
        scan_id = self._sched_selected_id()
        if scan_id is None:
            messagebox.showwarning("Sin selección",
                                   "Selecciona una programación para ejecutar.")
            return
        if self._scraper_thread and self._scraper_thread.is_alive():
            messagebox.showwarning("Escaneo en curso",
                                   "Espera a que termine el escaneo actual antes de ejecutar otro.")
            return
        try:
            from src.storage.repository import get_scheduled_scan
            scan = get_scheduled_scan(scan_id)
            if scan is None:
                return
            self._log_append("INFO", f"Ejecutando manualmente: \"{scan.name}\"…")
            threading.Thread(
                target=lambda s=scan: self._scheduler_service._execute_scan(s.id),
                daemon=True,
            ).start()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _sched_open_form(self, scan_id: int | None) -> None:
        """Open the create/edit popup for a scheduled scan."""
        from src.storage.repository import get_scheduled_scan

        existing = get_scheduled_scan(scan_id) if scan_id else None

        win = ctk.CTkToplevel(self)
        win.title("Editar programación" if existing else "Nueva programación")
        win.geometry("980x520")
        win.resizable(True, False)
        win.update_idletasks()
        win.grab_set()
        messagebox.showinfo(
            "Ventana de programación",
            "La ventana principal quedará bloqueada mientras esta vista esté abierta.\n\n"
            "Cierra esta ventana para volver a usar el resto de la aplicación.",
            parent=win,
        )

        # ── Two-column layout: left = scan settings, right = notifications ──
        win.grid_columnconfigure(0, weight=1)
        win.grid_columnconfigure(1, weight=1)
        win.grid_rowconfigure(0, weight=1)

        left  = ctk.CTkFrame(win)
        right = ctk.CTkFrame(win)
        left.grid (row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        left.grid_columnconfigure(1, weight=1)
        right.grid_columnconfigure(1, weight=1)

        # shared helpers
        day_names_es = ["Lunes", "Martes", "Miércoles", "Jueves",
                        "Viernes", "Sábado", "Domingo"]

        def lbl_on(parent, text, row):
            ctk.CTkLabel(parent, text=text, anchor="w").grid(
                row=row, column=0, sticky="nw", padx=10, pady=6)

        # ── LEFT: scan settings ───────────────────────────────────────────────
        ctk.CTkLabel(left, text="Configuración del escaneo",
                     font=ctk.CTkFont(size=17, weight="bold")).grid(
                     row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4))

        lbl_on(left, "Nombre:", 1)
        e_name = ctk.CTkEntry(left)
        e_name.insert(0, existing.name if existing else "")
        e_name.grid(row=1, column=1, sticky="ew", padx=10, pady=6)

        lbl_on(left, "Palabras clave\n(una por línea):", 2)
        e_kw = ctk.CTkTextbox(left, height=110)
        kw_text = "\n".join(existing.keywords if existing else DEFAULT_KEYWORDS[:5])
        e_kw.insert("1.0", kw_text)
        e_kw.grid(row=2, column=1, sticky="ew", padx=10, pady=6)

        lbl_on(left, "Frecuencia:", 3)
        freq_var = ctk.StringVar(value=existing.frequency if existing else "daily")
        ctk.CTkOptionMenu(left, values=["daily", "weekly"],
                          variable=freq_var, width=160).grid(
                          row=3, column=1, sticky="w", padx=10, pady=6)

        lbl_on(left, "Día de la semana:", 4)
        day_var = ctk.StringVar(
            value=day_names_es[existing.day_of_week] if existing else "Lunes")
        ctk.CTkOptionMenu(left, values=day_names_es,
                          variable=day_var, width=160).grid(
                          row=4, column=1, sticky="w", padx=10, pady=6)

        lbl_on(left, "Hora (HH:MM):", 5)
        e_time = ctk.CTkEntry(left, width=100, placeholder_text="08:00")
        e_time.insert(0, existing.time_of_day if existing else "08:00")
        e_time.grid(row=5, column=1, sticky="w", padx=10, pady=6)

        lbl_on(left, "Opciones:", 6)
        ai_var  = ctk.BooleanVar(value=existing.use_ai if existing else False)
        pdf_var = ctk.BooleanVar(value=existing.download_pdf if existing else True)
        ena_var = ctk.BooleanVar(value=existing.enabled if existing else True)
        opts_frm = ctk.CTkFrame(left, fg_color="transparent")
        opts_frm.grid(row=6, column=1, sticky="w", padx=10, pady=6)
        ctk.CTkCheckBox(opts_frm, text="Usar IA",         variable=ai_var ).pack(anchor="w")
        ctk.CTkCheckBox(opts_frm, text="Descargar PDFs",  variable=pdf_var).pack(anchor="w")
        ctk.CTkCheckBox(opts_frm, text="Habilitado",      variable=ena_var).pack(anchor="w")

        # ── RIGHT: notifications ──────────────────────────────────────────────
        ctk.CTkLabel(right, text="Notificaciones por correo",
                     font=ctk.CTkFont(size=17, weight="bold")).grid(
                     row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4))

        lbl_on(right, "Palabras clave\nde alerta:", 1)
        e_nkw = ctk.CTkTextbox(right, height=140)
        nkw_text = "\n".join(existing.notify_keywords if existing else [])
        e_nkw.insert("1.0", nkw_text)
        e_nkw.grid(row=1, column=1, sticky="ew", padx=10, pady=6)

        lbl_on(right, "Correos de\nnotificación:", 2)
        e_emails = ctk.CTkTextbox(right, height=140)
        email_text = "\n".join(existing.notify_emails if existing else [])
        e_emails.insert("1.0", email_text)
        e_emails.grid(row=2, column=1, sticky="ew", padx=10, pady=6)

        ctk.CTkLabel(right, text="Un correo por línea. Se enviará una alerta\n"
                     "cuando se encuentre alguna palabra clave de alerta.",
                     text_color="gray", font=ctk.CTkFont(size=13),
                     anchor="w", justify="left").grid(
                     row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))

        # Save / Cancel
        def _save_form():
            name = e_name.get().strip()
            if not name:
                messagebox.showwarning("Campo requerido",
                                       "El nombre es obligatorio.", parent=win)
                return
            time_str = e_time.get().strip() or "08:00"
            try:
                hh, mm = time_str.split(":")
                assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
            except Exception:
                messagebox.showwarning("Hora inválida",
                    "Usa el formato HH:MM (ej. 08:00).", parent=win)
                return

            keywords  = [k.strip() for k in e_kw.get("1.0", "end").splitlines() if k.strip()]
            nkw       = [k.strip() for k in e_nkw.get("1.0", "end").splitlines() if k.strip()]
            emails    = [e.strip() for e in e_emails.get("1.0", "end").splitlines() if e.strip()]
            dow       = day_names_es.index(day_var.get())

            try:
                from src.storage import repository as repo
                if existing:
                    import json as _json
                    repo.update_scheduled_scan(existing.id,
                        name=name,
                        keywords_json=_json.dumps(keywords, ensure_ascii=False),
                        frequency=freq_var.get(),
                        time_of_day=time_str,
                        day_of_week=dow,
                        enabled=ena_var.get(),
                        use_ai=ai_var.get(),
                        download_pdf=pdf_var.get(),
                        notify_keywords_json=_json.dumps(nkw, ensure_ascii=False),
                        notify_emails_json=_json.dumps(emails, ensure_ascii=False),
                    )
                else:
                    repo.create_scheduled_scan(
                        name=name, keywords=keywords,
                        frequency=freq_var.get(), time_of_day=time_str,
                        day_of_week=dow, enabled=ena_var.get(),
                        use_ai=ai_var.get(), download_pdf=pdf_var.get(),
                        notify_keywords=nkw, notify_emails=emails,
                    )
                if hasattr(self, "_scheduler_service"):
                    self._scheduler_service.reload()
                self._sched_refresh()
                win.destroy()
            except Exception as exc:
                messagebox.showerror("Error al guardar", str(exc), parent=win)

        btn_frm = ctk.CTkFrame(win, fg_color="transparent")
        btn_frm.grid(row=1, column=0, columnspan=2, pady=10)
        ctk.CTkButton(btn_frm, text="💾  Guardar", width=160,
                      command=_save_form).pack(side="left", padx=8)
        ctk.CTkButton(btn_frm, text="Cancelar", width=120,
                      fg_color="gray", hover_color="#555",
                      command=win.destroy).pack(side="left", padx=8)

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Wrap everything in a scrollable frame so the save button is always reachable
        sf = ctk.CTkScrollableFrame(tab)
        sf.grid(row=0, column=0, sticky="nsew")
        sf.grid_columnconfigure(1, weight=1)
        tab = sf  # redirect all subsequent .grid() calls into the scrollable frame

        env_path = BASE_DIR / ".env"

        def _read_env() -> dict:
            """Read key=value pairs from .env, ignoring comments."""
            vals = {}
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        vals[k.strip()] = v.strip()
            return vals

        def _write_env(updates: dict) -> None:
            """Write updates into .env, preserving comments and existing keys."""
            lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
            written = set()
            out = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    if k in updates:
                        out.append(f"{k}={updates[k]}")
                        written.add(k)
                        continue
                out.append(line)
            # Append any keys not already in file
            for k, v in updates.items():
                if k not in written:
                    out.append(f"{k}={v}")
            env_path.write_text("\n".join(out) + "\n", encoding="utf-8")

        current = _read_env()
        r = 0

        # Section: IA
        ctk.CTkLabel(tab, text="Proveedor de Inteligencia Artificial",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=r, column=0, columnspan=2,
                                      sticky="w", padx=12, pady=(14, 4))
        r += 1

        ctk.CTkLabel(tab, text="Proveedor:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_provider = ctk.CTkOptionMenu(
            tab, values=["groq", "gemini", "azure"], width=200)
        self._cfg_provider.set(current.get("AI_PROVIDER", "groq"))
        self._cfg_provider.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        r += 1

        # Groq
        ctk.CTkLabel(tab, text="Clave API Groq:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_groq_key = ctk.CTkEntry(tab, width=420, show="*",
                                           placeholder_text="gsk_…")
        self._cfg_groq_key.insert(0, current.get("GROQ_API_KEY", ""))
        self._cfg_groq_key.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        ctk.CTkLabel(tab, text="Modelo Groq:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_groq_model = ctk.CTkEntry(tab, width=280)
        self._cfg_groq_model.insert(0, current.get("GROQ_MODEL", "llama-3.3-70b-versatile"))
        self._cfg_groq_model.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        r += 1

        # Gemini
        ctk.CTkLabel(tab, text="Clave API Gemini:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_gemini_key = ctk.CTkEntry(tab, width=420, show="*",
                                             placeholder_text="AIza…")
        self._cfg_gemini_key.insert(0, current.get("GEMINI_API_KEY", ""))
        self._cfg_gemini_key.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        # Section: Scraper
        ctk.CTkLabel(tab, text="Comportamiento del Scraper",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=r, column=0, columnspan=2,
                                      sticky="w", padx=12, pady=(18, 4))
        r += 1

        ctk.CTkLabel(tab, text="Timeout navegación (ms):", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_timeout = ctk.CTkEntry(tab, width=120)
        self._cfg_timeout.insert(0, current.get("NAV_TIMEOUT_MS", "90000"))
        self._cfg_timeout.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        r += 1

        # ── Section: Email / SMTP ──────────────────────────────────────────────
        ctk.CTkLabel(tab, text="Configuración de Correo Electrónico",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=r, column=0, columnspan=2,
                                      sticky="w", padx=12, pady=(18, 4))
        r += 1

        ctk.CTkLabel(tab, text="Servidor SMTP:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_smtp_host = ctk.CTkEntry(tab, width=280,
                                           placeholder_text="smtp.gmail.com")
        self._cfg_smtp_host.insert(0, current.get("SMTP_HOST", ""))
        self._cfg_smtp_host.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        r += 1

        ctk.CTkLabel(tab, text="Puerto SMTP:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_smtp_port = ctk.CTkEntry(tab, width=100)
        self._cfg_smtp_port.insert(0, current.get("SMTP_PORT", "587"))
        self._cfg_smtp_port.grid(row=r, column=1, sticky="w", padx=12, pady=5)
        r += 1

        ctk.CTkLabel(tab, text="Usuario SMTP:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_smtp_user = ctk.CTkEntry(tab, width=320,
                                           placeholder_text="tucorreo@gmail.com")
        self._cfg_smtp_user.insert(0, current.get("SMTP_USER", ""))
        self._cfg_smtp_user.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        ctk.CTkLabel(tab, text="Contraseña SMTP:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_smtp_pass = ctk.CTkEntry(tab, width=320, show="*",
                                           placeholder_text="App Password (Gmail) o contraseña SMTP")
        self._cfg_smtp_pass.insert(0, current.get("SMTP_PASSWORD", ""))
        self._cfg_smtp_pass.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        ctk.CTkLabel(tab, text="Remitente:", anchor="w").grid(
            row=r, column=0, sticky="w", padx=12, pady=5)
        self._cfg_smtp_from = ctk.CTkEntry(tab, width=320,
                                           placeholder_text="SEACE Buscador <tucorreo@gmail.com>")
        self._cfg_smtp_from.insert(0, current.get("SMTP_FROM", ""))
        self._cfg_smtp_from.grid(row=r, column=1, sticky="ew", padx=12, pady=5)
        r += 1

        def _test_email():
            # Use Remitente as recipient (it's always a full email address).
            # Fall back to SMTP user only if Remitente is empty.
            from_raw = self._cfg_smtp_from.get().strip()
            # Extract bare address from "Display Name <addr@domain>" if needed
            import re as _re
            m = _re.search(r'<([^>]+)>', from_raw)
            recipient = m.group(1) if m else (from_raw or self._cfg_smtp_user.get().strip())
            if not recipient:
                messagebox.showwarning("Sin remitente",
                    "Completa el campo 'Remitente' o 'Usuario SMTP' antes de enviar la prueba.")
                return
            # Save SMTP settings to .env automatically so they persist after restart
            _write_env({
                "SMTP_HOST":     self._cfg_smtp_host.get().strip(),
                "SMTP_PORT":     self._cfg_smtp_port.get().strip(),
                "SMTP_USER":     self._cfg_smtp_user.get().strip(),
                "SMTP_PASSWORD": self._cfg_smtp_pass.get().strip(),
                "SMTP_FROM":     self._cfg_smtp_from.get().strip(),
            })
            _apply_smtp_env()
            threading.Thread(target=_do_test_email, args=(recipient,), daemon=True).start()

        def _do_test_email(recipient: str) -> None:
            try:
                from src.notifications.email_sender import send_test_email
                send_test_email(recipient)
                self.after(0, lambda: messagebox.showinfo("Correo enviado",
                    f"Correo de prueba enviado a {recipient}.\n"
                    "Revisa tu bandeja de entrada."))
            except Exception as exc:
                self.after(0, lambda e=exc: messagebox.showerror("Error al enviar",
                    f"No se pudo enviar el correo:\n{e}"))

        ctk.CTkButton(tab, text="📧  Enviar correo de prueba",
                      fg_color="#0891b2", hover_color="#0e7490",
                      command=_test_email).grid(row=r, column=1, sticky="w",
                                                padx=12, pady=4)
        r += 1
        ctk.CTkLabel(tab,
                     text="Haz clic en '💾 Guardar configuración' para que los datos de correo persistan al cerrar la app.",
                     text_color="gray", font=ctk.CTkFont(size=15),
                     wraplength=420, anchor="w", justify="left").grid(
                         row=r, column=1, sticky="w", padx=12, pady=(0, 4))
        r += 1

        def _apply_smtp_env() -> None:
            for k, v in {
                "SMTP_HOST":     self._cfg_smtp_host.get().strip(),
                "SMTP_PORT":     self._cfg_smtp_port.get().strip(),
                "SMTP_USER":     self._cfg_smtp_user.get().strip(),
                "SMTP_PASSWORD": self._cfg_smtp_pass.get().strip(),
                "SMTP_FROM":     self._cfg_smtp_from.get().strip(),
            }.items():
                if v:
                    os.environ[k] = v
            # Reload the config singleton so email_sender picks up the new values
            try:
                from src.config import settings
                settings.smtp_host     = os.environ.get("SMTP_HOST", "")
                settings.smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
                settings.smtp_user     = os.environ.get("SMTP_USER", "")
                settings.smtp_password = os.environ.get("SMTP_PASSWORD", "")
                settings.smtp_from     = os.environ.get("SMTP_FROM", "")
            except Exception:
                pass

        # Save button
        def _save():
            updates = {
                "AI_PROVIDER":   self._cfg_provider.get(),
                "GROQ_API_KEY":  self._cfg_groq_key.get().strip(),
                "GROQ_MODEL":    self._cfg_groq_model.get().strip(),
                "GEMINI_API_KEY":self._cfg_gemini_key.get().strip(),
                "NAV_TIMEOUT_MS":self._cfg_timeout.get().strip(),
                "SMTP_HOST":     self._cfg_smtp_host.get().strip(),
                "SMTP_PORT":     self._cfg_smtp_port.get().strip(),
                "SMTP_USER":     self._cfg_smtp_user.get().strip(),
                "SMTP_PASSWORD": self._cfg_smtp_pass.get().strip(),
                "SMTP_FROM":     self._cfg_smtp_from.get().strip(),
            }
            _write_env(updates)
            # Apply immediately to running process
            for k, v in updates.items():
                if v:
                    os.environ[k] = v
            _apply_smtp_env()
            messagebox.showinfo("Guardado",
                "Configuración guardada correctamente.\n"
                "Los cambios de clave API se aplican de inmediato.")

        ctk.CTkButton(tab, text="💾  Guardar configuración",
                      width=220, height=38,
                      command=_save).grid(row=r, column=0, columnspan=2, pady=20)

    # ── Progress tab ──────────────────────────────────────────────────────────

    def _build_progress_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Stats counters
        sf = ctk.CTkFrame(tab)
        sf.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        for col, (label, attr) in enumerate([
            ("Filas escaneadas", "_stat_scanned"),
            ("Coincidencias",    "_stat_matches"),
            ("Leads guardados",  "_stat_saved"),
        ]):
            card = ctk.CTkFrame(sf)
            card.grid(row=0, column=col, padx=20, pady=10, sticky="ew")
            sf.grid_columnconfigure(col, weight=1)
            num = ctk.CTkLabel(card, text="0",
                               font=ctk.CTkFont(size=39, weight="bold"))
            num.pack(pady=(6, 0))
            ctk.CTkLabel(card, text=label, text_color="gray",
                         font=ctk.CTkFont(size=15)).pack(pady=(0, 6))
            setattr(self, attr, num)

        # Log box
        self._log_box = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Courier", size=15),
            state="disabled", wrap="word")
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))

    # ── Results tab ───────────────────────────────────────────────────────────

    def _build_results_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Style the treeview to look clean
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Leads.Treeview",
                        rowheight=36, font=("Segoe UI", 14),
                        borderwidth=0, relief="flat")
        style.configure("Leads.Treeview.Heading",
                        font=("Segoe UI", 14, "bold"), background="#e2e8f0")
        style.map("Leads.Treeview", background=[("selected", "#bfdbfe")])

        # Style for cronograma treeview (larger rows, no overlap)
        style.configure("Crono.Treeview",
                        rowheight=36, font=("Segoe UI", 13),
                        borderwidth=0, relief="flat")
        style.configure("Crono.Treeview.Heading",
                        font=("Segoe UI", 13, "bold"), background="#e2e8f0")
        style.map("Crono.Treeview", background=[("selected", "#bfdbfe")])

        tree_frame = ctk.CTkFrame(tab, fg_color="transparent")
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        cols = ("reviewed", "entity", "nomenclature", "description", "score", "level")
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            selectmode="browse", style="Leads.Treeview")

        for col, heading, width, stretch in [
            ("reviewed",     "✓",            28,  False),
            ("entity",       "Entidad",      200, False),
            ("nomenclature", "Nomenclatura", 120, False),
            ("description",  "Descripción",  360, True),
            ("score",        "Puntaje",       60, False),
            ("level",        "Nivel",         70, False),
        ]:
            self._tree.heading(col, text=heading)
            self._tree.column(col, width=width, minwidth=20, stretch=stretch)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._tree.bind("<Double-1>", self._on_lead_double_click)

        # Bottom bar
        bf = ctk.CTkFrame(tab, fg_color="transparent")
        bf.grid(row=1, column=0, pady=6)
        ctk.CTkButton(bf, text="📊  Exportar a Excel",
                      command=self._export_excel).pack(side="left", padx=8)
        ctk.CTkButton(bf, text="🔄  Actualizar",
                      fg_color="gray", hover_color="#555",
                      command=self._refresh_results).pack(side="left", padx=8)
        ctk.CTkButton(bf, text="🗑️  Limpiar resultados",
                      fg_color="#dc2626", hover_color="#b91c1c",
                      command=self._clear_all_leads).pack(side="left", padx=8)
        self._result_count_lbl = ctk.CTkLabel(
            bf, text="0 resultados", text_color="gray")
        self._result_count_lbl.pack(side="left", padx=16)

    # ══════════════════════════════════════════════════════════════════════════
    # Scraper control
    # ══════════════════════════════════════════════════════════════════════════

    def _start_scrape(self) -> None:
        keywords = [k.strip() for k in self._kw_box.get("1.0", "end").splitlines() if k.strip()]
        if not keywords:
            messagebox.showerror("Error", "Ingresa al menos una palabra clave.")
            return

        try:
            max_pages = int(self._max_pages.get().strip() or "0") or None
        except ValueError:
            max_pages = None

        params = dict(
            keywords=keywords,
            date_from=self._date_from.get().strip(),
            date_to=self._date_to.get().strip(),
            search_query=self._desc_entry.get().strip(),
            max_pages=max_pages,
            use_ai=self._use_ai_var.get(),
            download_pdf=self._dl_pdf_var.get(),
        )

        self._stop_event.clear()
        self._leads = []
        self._clear_log()
        self._clear_tree()
        self._set_running(True)
        self._tabs.set("Progreso")

        self._scraper_thread = threading.Thread(
            target=self._thread_fn, args=(params,), daemon=True)
        self._scraper_thread.start()

    def _stop_scrape(self) -> None:
        self._stop_event.set()
        self._log_append("WARNING", "Solicitud de detención enviada — terminando operación actual...")

    def _thread_fn(self, params: dict) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_scrape(params))
        except Exception:
            import traceback
            self._msg_queue.put(("error", traceback.format_exc()))
        finally:
            loop.close()

    async def _async_scrape(self, params: dict) -> None:
        from loguru import logger
        from main import run_pipeline
        from src.storage.repository import init_db

        init_db()
        logger.remove()

        q = self._msg_queue

        def _sink(msg):
            rec = msg.record
            q.put(("log", rec["level"].name, rec["message"]))

        logger.add(_sink, level="INFO")
        logger.add(
            str(DATA_DIR / "logs" / "scraper.log"),
            level="DEBUG", rotation="10 MB", encoding="utf-8")

        result = await run_pipeline(
            verbose=False,
            use_ai=params["use_ai"],
            download_pdf=params["download_pdf"],
            search_query=params["search_query"],
            keywords=params["keywords"],
            date_from=params["date_from"],
            date_to=params["date_to"],
            max_pages=params["max_pages"],
            job_id=0,
            user_id=0,
        )
        q.put(("done", result))

    # ══════════════════════════════════════════════════════════════════════════
    # Queue polling (runs on GUI thread via after())
    # ══════════════════════════════════════════════════════════════════════════

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log_append(msg[1], msg[2])
                elif kind == "done":
                    self._on_done(msg[1])
                elif kind == "error":
                    self._log_append("ERROR", msg[1])
                    self._set_running(False)
                    self._status_bar.configure(
                        text="Error — revisa el log", text_color="#fca5a5")
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    # ══════════════════════════════════════════════════════════════════════════
    # Log helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _log_append(self, level: str, text: str) -> None:
        self._log_box.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        color = _LEVEL_COLOR.get(level, "#1a1a2e")
        tag = f"lvl_{level}"
        self._log_box.tag_config(tag, foreground=color)
        self._log_box.insert("end", f"[{ts}] [{level:<7}] {text}\n", tag)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

        # Mirror stats from log messages (scraper logs "scanned=X matches=Y saved=Z")
        import re
        if m := re.search(r"scanned[=\s]+(\d+).*?matches[=\s]+(\d+).*?saved[=\s]+(\d+)", text, re.I):
            self._stat_scanned.configure(text=m.group(1))
            self._stat_matches.configure(text=m.group(2))
            self._stat_saved.configure(text=m.group(3))

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")
        for attr in ("_stat_scanned", "_stat_matches", "_stat_saved"):
            getattr(self, attr).configure(text="0")
        self._status_bar.configure(text="Ejecutando…", text_color="#93c5fd")

    # ══════════════════════════════════════════════════════════════════════════
    # Results
    # ══════════════════════════════════════════════════════════════════════════

    def _clear_tree(self) -> None:
        """Clear only the treeview rows — does NOT reset self._leads."""
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._result_count_lbl.configure(text="0 resultados")

    def _refresh_results(self) -> None:
        try:
            from src.storage.repository import get_leads, init_db
            init_db()
            leads_obj = get_leads(limit=500)
            self._leads = [
                {
                    "id":              l.id,
                    "entity":          l.entity,
                    "nomenclature":    l.nomenclature,
                    "object_type":     l.object_type,
                    "description":     l.description,
                    "ficha_url":       l.ficha_url,
                    "pdf_local_path":  l.pdf_local_path,
                    "pdf_page_count":  l.pdf_page_count,
                    "tech_specs_text": l.tech_specs_text,
                    "score":           l.match_score,
                    "level":           l.match_level,
                    "ai_summary":      l.ai_summary,
                    "key_requirements": l.key_requirements,
                    "disqualifiers":   l.disqualifiers,
                    "cronograma":      l.cronograma,
                    "reviewed":        l.reviewed,
                    "review_notes":    l.review_notes,
                    "bid_decision":    l.bid_decision,
                    "scraped_at":      l.scraped_at.strftime("%d/%m/%Y %H:%M") if l.scraped_at else "",
                }
                for l in leads_obj
            ]
            self._populate_tree()
            self._log_append("INFO", f"Tabla actualizada: {len(self._leads)} lead(s) cargados.")
        except Exception as exc:
            import traceback
            self._log_append("ERROR", f"Error al cargar resultados: {exc}\n{traceback.format_exc()}")

    def _populate_tree(self) -> None:
        self._clear_tree()  # clear rows only, self._leads is already set
        self._tree.tag_configure("reviewed_row", foreground="#6b7280")
        for lead in self._leads:
            tags = ("reviewed_row",) if lead.get("reviewed") else ()
            self._tree.insert("", "end", tags=tags, values=(
                "✓" if lead.get("reviewed") else "",
                lead.get("entity", ""),
                lead.get("nomenclature", ""),
                (lead.get("description") or "")[:140],
                lead.get("score", ""),
                lead.get("level", ""),
            ))
        n = len(self._leads)
        reviewed_n = sum(1 for l in self._leads if l.get("reviewed"))
        self._result_count_lbl.configure(
            text=f"{n} resultado{'s' if n != 1 else ''}  ({reviewed_n} revisados)")

    def _on_done(self, result: dict) -> None:
        scanned = result.get("rows_scanned", 0)
        matches = result.get("keyword_matches", 0)
        saved   = result.get("leads_saved", 0)
        self._stat_scanned.configure(text=str(scanned))
        self._stat_matches.configure(text=str(matches))
        self._stat_saved.configure(text=str(saved))
        self._set_running(False)
        self._status_bar.configure(
            text=f"Completado — {saved} lead(s) guardados", text_color="#86efac")
        self._log_append(
            "SUCCESS",
            f"Búsqueda completada: {scanned} filas escaneadas, "
            f"{matches} coincidencias, {saved} leads guardados.")
        self._refresh_results()
        self._tabs.set("Resultados")

    # ── Lead detail popup ─────────────────────────────────────────────────────

    def _on_lead_double_click(self, _event) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        if idx >= len(self._leads):
            return
        self._show_detail(self._leads[idx])

    def _show_detail(self, lead: dict) -> None:
        import webbrowser, json as _json

        win = ctk.CTkToplevel(self)
        win.title(f"Detalle — {lead.get('nomenclature', '')}")
        win.geometry("780x680")
        win.update_idletasks()
        win.grab_set()
        # Notify the user that the main window is locked while this is open
        messagebox.showinfo(
            "Ventana de detalle",
            "La ventana principal quedará bloqueada mientras esta vista esté abierta.\n\n"
            "Cierra esta ventana para volver a usar el resto de la aplicación.",
            parent=win,
        )
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)

        # ── Notebook (tabs inside popup) ──────────────────────────────────────
        nb = ttk.Notebook(win)
        nb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # Helper: make a scrollable text tab
        def _text_tab(title: str) -> tk.Text:
            frm = tk.Frame(nb, bg="#f8fafc")
            frm.grid_columnconfigure(0, weight=1)
            frm.grid_rowconfigure(0, weight=1)
            t = tk.Text(frm, wrap="word", font=("Segoe UI", 14),
                        relief="flat", padx=10, pady=8,
                        bg="#f8fafc", fg="#1a1a2e")
            vsb = ttk.Scrollbar(frm, orient="vertical", command=t.yview)
            t.configure(yscrollcommand=vsb.set)
            t.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            t.tag_configure("h",   font=("Segoe UI", 14, "bold"), foreground="#1d4ed8")
            t.tag_configure("val", font=("Segoe UI", 14),          foreground="#1a1a2e")
            t.tag_configure("sub", font=("Segoe UI",  9, "italic"),foreground="#374151")
            t.tag_configure("ok",  font=("Segoe UI", 14),          foreground="#16a34a")
            t.tag_configure("bad", font=("Segoe UI", 14),          foreground="#dc2626")
            nb.add(frm, text=title)
            return t

        # ── Tab 1: Información general ────────────────────────────────────────
        t1 = _text_tab("📋 General")
        for label, value in [
            ("Entidad",       lead.get("entity", "")),
            ("Nomenclatura",  lead.get("nomenclature", "")),
            ("Tipo de objeto",lead.get("object_type", "")),
            ("Descripción",   lead.get("description", "")),
            ("Fecha scraping",lead.get("scraped_at", "")),
            ("Puntuación IA", f"{lead.get('score', 0)} — {lead.get('level', '')}"),
            ("URL Ficha SEACE",lead.get("ficha_url", "")),
        ]:
            t1.insert("end", f"{label}\n", "h")
            t1.insert("end", f"{value or '—'}\n\n", "val")
        t1.configure(state="disabled")

        # ── Tab 2: Resumen IA ─────────────────────────────────────────────────
        t2 = _text_tab("🤖 Resumen IA")
        ai = lead.get("ai_summary") or ""
        reqs = lead.get("key_requirements") or []
        disq = lead.get("disqualifiers") or []

        t2.insert("end", "Resumen\n", "h")
        t2.insert("end", f"{ai or 'No disponible'}\n\n", "val")

        if reqs:
            t2.insert("end", "Requisitos clave\n", "h")
            for r in reqs:
                t2.insert("end", f"  ✓ {r}\n", "ok")
            t2.insert("end", "\n")

        if disq:
            t2.insert("end", "Descalificadores\n", "h")
            for d in disq:
                t2.insert("end", f"  ✗ {d}\n", "bad")
            t2.insert("end", "\n")

        tech = lead.get("tech_specs_text") or ""
        if tech:
            t2.insert("end", "Especificaciones técnicas (PDF)\n", "h")
            t2.insert("end", tech[:3000] + ("…" if len(tech) > 3000 else ""), "sub")
        t2.configure(state="disabled")

        # ── Tab 3: Cronograma ─────────────────────────────────────────────────
        crono_frm = tk.Frame(nb, bg="#f8fafc")
        crono_frm.grid_columnconfigure(0, weight=1)
        crono_frm.grid_rowconfigure(0, weight=1)
        nb.add(crono_frm, text="📅 Cronograma")

        cronograma = lead.get("cronograma") or []
        if cronograma:
            cols_c = ("stage", "date_start", "date_end")
            tree_c = ttk.Treeview(crono_frm, columns=cols_c, show="headings",
                                  height=15, style="Crono.Treeview")
            tree_c.heading("stage",      text="Etapa")
            tree_c.heading("date_start", text="Fecha inicio")
            tree_c.heading("date_end",   text="Fecha fin")
            tree_c.column("stage",      width=380, stretch=True)
            tree_c.column("date_start", width=180)
            tree_c.column("date_end",   width=180)
            vsb_c = ttk.Scrollbar(crono_frm, orient="vertical", command=tree_c.yview)
            tree_c.configure(yscrollcommand=vsb_c.set)
            tree_c.grid(row=0, column=0, sticky="nsew", padx=(6,0), pady=6)
            vsb_c.grid(row=0, column=1, sticky="ns", pady=6, padx=(0,4))
            def _get(stage, *keys):
                """Case-insensitive key lookup across possible field names."""
                low = {k.lower().replace(" ", "_"): v for k, v in stage.items()}
                for k in keys:
                    if k.lower().replace(" ", "_") in low:
                        return low[k.lower().replace(" ", "_")]
                return ""

            for stage in cronograma:
                tree_c.insert("", "end", values=(
                    _get(stage, "etapa", "stage", "name", "descripcion"),
                    _get(stage, "fecha_inicio", "fecha inicio", "date_start", "inicio"),
                    _get(stage, "fecha_fin",    "fecha fin",   "date_end",   "fin"),
                ))
        else:
            tk.Label(crono_frm, text="Sin cronograma disponible",
                     bg="#f8fafc", fg="#6b7280",
                     font=("Segoe UI", 15)).grid(pady=40)

        # ── Tab 4: Revisión ───────────────────────────────────────────────────
        rev_frm = ctk.CTkFrame(win)  # NOT added to nb yet — we grid it separately
        rev_outer = tk.Frame(nb, bg="#f5f5f5")
        rev_outer.grid_columnconfigure(0, weight=1)
        nb.add(rev_outer, text="✏️ Revisión")

        rev_reviewed = ctk.BooleanVar(value=bool(lead.get("reviewed")))
        rev_decision = ctk.StringVar(value=lead.get("bid_decision") or "pendiente")

        pad = dict(padx=16, pady=6)
        ctk.CTkLabel(rev_outer, text="Estado de revisión",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        ctk.CTkCheckBox(rev_outer, text="Marcado como revisado",
                        variable=rev_reviewed).pack(anchor="w", padx=16)

        ctk.CTkLabel(rev_outer, text="Decisión de oferta",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=16, pady=(12,2))
        for val, lbl in [
            ("pendiente",  "⏳ Pendiente"),
            ("participar", "✅ Participar"),
            ("descartar",  "❌ Descartar"),
            ("evaluar",    "🔍 Evaluar más"),
        ]:
            ctk.CTkRadioButton(rev_outer, text=lbl,
                               variable=rev_decision, value=val).pack(
                anchor="w", padx=32, pady=1)

        ctk.CTkLabel(rev_outer, text="Notas",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=16, pady=(12,2))
        notes_box = ctk.CTkTextbox(rev_outer, height=100)
        notes_box.pack(fill="x", padx=16)
        notes_box.insert("1.0", lead.get("review_notes") or "")

        def _save_review():
            from src.storage.repository import update_review
            lead_id = lead.get("id")
            if not lead_id:
                return
            update_review(
                lead_id=lead_id,
                reviewed=rev_reviewed.get(),
                bid_decision=rev_decision.get(),
                review_notes=notes_box.get("1.0", "end").strip(),
            )
            # Update local cache
            lead["reviewed"]     = rev_reviewed.get()
            lead["bid_decision"] = rev_decision.get()
            lead["review_notes"] = notes_box.get("1.0", "end").strip()
            # Refresh tree row colour
            self._populate_tree()
            self._log_append("SUCCESS", f"Revisión guardada para {lead.get('nomenclature')}")

        ctk.CTkButton(rev_outer, text="💾  Guardar revisión",
                      command=_save_review).pack(pady=12)

        # ── Bottom button bar ─────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.grid(row=1, column=0, pady=(0, 8))

        ficha_url    = lead.get("ficha_url", "").strip()
        nomenclature = lead.get("nomenclature", "").strip()

        # ficha_url encodes permanent SEACE params: nidProceso, nidConvocatoria, etc.
        # Opening the ficha requires replaying the PrimeFaces POST — we do this
        # by launching a headed Playwright browser that submits the form.
        import urllib.parse as _up
        _fparams = dict(_up.parse_qsl(_up.urlparse(ficha_url).query)) if ficha_url else {}

        _desc = (lead.get("description") or "")[:120].strip()
        _search_term = _desc or nomenclature
        if _search_term:
            def _open_seace(st=_search_term):
                self._open_seace_headed(st)
            ctk.CTkButton(btn_frame, text="🔗  Abrir en SEACE",
                          command=_open_seace).pack(side="left", padx=4)

        if nomenclature:
            def _copy_nc(n=nomenclature):
                win.clipboard_clear(); win.clipboard_append(n); win.update()
            ctk.CTkButton(btn_frame, text="📋  Copiar nomenclatura",
                          fg_color="#6b7280", hover_color="#4b5563",
                          command=_copy_nc).pack(side="left", padx=4)

        pdf_path = lead.get("pdf_local_path", "").strip()
        if pdf_path and os.path.exists(pdf_path):
            def _open_pdf(p=pdf_path):
                if sys.platform.startswith("win"):
                    os.startfile(p)
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", p])
            ctk.CTkButton(btn_frame, text="📄  Abrir PDF",
                          fg_color="#0891b2", hover_color="#0e7490",
                          command=_open_pdf).pack(side="left", padx=4)

        if ficha_url:
            def _copy_url(u=ficha_url):
                win.clipboard_clear(); win.clipboard_append(u); win.update()
            ctk.CTkButton(btn_frame, text="📋  Copiar URL ficha",
                          fg_color="#6b7280", hover_color="#4b5563",
                          command=_copy_url).pack(side="left", padx=4)

        ctk.CTkButton(btn_frame, text="Cerrar", fg_color="gray",
                      hover_color="#555", command=win.destroy).pack(side="left", padx=4)

    # ── Export to Excel ───────────────────────────────────────────────────────

    def _export_excel(self) -> None:
        if not self._leads:
            messagebox.showinfo("Sin datos", "No hay resultados para exportar.\n"
                                             "Ejecuta una búsqueda primero.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
            initialfile=f"seace_leads_{datetime.now():%Y%m%d_%H%M}.xlsx",
        )
        if not path:
            return

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Leads SEACE"

            headers = ["Entidad", "Nomenclatura", "Descripción",
                       "Puntuación", "Nivel", "URL Ficha", "Resumen IA"]
            ws.append(headers)

            blue = PatternFill("solid", fgColor="1D4ED8")
            bold_white = Font(bold=True, color="FFFFFF")
            for cell in ws[1]:
                cell.font = bold_white
                cell.fill = blue
                cell.alignment = Alignment(horizontal="center", vertical="center")

            col_widths = [35, 18, 65, 12, 12, 55, 65]
            for i, w in enumerate(col_widths, 1):
                ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
            ws.row_dimensions[1].height = 20

            for lead in self._leads:
                ws.append([
                    lead.get("entity", ""),
                    lead.get("nomenclature", ""),
                    lead.get("description", ""),
                    lead.get("score", ""),
                    lead.get("level", ""),
                    lead.get("ficha_url", ""),
                    lead.get("ai_summary") or "",
                ])

            wb.save(path)
            messagebox.showinfo("Exportado", f"Archivo guardado:\n{path}")

        except ImportError:
            messagebox.showerror("Falta dependencia",
                                 "Instala openpyxl:\n  pip install openpyxl")
        except Exception as exc:
            messagebox.showerror("Error al exportar", str(exc))

    # ══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _clear_all_leads(self) -> None:
        if not messagebox.askyesno(
            "Confirmar limpieza",
            "¿Eliminar TODOS los leads de la base de datos?\n\nEsta acción no se puede deshacer.",
            icon="warning",
        ):
            return
        try:
            from src.storage.repository import delete_all_leads, init_db
            init_db()
            n = delete_all_leads()
            self._leads = []
            self._clear_tree()
            self._log_append("INFO", f"{n} lead(s) eliminados de la base de datos.")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo limpiar:\n{exc}")

    def _open_seace_headed(self, search_term: str) -> None:
        """Launch a visible Playwright browser and search SEACE by description."""
        self._log_append("INFO",
            "Abriendo SEACE en el navegador… se abrirá una ventana de Chrome.")
        threading.Thread(
            target=lambda: asyncio.run(self._async_seace_browser(search_term)),
            daemon=True,
        ).start()

    async def _async_seace_browser(self, search_term: str) -> None:
        from playwright.async_api import async_playwright, TimeoutError as _PWT

        SEARCH_URL = ("https://prod2.seace.gob.pe/seacebus-uiwd-pub/"
                      "buscadorPublico/buscadorPublico.xhtml")
        FIELD_ID   = "tbBuscador:idFormBuscarProceso:descripcionObjeto"

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page    = await browser.new_page()

            try:
                # 1. Load page
                await page.goto(SEARCH_URL, wait_until="networkidle", timeout=40_000)

                # 2. Click the "Buscador de Procedimientos de Selección" tab
                try:
                    tab = page.get_by_role("tab", name="Buscador de Procedimientos de Selección")
                    await tab.wait_for(state="visible", timeout=15_000)
                    await tab.click()
                except Exception:
                    tab = page.locator("text=Buscador de Procedimientos de Selección").first
                    await tab.click()

                # 3. Wait for the description field
                await page.wait_for_selector(
                    f'[id="{FIELD_ID}"]', state="visible", timeout=15_000)
                await page.wait_for_timeout(500)

                # 4. Fill "Descripción del Objeto" using keyboard events
                field = page.locator(f'[id="{FIELD_ID}"]')
                await field.click()
                await page.keyboard.press("Control+a")
                await page.keyboard.type(search_term[:100], delay=40)
                await page.wait_for_timeout(400)

                # 5. Click Buscar
                try:
                    buscar = page.locator('[id*="btnBuscar"], button:has-text("Buscar"), input[value="Buscar"]').first
                    await buscar.wait_for(state="visible", timeout=8_000)
                    await buscar.click()
                    self._msg_queue.put(("log", "SUCCESS",
                        "Búsqueda enviada — el navegador está abierto con los resultados."))
                except Exception as e:
                    self._msg_queue.put(("log", "WARNING",
                        f"No se pudo hacer clic en Buscar: {e}. Presiona el botón manualmente."))

            except Exception as exc:
                self._msg_queue.put(("log", "ERROR", f"Error automatizando SEACE: {exc}"))

            # Always keep browser open until user closes the tab
            try:
                await page.wait_for_event("close", timeout=600_000)
            except Exception:
                pass

    def _set_running(self, running: bool) -> None:
        self._start_btn.configure(state="disabled" if running else "normal")
        self._stop_btn.configure(state="normal"   if running else "disabled")

    def _reset_keywords(self) -> None:
        self._kw_box.delete("1.0", "end")
        self._kw_box.insert("1.0", "\n".join(DEFAULT_KEYWORDS))

    # ── First-run Playwright browser check ───────────────────────────────────

    def _check_playwright_async(self) -> None:
        threading.Thread(target=self._check_playwright, daemon=True).start()

    def _check_playwright(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                if not os.path.exists(p.chromium.executable_path):
                    self.after(0, self._offer_install)
        except Exception:
            self.after(0, self._offer_install)

    def _offer_install(self) -> None:
        if messagebox.askyesno(
            "Configuración inicial",
            "Primera ejecución: se necesita instalar el navegador Chromium (~150 MB).\n\n"
            "¿Instalar ahora? (solo ocurre una vez)",
        ):
            self._do_install_playwright()

    def _do_install_playwright(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Instalando Chromium…")
        win.geometry("420x130")
        win.resizable(False, False)
        win.update_idletasks()
        win.grab_set()
        ctk.CTkLabel(
            win, text="Descargando Chromium, por favor espera…\nEsto solo ocurre una vez.",
            wraplength=380,
        ).pack(pady=16)
        bar = ctk.CTkProgressBar(win, mode="indeterminate")
        bar.pack(fill="x", padx=24)
        bar.start()

        def _run():
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
            )
            self.after(0, lambda: (
                win.destroy(),
                messagebox.showinfo("Listo", "Chromium instalado correctamente.\nYa puedes iniciar búsquedas."),
            ))

        threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    app = SEACEApp()
    app.mainloop()


if __name__ == "__main__":
    main()
