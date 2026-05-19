"""Sincroniza cargas desde Outlook 365 vía IMAP (funciona en Render/Linux).

A diferencia de sync_cargas_outlook.py (Windows COM), este script habla IMAP
directo con outlook.office365.com:993, por lo que corre en cualquier servidor.

Credenciales:
    OUTLOOK_EMAIL    — cuenta Outlook 365
    OUTLOOK_PASSWORD — contraseña. Si la cuenta tiene MFA, hay que generar un
                       App Password en https://account.microsoft.com/security
                       y usar ese valor aquí.

Variables opcionales:
    IMAP_FOLDER  (default: "EasyGo") — carpeta donde caen los correos
    IMAP_SERVER  (default: "outlook.office365.com")
    IMAP_PORT    (default: 993)
    DIAS_VENTANA (default: 7) — sólo procesa correos recientes

Uso:
    python tools/sync_cargas_imap.py
"""

from __future__ import annotations

import email
import imaplib
import os
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = PROJECT_ROOT.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PARENT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from db import (  # noqa: E402
    email_ya_procesado,
    init_db,
    marcar_email_procesado,
)
from sync_cargas_outlook import (  # noqa: E402
    SUBJECT_REGEX,
    TMP_DIR,
    _ingestar_df,
    _read_dataframe,
)

IMAP_SERVER = os.getenv("IMAP_SERVER", "outlook.office365.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "EasyGo")
DIAS_VENTANA = int(os.getenv("DIAS_VENTANA", "7"))

OUTLOOK_EMAIL = os.getenv("OUTLOOK_EMAIL", "")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_PASSWORD", "")

FOLDER_CANDIDATES = (
    IMAP_FOLDER,
    f"Inbox/{IMAP_FOLDER}",
    f"INBOX/{IMAP_FOLDER}",
    f"Bandeja de entrada/{IMAP_FOLDER}",
)


def _connect() -> imaplib.IMAP4_SSL:
    if not OUTLOOK_EMAIL or not OUTLOOK_PASSWORD:
        sys.exit(
            "ERROR: OUTLOOK_EMAIL u OUTLOOK_PASSWORD no están definidos.\n"
            "Configúralos en .env (local) o en Render → Environment."
        )
    try:
        imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    except OSError as e:
        sys.exit(f"ERROR: no se pudo conectar a {IMAP_SERVER}:{IMAP_PORT}: {e}")
    try:
        imap.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
    except imaplib.IMAP4.error as e:
        sys.exit(
            f"ERROR: LOGIN IMAP falló para {OUTLOOK_EMAIL}: {e}\n"
            "Si la cuenta tiene MFA, generá un App Password en "
            "account.microsoft.com/security y reemplazá OUTLOOK_PASSWORD."
        )
    return imap


def _select_folder(imap: imaplib.IMAP4_SSL) -> str:
    """Intenta SELECT en los candidatos. Retorna el nombre que funcionó."""
    last_err = None
    for cand in FOLDER_CANDIDATES:
        try:
            typ, _ = imap.select(f'"{cand}"', readonly=True)
            if typ == "OK":
                print(f"Carpeta seleccionada: {cand}")
                return cand
        except imaplib.IMAP4.error as e:
            last_err = e
    typ, data = imap.list()
    disponibles = []
    if typ == "OK":
        for raw in data or []:
            if isinstance(raw, bytes):
                disponibles.append(raw.decode("utf-8", errors="replace"))
    sys.exit(
        f"ERROR: no se encontró la carpeta '{IMAP_FOLDER}'. "
        f"Intentados: {FOLDER_CANDIDATES}. Último error: {last_err}.\n"
        f"Carpetas disponibles:\n  " + "\n  ".join(disponibles[:40])
    )


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _parse_date(raw: str | None):
    if not raw:
        return datetime.today().date()
    try:
        return parsedate_to_datetime(raw).date()
    except Exception:
        return datetime.today().date()


def _safe_filename(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_").replace("\0", "")
    return name[:200] or "adjunto.bin"


def _extract_attachment(msg: email.message.Message) -> Path | None:
    """Guarda el primer adjunto Excel/CSV del mensaje. Retorna la ruta o None."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = (part.get("Content-Disposition") or "").lower()
        filename = _decode_header(part.get_filename() or "")
        if not filename:
            continue
        if "attachment" not in disp and "inline" not in disp:
            # algunos correos no traen disposition; deducir por extensión
            pass
        if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        dest = TMP_DIR / _safe_filename(filename)
        dest.write_bytes(payload)
        return dest
    return None


def main() -> dict:
    init_db()
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Conectando a {IMAP_SERVER}:{IMAP_PORT} como {OUTLOOK_EMAIL}...")
    imap = _connect()
    try:
        _select_folder(imap)

        since = (datetime.today() - timedelta(days=DIAS_VENTANA - 1)).strftime(
            "%d-%b-%Y"
        )
        typ, data = imap.search(None, f'(SINCE "{since}")')
        if typ != "OK":
            sys.exit(f"ERROR: IMAP SEARCH falló: {typ} {data}")

        uids = (data[0] or b"").split()
        print(f"Mensajes en ventana de {DIAS_VENTANA} día(s): {len(uids)}")

        total_cargas = 0
        total_items = 0
        procesados = 0

        for uid in reversed(uids):
            typ, hdr_data = imap.fetch(
                uid,
                "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT DATE)])",
            )
            if typ != "OK" or not hdr_data:
                continue
            hdr_bytes = b""
            for chunk in hdr_data:
                if isinstance(chunk, tuple) and len(chunk) >= 2:
                    hdr_bytes = chunk[1]
                    break
            hdr_msg = email.message_from_bytes(hdr_bytes)
            message_id = (hdr_msg.get("Message-ID") or "").strip()
            subject = _decode_header(hdr_msg.get("Subject"))
            date_raw = hdr_msg.get("Date")

            entry_id = message_id or f"{uid.decode()}|{date_raw}|{subject}"

            if email_ya_procesado(entry_id):
                continue

            if not SUBJECT_REGEX.search(subject or ""):
                marcar_email_procesado(entry_id)
                continue

            print(f"\nProcesando: {subject!r}")

            typ, full_data = imap.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK" or not full_data:
                print("  ! No se pudo fetch del cuerpo")
                continue
            full_bytes = b""
            for chunk in full_data:
                if isinstance(chunk, tuple) and len(chunk) >= 2:
                    full_bytes = chunk[1]
                    break
            msg = email.message_from_bytes(full_bytes)

            path = _extract_attachment(msg)
            if not path:
                print("  ! Sin adjunto Excel/CSV — se omite")
                marcar_email_procesado(entry_id)
                continue

            try:
                df = _read_dataframe(path)
            except Exception as e:
                print(f"  ! Error leyendo {path.name}: {e}")
                continue

            fecha_correo = _parse_date(date_raw)
            cargas, items_n = _ingestar_df(df, fecha_correo)
            marcar_email_procesado(entry_id)
            if cargas > 0 or items_n > 0:
                total_cargas += cargas
                total_items += items_n
                procesados += 1
                print(f"  OK {cargas} carga(s), {items_n} item(s) (fecha={fecha_correo})")

        summary = {
            "correos_procesados": procesados,
            "cargas_nuevas": total_cargas,
            "items_nuevos": total_items,
        }
        print(f"\nResumen: {summary}")
        return summary
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
