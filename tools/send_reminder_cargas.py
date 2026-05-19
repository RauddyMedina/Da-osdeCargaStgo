"""Envía recordatorio si hay cargas en estado 'por_declarar' al cierre del día.

Uso:
    python tools/send_reminder_cargas.py            # hoy
    python tools/send_reminder_cargas.py 2026-05-18 # fecha específica

Cron Render (render.yaml):
    schedule: "0 22 * * 1-5"   # lunes-viernes 22:00 UTC = 18:00 Chile
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / ".env")

from db import listar_cargas_por_fecha  # noqa: E402

OUTLOOK_EMAIL = os.getenv("OUTLOOK_EMAIL", "")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
DESTINATARIOS = [
    s.strip() for s in os.getenv("DESTINATARIOS_DANOS", "").split(",") if s.strip()
]


def main(fecha: date | None = None) -> int:
    """Envía recordatorio de cargas pendientes. Devuelve cantidad de cargas pendientes."""
    if fecha is None:
        fecha = date.today()

    pendientes = listar_cargas_por_fecha(fecha, estado="por_declarar")
    if not pendientes:
        print(f"[{fecha}] No hay cargas pendientes. Sin envío.")
        return 0

    if not OUTLOOK_EMAIL or not OUTLOOK_PASSWORD:
        print("ERROR: OUTLOOK_EMAIL u OUTLOOK_PASSWORD no definidos.")
        return len(pendientes)
    if not DESTINATARIOS:
        print("ERROR: DESTINATARIOS_DANOS no definido.")
        return len(pendientes)

    lineas = "\n".join(
        f"  • {c['numero_carga']} — {c['total_entregas']} entregas"
        f" (CD: {c['cd'] or '-'}, Andén: {c['anden'] or '-'})"
        for c in pendientes
    )
    cuerpo = (
        f"Quedan {len(pendientes)} carga(s) SIN FINALIZAR para el "
        f"{fecha.strftime('%d-%m-%Y')}:\n\n"
        f"{lineas}\n\n"
        "Por favor declare los daños o marque sin daños antes del cierre del día."
    )

    msg = EmailMessage()
    msg["Subject"] = (
        f"⚠️ Cargas pendientes de declaración — {fecha.strftime('%d-%m-%Y')}"
    )
    msg["From"] = formataddr(("Declaración Daños Andén", OUTLOOK_EMAIL))
    msg["To"] = ", ".join(DESTINATARIOS)
    msg.set_content(cuerpo)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        smtp.send_message(msg)

    print(f"✓ Recordatorio enviado. Cargas pendientes: {len(pendientes)}")
    return len(pendientes)


if __name__ == "__main__":
    fecha_arg = None
    if len(sys.argv) > 1:
        fecha_arg = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    sys.exit(0 if main(fecha_arg) >= 0 else 1)
