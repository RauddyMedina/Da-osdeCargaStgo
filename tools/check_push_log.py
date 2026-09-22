"""Self-check del log a disco del panel PUSH WMS SHEET.

Corre:  python tools/check_push_log.py     (desde DeclaracionCargaDanosStg/)

Falla si: el log deja de escribirse, se pierde la linea ##SUMMARY## (la que NO se muestra
en la ventana pero es la que dice si el push fallo), la rotacion por tamano no archiva, o
un log inaccesible tumba la corrida en vez de degradar en silencio.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import push_panel  # noqa: E402

SEP = "=" * 72


def _panel():
    """Un PushPanel sin UI: solo los helpers de log."""
    p = object.__new__(push_panel.PushPanel)
    p.logf = None
    p._wms_error = False
    p._append = lambda *_a, **_k: None   # la ventana no existe en el check
    return p


def _corrida(p, lineas, dry_run=False, code=0):
    p._log_abrir(["python", "sync_and_push.py"], dry_run, "31-08-2026")
    for linea in lineas:
        p._log(linea)
    p._log_cerrar(code)


def main() -> None:
    original = push_panel.LOG_PATH
    tmp = Path(tempfile.mkdtemp(prefix="check_push_log_"))
    try:
        # 1. Una corrida deja header, lineas y cierre en disco.
        push_panel.LOG_PATH = tmp / "logs" / "push_wms.log"
        p = _panel()
        _corrida(p, [">> Cargas nuevas: 0", '##SUMMARY## {"wms_error": true}'], code=1)
        txt = push_panel.LOG_PATH.read_text(encoding="utf-8")
        assert "SUBIDA REAL" in txt and "31-08-2026" in txt, "falta el header de la corrida"
        assert ">> Cargas nuevas: 0" in txt, "no se escribieron las lineas del proceso"
        assert "##SUMMARY##" in txt, "el ##SUMMARY## debe quedar aunque se oculte en la UI"
        assert "rc=1" in txt, "falta el cierre con el codigo de salida"
        assert p.logf is None, "el archivo quedo abierto tras _log_cerrar"

        # 2. Dos corridas se acumulan (append, no se pisan).
        _corrida(p, [">> segunda corrida"], dry_run=True)
        txt = push_panel.LOG_PATH.read_text(encoding="utf-8")
        assert txt.count(SEP) == 4, f"cada corrida escribe 2 separadores, vi {txt.count(SEP)}"
        assert "VISTA PREVIA" in txt and ">> segunda corrida" in txt

        # 3. Rotacion por tamano: el log viejo se archiva y se empieza uno nuevo.
        push_panel.LOG_PATH.write_text("x" * (push_panel.LOG_MAX + 1), encoding="utf-8")
        _corrida(p, [">> tras rotar"])
        archivado = push_panel.LOG_PATH.with_name("push_wms.1.log")
        assert archivado.exists(), "no se archivo el log viejo"
        assert archivado.stat().st_size > push_panel.LOG_MAX, "se archivo el archivo equivocado"
        nuevo = push_panel.LOG_PATH.read_text(encoding="utf-8")
        assert ">> tras rotar" in nuevo and "xxx" not in nuevo, "el log nuevo no arranco limpio"

        # 4. Log inaccesible: degrada en silencio, NO tumba el push.
        bloqueado = tmp / "soy_un_archivo"
        bloqueado.write_text("no soy carpeta", encoding="utf-8")
        push_panel.LOG_PATH = bloqueado / "logs" / "push_wms.log"
        p2 = _panel()
        _corrida(p2, [">> el push igual corre"])   # no debe lanzar
        assert p2.logf is None
    finally:
        push_panel.LOG_PATH = original

    # 5. El cableado sigue puesto: sin estas 3 llamadas los helpers nunca corren
    #    y el check de arriba pasaria igual (verde enganoso).
    src = (_HERE / "push_panel.py").read_text(encoding="utf-8")
    for llamada in ("self._log_abrir(cmd, dry_run, f)",
                    "self._log(payload)",
                    "self._log_cerrar(code)"):
        assert llamada in src, f"push_panel.py perdio la llamada: {llamada}"

    print("OK check_push_log: log en disco, ##SUMMARY## incluido, rotacion y "
          "degradacion silenciosa.")


if __name__ == "__main__":
    main()
