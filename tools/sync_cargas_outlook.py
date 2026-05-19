"""Sincroniza cargas desde la carpeta EasyGo en Outlook Desktop (via COM).

No requiere Azure AD ni MS_CLIENT_ID/MS_TENANT_ID.
Requiere que Outlook Desktop esté instalado y abierto con la cuenta configurada.

Para cada correo nuevo:
  1. Filtra por asunto que matchee con cargas Easy
  2. Descarga el adjunto Excel/CSV
  3. Parsea con pandas y carga en SQLite (cargas + items)
  4. Marca el EntryID como procesado para no re-ingestar

Uso:
    python tools/sync_cargas_outlook.py
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
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
    upsert_carga,
    upsert_item,
)

FOLDER_NAME = os.getenv("OUTLOOK_FOLDER", "EasyGo")
TMP_DIR = PROJECT_ROOT / ".tmp" / "correos_descargados"
DIAS_VENTANA = int(os.getenv("DIAS_VENTANA", "7"))

SUBJECT_REGEX = re.compile(
    r"env[ií]o de gu[ií]as de despachos|easy\s*go|detalle\s*carga",
    re.IGNORECASE,
)


def _get_outlook():
    try:
        import win32com.client
        return win32com.client.Dispatch("Outlook.Application")
    except Exception as e:
        sys.exit(
            "ERROR: No se pudo conectar con Outlook Desktop.\n"
            "Asegurate de que Outlook esté instalado y abierto.\n"
            f"Detalle: {e}"
        )


def _find_folder(outlook, folder_name: str):
    mapi = outlook.GetNamespace("MAPI")

    def _search(folder):
        try:
            for sub in folder.Folders:
                if sub.Name.strip().lower() == folder_name.strip().lower():
                    return sub
                result = _search(sub)
                if result:
                    return result
        except Exception:
            pass
        return None

    for root in mapi.Folders:
        try:
            result = _search(root)
            if result:
                return result
        except Exception:
            continue
    return None


def _get_entry_id(msg) -> str:
    try:
        return msg.EntryID
    except Exception:
        return str(msg.ReceivedTime) + str(msg.Subject)


def _download_attachment(msg) -> Path | None:
    """Guarda el primer adjunto Excel/CSV del mensaje. Retorna la ruta o None."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(msg.Attachments.Count):
        att = msg.Attachments.Item(i + 1)
        filename = att.FileName or ""
        if filename.lower().endswith((".csv", ".xlsx", ".xls")):
            dest = TMP_DIR / filename
            att.SaveAsFile(str(dest.resolve()))
            return dest
    return None


def _read_dataframe(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        # El CSV de EasyGo usa ; como separador y encoding latin-1
        for sep in (";", ",", "\t"):
            for enc in ("latin-1", "utf-8", "cp1252"):
                try:
                    df = pd.read_csv(
                        path, sep=sep, dtype=str,
                        encoding=enc, on_bad_lines="skip",
                    )
                    if df.shape[1] >= 5:
                        return df
                except Exception:
                    continue
        raise ValueError(f"No se pudo leer el CSV: {path.name}")
    return pd.read_excel(path, dtype=str)


def _norm(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _clean_numero_carga(raw) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"^CARGA[:\s]*", "", str(raw).strip(), flags=re.IGNORECASE)
    return cleaned or None


def _parse_float(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _recv_date(msg) -> "datetime.date":
    try:
        rt = msg.ReceivedTime
        return datetime(rt.year, rt.month, rt.day).date()
    except Exception:
        return datetime.today().date()


def _ingestar_df(df: pd.DataFrame, fecha_correo) -> tuple[int, int]:
    df.columns = [c.strip().upper() for c in df.columns]

    requeridas = {"NUMERO CARGA", "ENTREGA"}
    faltantes = requeridas - set(df.columns)
    if faltantes:
        print(f"  ! Columnas faltantes: {sorted(faltantes)} - se omite el archivo")
        print(f"  ! Columnas presentes: {sorted(df.columns.tolist())}")
        return 0, 0

    cargas_vistas: set[str] = set()
    items_count = 0

    for _, row in df.iterrows():
        numero_carga = _clean_numero_carga(row.get("NUMERO CARGA"))
        entrega = _norm(row.get("ENTREGA"))
        if not numero_carga or not entrega:
            continue

        if numero_carga not in cargas_vistas:
            upsert_carga(
                numero_carga=numero_carga,
                fecha_correo=fecha_correo,
                cd=_norm(row.get("CD")),
                anden=_norm(row.get("ANDEN")),
            )
            cargas_vistas.add(numero_carga)

        upsert_item(
            numero_carga=numero_carga,
            entrega=entrega,
            producto=_norm(row.get("PRODUCTO")),
            descripcion=_norm(row.get("DESCRIPCION")),
            bultos=_parse_float(row.get("BULTOS")),
            unidades=_parse_float(row.get("UNIDADES")),
            nombre_cliente=_norm(row.get("NOMBRE")),
            comuna=_norm(row.get("COMUNA")),
            region=_norm(row.get("REGION")),
        )
        items_count += 1

    return len(cargas_vistas), items_count


def main() -> dict:
    init_db()
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print("Conectando con Outlook Desktop...")
    outlook = _get_outlook()

    print(f"Buscando carpeta '{FOLDER_NAME}'...")
    folder = _find_folder(outlook, FOLDER_NAME)
    if folder is None:
        sys.exit(
            f"ERROR: carpeta '{FOLDER_NAME}' no encontrada en Outlook.\n"
            "Verifica que el nombre coincida exactamente (mayúsculas/minúsculas)."
        )

    print(f"Carpeta encontrada: {folder.Name} ({folder.Items.Count} mensajes)")

    # Ordenar descendente para procesar los más recientes primero y cortar pronto
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass

    corte = datetime.today().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - __import__("datetime").timedelta(days=DIAS_VENTANA - 1)

    total_cargas = 0
    total_items = 0
    procesados = 0

    for i in range(items.Count):
        msg = items.Item(i + 1)
        try:
            recv_dt = datetime(
                msg.ReceivedTime.year,
                msg.ReceivedTime.month,
                msg.ReceivedTime.day,
            )
        except Exception:
            recv_dt = datetime.today()

        if recv_dt < corte:
            break  # más viejos que la ventana → parar

        entry_id = _get_entry_id(msg)
        if email_ya_procesado(entry_id):
            continue

        subject = msg.Subject or ""
        if not SUBJECT_REGEX.search(subject):
            marcar_email_procesado(entry_id)
            continue

        print(f"\nProcesando: {subject!r}")

        if msg.Attachments.Count == 0:
            print("  ! Sin adjuntos — se omite")
            marcar_email_procesado(entry_id)
            continue

        path = _download_attachment(msg)
        if not path:
            print("  ! Sin adjunto Excel/CSV válido — se omite")
            marcar_email_procesado(entry_id)
            continue

        try:
            df = _read_dataframe(path)
        except Exception as e:
            print(f"  ! Error leyendo {path.name}: {e}")
            continue

        fecha_correo = _recv_date(msg)
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


if __name__ == "__main__":
    main()
