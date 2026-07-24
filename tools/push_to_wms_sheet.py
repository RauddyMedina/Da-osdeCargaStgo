"""
push_to_wms_sheet.py
====================
Orquestador (lado "Sync Cargas") que sube las cargas de una fecha al Google Sheet
'BASE DE DATOS WMS' y actualiza la pestaña "Que va quedando Easy".

Flujo:
  1. Baja de Outlook los adjuntos de la fecha (reusa sync_cargas_outlook.iter_adjuntos_fecha).
  2. Los guarda en .tmp/correos_descargados/.
  3. Llama por SUBPROCESO a BaseDatosWMS/tools/integration_push.py con las rutas.
     (subproceso = aísla el paquete `tools` de cada proyecto, que se llaman igual.)

Diseñado para invocarse desde sync_and_push.py (best-effort, no rompe Render) o solo:
    python tools/push_to_wms_sheet.py --fecha 22-05-2026
    python tools/push_to_wms_sheet.py --fecha 22-05-2026 --dry-run
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# Salida siempre UTF-8 tolerante (evita UnicodeEncodeError bajo pythonw/cp1252).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = PROJECT_ROOT.parent
BASEDATOSWMS_ROOT = PARENT_ROOT / "BaseDatosWMS"
INTEGRATION_PUSH = BASEDATOSWMS_ROOT / "tools" / "integration_push.py"
EASYGO_SCRIPT = PARENT_ROOT / "tools" / "easygo_opl_to_sheet.py"
TMP_DIR = PROJECT_ROOT / ".tmp" / "correos_descargados"

sys.path.insert(0, str(PROJECT_ROOT / "tools"))


def _descargar_adjuntos(fecha) -> list[Path]:
    """Baja los adjuntos de la fecha y devuelve sus rutas en disco."""
    from sync_cargas_outlook import OutlookNoDisponible, iter_adjuntos_fecha

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []
    try:
        for file_bytes, filename, _fecha_correo in iter_adjuntos_fecha(fecha):
            destino = TMP_DIR / filename
            destino.write_bytes(file_bytes)
            rutas.append(destino)
            print(f"   adjunto: {filename}")
    except OutlookNoDisponible as e:
        print(f"!! Outlook no disponible — se omite push al sheet: {e}")
        return []
    return rutas


def _env() -> dict:
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


# CREATE_NO_WINDOW: corre python.exe (consola) sin abrir una ventana visible.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _console_python() -> str:
    """Devuelve un Python de CONSOLA (python.exe), no pythonw.exe.

    El panel se lanza con pythonw.exe; si los subprocesos hijos heredan pythonw,
    el append real a Google Sheets de easygo falla en silencio (OPL no sube).
    python.exe está probado para esa operación, así que forzamos consola.
    """
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if Path(cand).exists():
            return cand
    return exe


def _run_opl(target, dry_run: bool) -> tuple[int, int, list]:
    """Corre el push OPL (carpeta EasyGo → 'BASE DATOS OPL') para la fecha.

    Devuelve (returncode, filas, subordenes). Best-effort: ante error loguea y sigue.
    """
    if not EASYGO_SCRIPT.exists():
        print(f"!! No se encontró {EASYGO_SCRIPT} — se omite OPL.")
        return 1, 0, []

    cmd = [_console_python(), str(EASYGO_SCRIPT), "--fecha", target.strftime("%Y-%m-%d")]
    if dry_run:
        cmd.append("--dry-run")

    print(f">> Push OPL (EasyGo -> 'BASE DATOS OPL') para fecha {target.isoformat()}...")
    try:
        proc = subprocess.run(
            cmd, cwd=str(PARENT_ROOT), env=_env(),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except Exception as e:
        print(f"!! No se pudo ejecutar easygo_opl: {e}")
        return 1, 0, []

    if proc.stdout:
        print(proc.stdout, end="")
    if proc.returncode != 0:
        print(f"!! easygo_opl devolvió código {proc.returncode}")
        if proc.stderr:
            print(proc.stderr, end="")

    filas, subordenes = 0, []
    summary_seen = False
    for line in (proc.stdout or "").splitlines():
        if line.startswith("##OPL_SUMMARY##"):
            summary_seen = True
            try:
                data = json.loads(line[len("##OPL_SUMMARY##"):].strip())
                filas = int(data.get("filas", 0))
                subordenes = list(data.get("subordenes", []) or [])
            except Exception:
                pass

    if proc.returncode != 0 or not summary_seen:
        print(f"!! OPL NO se completó (rc={proc.returncode}, resumen={'si' if summary_seen else 'NO'}). "
              f"'BASE DATOS OPL' y los subordenes en Easy podrían no haberse actualizado.")
    return proc.returncode, filas, subordenes


def _emit_combined(cargas, entregas, filas, opl_filas, opl_subordenes, dry_run,
                   opl_error=False, wms_error=False) -> None:
    """Imprime el ##SUMMARY## combinado (último → el que toma el panel) con métricas OPL."""
    print("##SUMMARY## " + json.dumps({
        "cargas": cargas, "entregas": entregas, "filas": filas,
        "opl_filas": opl_filas, "opl_subordenes": opl_subordenes,
        "opl_error": bool(opl_error), "wms_error": bool(wms_error),
        "dry_run": bool(dry_run),
    }))


def push_y_easy(fecha=None, dry_run: bool = False,
                do_opl: bool = True, do_wms: bool = True) -> int:
    """Sube WMS y/o OPL de la fecha a sus bases y alimenta 'Que va quedando Easy'.

    - WMS (carpeta "WMS")  → 'BASE DE DATOS WMS'  + entregas a Easy.
    - OPL (carpeta "EasyGo") → 'BASE DATOS OPL'   + subordenes (col B) a Easy.
    La reconciliación de Easy (append→dedup→fórmulas) la hace integration_push una sola vez.

    do_opl / do_wms permiten correr SOLO uno:
    - Panel OPL (botón aparte): do_opl=True,  do_wms=False  (--opl-only).
    - Panel WMS / Render:       do_opl=False, do_wms=True   (--wms-only).

    Devuelve un returncode (0 = OK). No lanza: best-effort para no romper el flujo Render.
    """
    target = fecha or date.today()
    que = "WMS + OPL" if (do_opl and do_wms) else ("OPL" if do_opl else "WMS")
    print(f">> Push a Google Sheets ({que}) para fecha {target.isoformat()}...")

    if not INTEGRATION_PUSH.exists():
        print(f"!! No se encontró {INTEGRATION_PUSH} — ¿está instalado BaseDatosWMS?")
        return 1

    # 1) OPL primero (si toca): sube a 'BASE DATOS OPL' y devuelve los subordenes para Easy.
    if do_opl:
        opl_rc, opl_filas, subordenes = _run_opl(target, dry_run)
    else:
        opl_rc, opl_filas, subordenes = 0, 0, []

    # 2) WMS (si toca): descargar adjuntos de la fecha.
    rutas = _descargar_adjuntos(target) if do_wms else []

    # 3) Subordenes OPL → JSON temporal para pasarlos a integration_push (cadena Easy única).
    easy_extra_path = None
    if subordenes:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        easy_extra_path = TMP_DIR / "opl_subordenes.json"
        easy_extra_path.write_text(json.dumps(subordenes), encoding="utf-8")

    if not rutas and not subordenes:
        print(">> Sin adjuntos WMS ni subordenes OPL para la fecha — nada que subir.")
        _emit_combined(0, 0, 0, opl_filas, 0, dry_run, opl_error=(opl_rc != 0))
        return opl_rc

    # 4) integration_push: WMS → 'BASE DE DATOS WMS' + (entregas WMS + subordenes OPL) → Easy.
    cmd = [_console_python(), str(INTEGRATION_PUSH), "--fecha", target.strftime("%d-%m-%Y")]
    if rutas:
        cmd += ["--files", *[str(r) for r in rutas]]
    if easy_extra_path:
        cmd += ["--easy-extra", str(easy_extra_path)]
    if dry_run:
        cmd.append("--dry-run")

    print(f">> Ejecutando integration_push ({len(rutas)} archivo(s) WMS"
          + (f", +{len(subordenes)} subordenes OPL" if subordenes else "") + ")...")
    proc = subprocess.run(
        cmd, cwd=str(BASEDATOSWMS_ROOT), env=_env(),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.returncode != 0:
        print(f"!! integration_push devolvió código {proc.returncode}")
        if proc.stderr:
            print(proc.stderr, end="")

    # 5) Parsear el ##SUMMARY## WMS y emitir el combinado (con métricas OPL) al final.
    wms = {"cargas": 0, "entregas": 0, "filas": 0}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("##SUMMARY##"):
            try:
                wms = json.loads(line[len("##SUMMARY##"):].strip())
            except Exception:
                pass
    _emit_combined(wms.get("cargas", 0), wms.get("entregas", 0), wms.get("filas", 0),
                   opl_filas, len(subordenes), dry_run,
                   opl_error=(opl_rc != 0), wms_error=(proc.returncode != 0))

    return proc.returncode or opl_rc


def _parse_fecha(args) -> date | None:
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
    sys.exit(f"ERROR: fecha inválida '{val}'. Usa formato DD-MM-YYYY (ej: 22-05-2026).")


def main() -> None:
    args = sys.argv[1:]
    fecha = _parse_fecha(args)
    dry_run = "--dry-run" in args
    opl_only = "--opl-only" in args
    wms_only = "--wms-only" in args
    # Default: ambos. --opl-only / --wms-only acotan el flujo.
    do_opl = not wms_only
    do_wms = not opl_only
    push_y_easy(fecha=fecha, dry_run=dry_run, do_opl=do_opl, do_wms=do_wms)


if __name__ == "__main__":
    main()
