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
from zoneinfo import ZoneInfo

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
from ingest_archivo import ingestar_archivo  # noqa: E402

FOLDER_NAME = os.getenv("OUTLOOK_FOLDER", "WMS")
TMP_DIR = PROJECT_ROOT / ".tmp" / "correos_descargados"
DIAS_VENTANA = int(os.getenv("DIAS_VENTANA", "7"))
MAX_SCAN = int(os.getenv("MAX_SCAN_CORREOS", "500"))

SUBJECT_REGEX = re.compile(
    r"env[ií]o de gu[ií]as de despachos|easy\s*go|detalle.*carga",
    re.IGNORECASE,
)


class OutlookNoDisponible(RuntimeError):
    """Outlook Desktop no está disponible (no instalado/abierto)."""


def _get_outlook():
    try:
        import win32com.client
        return win32com.client.Dispatch("Outlook.Application")
    except Exception as e:
        raise OutlookNoDisponible(
            "No se pudo conectar con Outlook Desktop. "
            "Asegurate de que Outlook esté instalado y abierto. "
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


def _correos_de_fecha(folder, target) -> list:
    """Correos de `target` con asunto válido y adjuntos, del MÁS VIEJO al MÁS NUEVO.

    Única fuente de "qué correos son de este día": la usan main() e iter_adjuntos_fecha()
    para no elegir cada una por su cuenta.

    No confía en el orden en que Outlook entrega la colección ni corta con `break` al
    primer correo de otra fecha: recorre una ventana fija y ordena por ReceivedTime.
    Confiar en el orden es lo que rompió el 2026-08-07 — se ingirió el correo de las
    11:31 (3 cargas) en vez del último (5). Los correos WMS son ACUMULATIVOS, así que
    leer uno viejo no da error: da menos cargas, en silencio.

    ponytail: ventana fija de MAX_SCAN mensajes (~16 días a 30 correos/día) en vez de
    Items.Restrict(), cuyo filtro de fechas depende del formato regional de Windows.
    Si hay que mirar más atrás, subir MAX_SCAN_CORREOS.
    """
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)  # solo para que lo reciente caiga en la ventana
    except Exception:
        pass

    encontrados = []
    for i in range(min(items.Count, MAX_SCAN)):
        try:
            msg = items.Item(i + 1)
            if _recv_date(msg) != target:
                continue
            if not SUBJECT_REGEX.search(msg.Subject or ""):
                continue
            if msg.Attachments.Count == 0:
                continue
            encontrados.append((msg.ReceivedTime, msg))
        except Exception:
            continue

    encontrados.sort(key=lambda par: par[0])
    return [msg for _, msg in encontrados]


def _iter_attachments(msg):
    """Genera (file_bytes, filename) por CADA adjunto válido (Excel/CSV/ZIP) del correo.

    Recorre TODOS los adjuntos: un correo puede traer varias cargas como adjuntos
    separados, y quedarse con el primero pierde las demás en silencio.
    """
    import zipfile, io
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(msg.Attachments.Count):
        att = msg.Attachments.Item(i + 1)
        filename = att.FileName or ""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in ("csv", "xlsx", "xls", "zip"):
            continue
        tmp_path = TMP_DIR / filename
        att.SaveAsFile(str(tmp_path.resolve()))
        file_bytes = tmp_path.read_bytes()
        if ext == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                    inner = [n for n in z.namelist()
                             if n.lower().endswith((".xlsx", ".xls", ".csv"))
                             and not n.startswith("__MACOSX")]
                    for n in inner:
                        yield z.read(n), n.rsplit("/", 1)[-1]
            except Exception as e:
                print(f"  ! Error al descomprimir ZIP {att.FileName}: {e}")
            continue
        yield file_bytes, filename


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
    """Fecha del correo en HORA DE CHILE (es la que se guarda como fecha_correo).

    Outlook entrega ReceivedTime en UTC, 4 horas adelante: sin convertir, todo correo
    que llegue desde las 20:00 CL queda archivado al día siguiente. El síntoma sería
    cargas que no aparecen en su día y que, a diferencia del bug del 2026-08-07,
    re-correr el sync NO recupera (para el código ese correo es de otro día, y
    upsert_carga no reubica: ON CONFLICT(numero_carga) DO NOTHING con PK global).

    ponytail: hoy WMS corta a las 19:31 CL — 28 min de margen fue lo más ajustado en
    95 días medidos. Si empiezan a mandar pasadas las 20:00 CL esto deja de ser seguro
    de más y pasa a ser lo único que evita el desfase.
    """
    try:
        rt = msg.ReceivedTime
        if rt.tzinfo is not None:  # naive → ya viene en hora local, convertir restaría de más
            rt = rt.astimezone(ZoneInfo("America/Santiago"))
        return rt.date()
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


def main(fecha=None) -> dict:
    """Sincroniza cargas desde Outlook.

    fecha: date | None — fecha objetivo a sincronizar.
      - None → HOY.
      - Para WMS: procesa SOLO el correo más reciente de esa fecha
        (WMS reenvía la misma data acumulada del día, basta uno).
    """
    from datetime import date as _date

    init_db()
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    target = fecha or _date.today()
    es_wms = FOLDER_NAME == "WMS"
    print(f"Fecha objetivo: {target.isoformat()}")

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

    correos = _correos_de_fecha(folder, target)
    print(f"Correos de la fecha con adjuntos: {len(correos)}")
    if es_wms:
        # Acumulativos: arrancar por el MÁS NUEVO y cortar en el primero que rinda.
        correos = list(reversed(correos))

    total_cargas = 0
    total_items = 0
    procesados = 0

    for msg in correos:
        entry_id = _get_entry_id(msg)
        if not es_wms and email_ya_procesado(entry_id):
            continue

        print(f"\nProcesando: {(msg.Subject or '')!r} ({msg.ReceivedTime})")

        fecha_correo = _recv_date(msg)
        cargas = items_n = 0
        for file_bytes, filename in _iter_attachments(msg):
            try:
                res = ingestar_archivo(file_bytes, filename, fecha_correo)
            except Exception as e:
                print(f"  ! Error ingiriendo {filename}: {e}")
                continue
            if res.get("errores"):
                print(f"  ! Errores durante ingesta: {res['errores'][:2]}")
            cargas += res["cargas"]
            items_n += res["items"]

        if not es_wms:
            marcar_email_procesado(entry_id)
        if cargas > 0 or items_n > 0:
            total_cargas += cargas
            total_items += items_n
            procesados += 1
            print(f"  OK {cargas} carga(s), {items_n} item(s) (fecha={fecha_correo})")
        else:
            print("  ! Sin adjunto Excel/CSV/ZIP válido — se omite")

        # Para WMS: el correo más reciente de la fecha ya tiene toda la data → parar
        if es_wms and (cargas > 0 or items_n > 0):
            break

    summary = {
        "correos_procesados": procesados,
        "cargas_nuevas": total_cargas,
        "items_nuevos": total_items,
    }
    print(f"\nResumen: {summary}")
    return summary


def iter_adjuntos_fecha(fecha=None):
    """Genera (file_bytes, filename, fecha_correo) de los adjuntos del ÚLTIMO correo
    WMS de la fecha objetivo.

    Usa el MISMO selector de correos que main() (_correos_de_fecha), así ambos no pueden
    elegir correos distintos. Como los correos WMS son acumulativos (el último del día ya
    trae todas las cargas), para `es_wms` arranca por el más nuevo y corta en el primero
    con adjunto(s) válido(s).

    Lanza OutlookNoDisponible si Outlook no está accesible.
    """
    from datetime import date as _date

    target = fecha or _date.today()
    es_wms = FOLDER_NAME == "WMS"

    outlook = _get_outlook()
    folder = _find_folder(outlook, FOLDER_NAME)
    if folder is None:
        raise OutlookNoDisponible(f"carpeta '{FOLDER_NAME}' no encontrada en Outlook.")

    correos = _correos_de_fecha(folder, target)
    if es_wms:
        correos = list(reversed(correos))  # del más nuevo al más viejo

    for msg in correos:
        fecha_correo = _recv_date(msg)
        rindio = False
        for file_bytes, filename in _iter_attachments(msg):
            rindio = True
            yield file_bytes, filename, fecha_correo
        # Correos WMS acumulativos: el más reciente del día ya trae todo. Tomamos
        # sus adjuntos y cortamos (igual que main). Si este correo no rindió adjuntos
        # válidos, seguimos al siguiente (no cortar en vacío).
        if es_wms and rindio:
            break


if __name__ == "__main__":
    main()
