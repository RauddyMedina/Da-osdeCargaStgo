"""Genera el correo consolidado con daños declarados del día.

Modos:
- draft (recomendado): crea borrador en la carpeta Borradores/Drafts de Outlook via IMAP APPEND
- send: envía directamente vía SMTP
- dry-run: solo muestra info, no toca nada

Lee cargas finalizadas con `sin_danos=0 AND enviada_at IS NULL`, construye HTML
con bloque por carga (tabla OP/CL | DAÑO), adjunta fotos, marca como enviadas.

Uso:
    python tools/send_consolidado_email.py --draft     # crea borrador
    python tools/send_consolidado_email.py --send      # envía
    python tools/send_consolidado_email.py --dry-run   # preview
"""

from __future__ import annotations

import imaplib
import os
import smtplib
import sys
import time
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate
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
    eliminar_fotos_de_cargas,
    listar_danos_de_carga,
    listar_fotos_de_carga,
    marcar_cargas_enviadas,
)

OUTLOOK_EMAIL = os.getenv("OUTLOOK_EMAIL") or os.getenv("REMITENTE_DANOS", "")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
IMAP_SERVER = os.getenv("IMAP_SERVER", "outlook.office365.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
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


def _find_drafts_folder(imap: imaplib.IMAP4_SSL) -> str:
    """Detecta la carpeta de borradores (Drafts/Borradores) en la cuenta IMAP."""
    # Intentar nombres comunes primero (rápido)
    for fname in ("Drafts", "Borradores", "INBOX/Drafts", "INBOX/Borradores"):
        status, _ = imap.select(f'"{fname}"', readonly=False)
        if status == "OK":
            return fname

    # Fallback: parsear LIST y buscar por flag \Drafts
    status, folders = imap.list()
    if status != "OK" or not folders:
        raise RuntimeError("No se pudo listar carpetas IMAP")
    for line in folders:
        decoded = line.decode() if isinstance(line, bytes) else line
        if "\\Drafts" in decoded:
            # formato: (\HasNoChildren \Drafts) "/" "Drafts"
            parts = decoded.rsplit(' "', 1)
            if len(parts) == 2:
                name = parts[1].rstrip('"').strip('"')
                if imap.select(f'"{name}"')[0] == "OK":
                    return name
    raise RuntimeError("No se encontró carpeta de borradores")


def _limpiar_fotos(numeros_carga: list[str], fotos: list[Path]) -> int:
    """Borra archivos de disco y filas DB de fotos ya adjuntadas al correo."""
    borrados = 0
    for p in fotos:
        try:
            p.unlink()
            borrados += 1
        except Exception as e:
            print(f"  ! No se pudo borrar {p}: {e}")
    eliminar_fotos_de_cargas(numeros_carga)
    print(f"  Fotos eliminadas del disco: {borrados}/{len(fotos)}")
    return borrados


def _save_as_draft(msg: EmailMessage) -> str:
    """Guarda el mensaje como borrador via IMAP APPEND. Devuelve nombre del folder."""
    if "Date" not in msg:
        msg["Date"] = formatdate(localtime=True)

    with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT) as imap:
        imap.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        folder = _find_drafts_folder(imap)
        date_str = imaplib.Time2Internaldate(time.time())
        result = imap.append(f'"{folder}"', "\\Draft", date_str, msg.as_bytes())
        if result[0] != "OK":
            raise RuntimeError(f"IMAP APPEND falló: {result}")
    return folder


def main(dry_run: bool = False, mode: str = "draft") -> dict:
    """
    mode: "draft" (crea borrador IMAP), "send" (envía SMTP), "dry" (preview).
    El parámetro dry_run=True fuerza mode="dry" (compat).
    """
    if dry_run:
        mode = "dry"
    if mode not in ("draft", "send", "dry"):
        raise ValueError(f"mode inválido: {mode}")

    if not OUTLOOK_EMAIL or not OUTLOOK_PASSWORD:
        sys.exit("ERROR: OUTLOOK_EMAIL u OUTLOOK_PASSWORD no definidos en .env")
    if not DESTINATARIOS:
        sys.exit("ERROR: DESTINATARIOS_DANOS no definido en .env")

    cargas_data, fotos = _gather_data()
    if not cargas_data:
        print("No hay cargas finalizadas pendientes de envío.")
        return {"enviadas": 0, "fotos": 0, "destinatarios": 0, "mode": mode}

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

    base_result = {
        "enviadas": len(cargas_data),
        "fotos": n_fotos,
        "destinatarios": len(DESTINATARIOS),
        "mode": mode,
    }

    if mode == "dry":
        print("[DRY-RUN] No se envió ni guardó nada.")
        return {**base_result, "dry_run": True}

    if mode == "draft":
        print(f"Creando borrador en {IMAP_SERVER}:{IMAP_PORT}...")
        folder = _save_as_draft(msg)
        numeros = [c["numero_carga"] for c in cargas_data]
        marcar_cargas_enviadas(numeros)
        _limpiar_fotos(numeros, fotos)
        print(f"✓ Borrador creado en carpeta '{folder}'. Cargas marcadas: {numeros}")
        return {**base_result, "folder": folder}

    # mode == "send"
    print(f"Enviando vía {SMTP_SERVER}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        smtp.send_message(msg)
    numeros = [c["numero_carga"] for c in cargas_data]
    marcar_cargas_enviadas(numeros)
    _limpiar_fotos(numeros, fotos)
    print(f"✓ Correo enviado. Cargas marcadas como enviadas: {numeros}")
    return base_result


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        main(mode="dry")
    elif "--send" in sys.argv:
        main(mode="send")
    else:
        main(mode="draft")
