"""Append una carga finalizada (con todos sus daños) al Google Sheet histórico.

Se llama desde el Streamlit cuando una carga pasa a estado 'finalizada'.

Crea/escribe en la pestaña `HISTORICO_DANOS_ANDEN` (configurable vía .env).
Columnas: fecha_finalizacion, numero_carga, cd, anden, entrega, tipo_dano,
          declarado_por, finalizada_por, sin_danos.

Si la carga es `sin_danos=1`, se appendea UNA fila con tipo_dano='SIN DAÑOS'.

Uso:
    python tools/append_carga_to_sheet.py <numero_carga>
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = PROJECT_ROOT.parent
PARENT_TOOLS = PARENT_ROOT / "tools"

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PARENT_ROOT / ".env")

sys.path.insert(0, str(PARENT_TOOLS))
from auth_google import get_sheets_service  # type: ignore  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from db import (  # noqa: E402
    listar_danos_de_carga,
    obtener_carga,
)

SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB_HISTORICO", "HISTORICO_DANOS_ANDEN")

HEADERS = [
    "fecha_finalizacion",
    "numero_carga",
    "cd",
    "anden",
    "entrega",
    "tipo_dano",
    "declarado_por",
    "finalizada_por",
    "sin_danos",
]


def _ensure_headers(service, sheet_id: str, tab: str) -> None:
    existing = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"'{tab}'!A1:I1")
        .execute()
    )
    if not existing.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()


def _build_rows(numero_carga: str) -> list[list]:
    carga = obtener_carga(numero_carga)
    if not carga:
        raise ValueError(f"Carga no encontrada: {numero_carga}")

    fecha_fin = carga["finalizada_at"] or datetime.now().isoformat(timespec="seconds")
    cd = carga["cd"] or ""
    anden = carga["anden"] or ""
    finalizada_por = carga["finalizada_por"] or ""
    sin_danos = int(carga["sin_danos"] or 0)

    if sin_danos:
        return [[
            fecha_fin, numero_carga, cd, anden, "", "SIN DAÑOS",
            "", finalizada_por, 1,
        ]]

    danos = listar_danos_de_carga(numero_carga)
    if not danos:
        return []
    return [
        [
            fecha_fin, numero_carga, cd, anden, entrega, d["tipo_dano"],
            d["declarado_por"], finalizada_por, 0,
        ]
        for entrega in sorted(danos.keys())
        for d in danos[entrega]
    ]


def append_carga(numero_carga: str) -> int:
    if not SHEET_ID:
        print("WARNING: GOOGLE_SHEET_ID no definido — se omite append a Sheets")
        return 0

    rows = _build_rows(numero_carga)
    if not rows:
        print(f"Carga {numero_carga}: sin filas para appendear")
        return 0

    service = get_sheets_service()

    # Crear pestaña si no existe
    try:
        _ensure_headers(service, SHEET_ID, SHEET_TAB)
    except Exception:
        # Crear pestaña
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={
                "requests": [
                    {"addSheet": {"properties": {"title": SHEET_TAB}}}
                ]
            },
        ).execute()
        _ensure_headers(service, SHEET_ID, SHEET_TAB)

    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"'{SHEET_TAB}'",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    print(f"Carga {numero_carga}: {len(rows)} fila(s) appendeadas a '{SHEET_TAB}'")
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python tools/append_carga_to_sheet.py <numero_carga>")
    append_carga(sys.argv[1])
