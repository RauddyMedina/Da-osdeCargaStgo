"""Sync Outlook local + push a Render. Pensado para Windows Task Scheduler.

Flujo:
  1. Corre sync_cargas_outlook.main() (Outlook COM) → actualiza DB local.
  2. Lee cargas+items recientes del DB local.
  3. POST a https://<app>.onrender.com/api/import con Bearer token.

Variables de entorno (en .env local):
  RENDER_UPLOAD_URL — https://<app>.onrender.com/api/import
  UPLOAD_TOKEN     — mismo token configurado en Render env vars
  DIAS_PUSH        — opcional, default 2 (ventana de días a empujar)

Uso:
  python tools/sync_and_push.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = PROJECT_ROOT.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PARENT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from sync_cargas_outlook import main as outlook_sync  # noqa: E402

RENDER_URL = os.getenv("RENDER_UPLOAD_URL", "")
UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "")
DIAS_PUSH = int(os.getenv("DIAS_PUSH", "2"))

LOCAL_DB = PROJECT_ROOT / "data" / "declaracion.db"


def _gather_payload(fecha=None) -> dict:
    """Lee cargas+items del DB local.

    fecha: date | None — si se da, filtra por esa fecha exacta;
           si no, usa los últimos DIAS_PUSH días.
    """
    if not LOCAL_DB.exists():
        return {"cargas": [], "items": []}
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    if fecha is not None:
        cargas = [
            dict(r)
            for r in conn.execute(
                "SELECT numero_carga, fecha_correo, cd, anden FROM cargas "
                "WHERE fecha_correo = ?",
                (fecha.isoformat(),),
            )
        ]
    else:
        desde = (date.today() - timedelta(days=DIAS_PUSH)).isoformat()
        cargas = [
            dict(r)
            for r in conn.execute(
                "SELECT numero_carga, fecha_correo, cd, anden FROM cargas "
                "WHERE fecha_correo >= ?",
                (desde,),
            )
        ]
    if not cargas:
        conn.close()
        return {"cargas": [], "items": []}
    nums = tuple(c["numero_carga"] for c in cargas)
    placeholders = ",".join("?" * len(nums))
    items = [
        dict(r)
        for r in conn.execute(
            f"SELECT numero_carga, entrega, producto, descripcion, bultos, "
            f"unidades, nombre_cliente, comuna, region FROM items "
            f"WHERE numero_carga IN ({placeholders})",
            nums,
        )
    ]
    conn.close()
    return {"cargas": cargas, "items": items}


def _parse_fecha(args) -> date | None:
    """Parsea --fecha DD-MM-YYYY de los argumentos. Vacío/ausente → None (HOY)."""
    val = None
    for i, a in enumerate(args):
        if a == "--fecha" and i + 1 < len(args):
            val = args[i + 1].strip()
            break
        if a.startswith("--fecha="):
            val = a.split("=", 1)[1].strip()
            break
    if not val:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    sys.exit(f"ERROR: fecha inválida '{val}'. Usa formato DD-MM-YYYY (ej: 01-06-2026).")


def main(fecha=None) -> dict:
    # 1) Sync local con Outlook Desktop COM
    print(">> Sync Outlook local...")
    try:
        outlook_sync(fecha=fecha)
    except SystemExit as e:
        print(f"!! Outlook sync abortó: {e}")
    except Exception as e:
        print(f"!! Error en Outlook sync: {e}")

    # 2) Validar config para push
    if not RENDER_URL or not UPLOAD_TOKEN:
        sys.exit(
            "ERROR: RENDER_UPLOAD_URL / UPLOAD_TOKEN no definidos en .env. "
            "Setealos y reintenta."
        )

    # 3) Empujar a Render
    payload = _gather_payload(fecha=fecha)
    print(
        f">> Empujando a {RENDER_URL}: "
        f"{len(payload['cargas'])} cargas, {len(payload['items'])} items"
    )
    if not payload["cargas"]:
        print(">> Nada que empujar.")
        return {"cargas": 0, "items": 0}

    r = requests.post(
        RENDER_URL,
        headers={
            "Authorization": f"Bearer {UPLOAD_TOKEN}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=60,
    )
    r.raise_for_status()
    resp = r.json()
    print(f">> Render OK: {resp}")
    return resp


if __name__ == "__main__":
    fecha_arg = _parse_fecha(sys.argv[1:])
    main(fecha=fecha_arg)
