"""Genera y envía el correo consolidado con daños declarados del día.

- Lee cargas finalizadas con `sin_danos=0 AND enviada_at IS NULL`
- Construye HTML imitando el formato de Captura.JPG (bloque verde por carga,
  tabla OP/CL | DAÑO)
- Adjunta las fotos de cada carga (data/fotos/...)
- Envía vía SMTP Outlook usando OUTLOOK_EMAIL / OUTLOOK_PASSWORD
- Marca las cargas como enviadas

Uso:
    python tools/send_consolidado_email.py [--dry-run]
"""

from __future__ import annotations

import os
import smtplib
import sys
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = PROJECT_ROOT.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PARENT_ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from db import (  # noqa: E402
    cargas_pendientes_de_envio,
    listar_danos_de_carga,
    listar_fotos_de_carga,
    marcar_cargas_enviadas,
)

OUTLOOK_EMAIL = os.getenv("OUTLOOK_EMAIL") or os.getenv("REMITENTE_DANOS", "")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
DESTINATARIOS = [
    s.strip() for s in os.getenv("DESTINATARIOS_DANOS", "").split(",") if s.strip()
]
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20 MB de adjuntos


def _build_html(cargas_con_danos: list[dict], fecha: date) -> str:
    """HTML imitando el layout de Captura.JPG."""
    fecha_str = fecha.strftime("%d-%m-%Y")
    bloques = []
    for c in cargas_con_danos:
        filas_html = "".join(
            f"<tr><td style='border:1px solid #444;padding:4px 8px;'>{entrega}</td>"
            f"<td style='border:1px solid #444;padding:4px 8px;'>{tipo}</td></tr>"
            for entrega, tipo in c["danos"]
        )
        bloque = f"""
<table style="border-collapse:collapse;margin-bottom:18px;font-family:Arial,sans-serif;font-size:13px;">
  <tr>
    <td style="background:#a9d08e;font-weight:bold;padding:6px 12px;border:1px solid #444;width:140px;">{fecha_str}</td>
    <td style="background:#a9d08e;font-weight:bold;padding:6px 12px;border:1px solid #444;">CARGA:{c['numero_carga']}</td>
  </tr>
  <tr>
    <td style="background:#a9d08e;font-weight:bold;padding:4px 8px;border:1px solid #444;">OP/CL</td>
    <td style="background:#a9d08e;font-weight:bold;padding:4px 8px;border:1px solid #444;">DAÑO</td>
  </tr>
  {filas_html}
</table>
"""
        bloques.append(bloque)

    return f"""<html><body style="font-family:Arial,sans-serif;font-size:13px;">
<p>Estimados,</p>
<p>A continuación, le envío los respaldos de productos identificados con daños de embalaje en andenes:</p>
{''.join(bloques)}
<p>Adjunto fotos de las hojas de carga físicas como respaldo.</p>
<p>Saludos cordiales.</p>
</body></html>
"""


def _gather_data() -> tuple[list[dict], list[Path]]:
    """Devuelve (lista de cargas con sus daños, lista de paths de fotos)."""
    cargas = cargas_pendientes_de_envio()
    resultado = []
    fotos: list[Path] = []
    for c in cargas:
        nc = c["numero_carga"]
        danos_dict = listar_danos_de_carga(nc)
        if not danos_dict:
            continue
        resultado.append({
            "numero_carga": nc,
            "danos": [
                (entrega, d["tipo_dano"])
                for entrega in sorted(danos_dict.keys())
                for d in danos_dict[entrega]
            ],
        })
        for f in listar_fotos_de_carga(nc):
            p = Path(f["ruta_archivo"])
            if not p.is_absolute():
                # Soporta paths nuevos (DATA_DIR) y legacy (PROJECT_ROOT)
                nuevo = DATA_DIR / p
                p = nuevo if nuevo.exists() else (PROJECT_ROOT / p)
            if p.exists():
                fotos.append(p)
    return resultado, fotos


def _attach_photos(msg: EmailMessage, fotos: list[Path]) -> int:
    """Adjunta fotos al mensaje. Si superan MAX_TOTAL_BYTES, comprime con Pillow."""
    if not fotos:
        return 0

    total = sum(p.stat().st_size for p in fotos)
    compress = total > MAX_TOTAL_BYTES
    adjuntadas = 0

    for p in fotos:
        try:
            if compress:
                from PIL import Image  # lazy import
                from io import BytesIO

                img = Image.open(p)
                buf = BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=70, optimize=True)
                data = buf.getvalue()
                ext = "jpg"
            else:
                data = p.read_bytes()
                ext = p.suffix.lstrip(".").lower() or "jpg"

            msg.add_attachment(
                data,
                maintype="image",
                subtype="jpeg" if ext in ("jpg", "jpeg") else ext,
                filename=p.name,
            )
            adjuntadas += 1
        except Exception as e:
            print(f"  ! No se pudo adjuntar {p.name}: {e}")
    return adjuntadas


def main(dry_run: bool = False) -> dict:
    if not OUTLOOK_EMAIL or not OUTLOOK_PASSWORD:
        sys.exit("ERROR: OUTLOOK_EMAIL u OUTLOOK_PASSWORD no definidos en .env")
    if not DESTINATARIOS:
        sys.exit("ERROR: DESTINATARIOS_DANOS no definido en .env")

    cargas_data, fotos = _gather_data()
    if not cargas_data:
        print("No hay cargas finalizadas pendientes de envío.")
        return {"enviadas": 0, "fotos": 0, "destinatarios": 0}

    hoy = date.today()
    asunto = f"Respaldo de Productos declarados con daños de embalaje en andenes {hoy.strftime('%d-%m-%Y')}"
    html = _build_html(cargas_data, hoy)

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr(("Declaración Daños Andén", OUTLOOK_EMAIL))
    msg["To"] = ", ".join(DESTINATARIOS)
    msg.set_content(
        "Este correo contiene la declaración consolidada de daños en formato HTML. "
        "Por favor active la vista HTML para verlo correctamente."
    )
    msg.add_alternative(html, subtype="html")

    n_fotos = _attach_photos(msg, fotos)

    print(f"Asunto: {asunto}")
    print(f"Destinatarios: {len(DESTINATARIOS)}")
    print(f"Cargas incluidas: {len(cargas_data)}")
    print(f"Fotos adjuntas: {n_fotos}")

    if dry_run:
        print("[DRY-RUN] No se envió el correo.")
        return {
            "enviadas": len(cargas_data),
            "fotos": n_fotos,
            "destinatarios": len(DESTINATARIOS),
            "dry_run": True,
        }

    print(f"Enviando vía {SMTP_SERVER}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        smtp.send_message(msg)

    numeros = [c["numero_carga"] for c in cargas_data]
    marcar_cargas_enviadas(numeros)
    print(f"✓ Correo enviado. Cargas marcadas como enviadas: {numeros}")

    return {
        "enviadas": len(cargas_data),
        "fotos": n_fotos,
        "destinatarios": len(DESTINATARIOS),
    }


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
