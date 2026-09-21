"""
Email notification sender for SEACE Buscador.

Sends an HTML alert when leads matching notification keywords are found
during a scheduled scan. Uses standard smtplib with STARTTLS (port 587).

Gmail users: create an App Password at https://myaccount.google.com/apppasswords
and use that instead of your regular Gmail password.
"""
from __future__ import annotations

import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _bare_address(addr: str) -> str:
    """Extract bare email from 'Display Name <email@domain>' or return as-is."""
    m = re.search(r'<([^>]+)>', addr)
    return m.group(1).strip() if m else addr.strip()


def _build_html(leads: list[dict], schedule_name: str) -> str:
    rows = ""
    for lead in leads[:50]:  # cap at 50 to keep email manageable
        score = lead.get("match_score", lead.get("score", "—"))
        url = lead.get("ficha_url", "")
        link = f'<a href="{url}">Ver ficha</a>' if url else "—"
        rows += (
            "<tr>"
            f'<td style="padding:6px 8px;border:1px solid #ddd">{lead.get("entity","")}</td>'
            f'<td style="padding:6px 8px;border:1px solid #ddd">{lead.get("nomenclature","")}</td>'
            f'<td style="padding:6px 8px;border:1px solid #ddd">{lead.get("description","")[:120]}</td>'
            f'<td style="padding:6px 8px;border:1px solid #ddd;text-align:center">{score}</td>'
            f'<td style="padding:6px 8px;border:1px solid #ddd;text-align:center">{link}</td>'
            "</tr>"
        )

    n = len(leads)
    truncation_note = (
        f"<p style='color:#888;font-size:12px'>Se muestran 50 de {n} licitaciones. "
        "Abre la aplicación para ver todos los resultados.</p>"
        if n > 50 else ""
    )

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:900px;margin:auto;padding:20px">
  <div style="background:#1d4ed8;padding:16px 24px;border-radius:6px 6px 0 0">
    <h2 style="color:white;margin:0">SEACE Buscador — Alerta de Licitaciones</h2>
  </div>
  <div style="border:1px solid #ddd;border-top:none;padding:20px;border-radius:0 0 6px 6px">
    <p>
      La búsqueda programada <strong>"{schedule_name}"</strong> encontró
      <strong>{n} licitación(es)</strong> que coinciden con tus palabras clave de alerta.
    </p>
    <p style="color:#888;font-size:12px">
      Ejecutado el {datetime.now().strftime("%d/%m/%Y a las %H:%M")}
    </p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead>
        <tr style="background:#eff6ff">
          <th style="padding:8px;border:1px solid #ddd;text-align:left">Entidad</th>
          <th style="padding:8px;border:1px solid #ddd;text-align:left">Nomenclatura</th>
          <th style="padding:8px;border:1px solid #ddd;text-align:left">Descripción</th>
          <th style="padding:8px;border:1px solid #ddd;text-align:center">Puntuación</th>
          <th style="padding:8px;border:1px solid #ddd;text-align:center">Enlace</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
    {truncation_note}
    <p style="margin-top:24px;color:#888;font-size:11px">
      Este correo fue enviado automáticamente por SEACE Buscador.
    </p>
  </div>
</body>
</html>
"""


def send_lead_alert(
    leads: list[dict],
    schedule_name: str,
    recipients: list[str],
) -> None:
    """
    Send an HTML email listing the matched leads.

    Raises:
        ValueError: if SMTP is not configured.
        smtplib.SMTPException: on connection / auth failure.
    """
    from src.config import settings

    if not settings.smtp_host or not settings.smtp_user:
        raise ValueError(
            "SMTP no configurado. Completa los campos de correo en ⚙️ Configuración."
        )

    display_sender = settings.smtp_from or settings.smtp_user
    envelope_from  = _bare_address(display_sender)
    subject = (
        f"[SEACE] {len(leads)} licitación(es) encontrada(s) — {schedule_name}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = display_sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(_build_html(leads, schedule_name), "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(envelope_from, recipients, msg.as_string())


def send_test_email(recipient: str) -> None:
    """Send a plain test email to verify SMTP settings."""
    from src.config import settings

    if not settings.smtp_host or not settings.smtp_user:
        raise ValueError(
            "SMTP no configurado. Completa los campos de correo en ⚙️ Configuración."
        )

    display_sender = settings.smtp_from or settings.smtp_user
    envelope_from  = _bare_address(display_sender)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[SEACE] Correo de prueba — configuración correcta"
    msg["From"] = display_sender
    msg["To"] = recipient
    body = (
        "<p>Este es un correo de prueba enviado por <strong>SEACE Buscador</strong>.</p>"
        "<p>Si recibes este mensaje, la configuración SMTP es correcta.</p>"
    )
    msg.attach(MIMEText(body, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(envelope_from, [recipient], msg.as_string())
