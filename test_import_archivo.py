"""
Autocheck del endpoint /api/import-archivo (el que usa el panel de bases cuando se
sube el Excel del WMS a mano). Sin red: se llama al handler directo, sobre una base
SQLite de juguete.

    python test_import_archivo.py
"""

from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

PROY = Path(__file__).resolve().parent
# DATA_DIR antes de importar db: ahí se resuelve la ruta de la base. Sin esto el test
# escribiría en la base de verdad.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="danos_test_")
sys.path.insert(0, str(PROY / "tools"))
sys.path.insert(0, str(PROY / "app"))

from openpyxl import Workbook  # noqa: E402

from upload_endpoint import _handle_import_archivo  # noqa: E402

FECHA = date(2026, 10, 26)

CABECERA = ["Anden", "CD", "Nro Carga", "Entrega", "Fecha Entrega", "Tipo Orden",
            "Cartón", "Comuna", "Región", "Producto", "Descripcion", "Unid", "Bultos",
            "Nombre", "Direccion", "Telefono", "Correo", "Compl", "Cant"]


def _excel_del_wms(filas, con_metadata=True) -> bytes:
    """El adjunto del WMS: una fila de metadata arriba y recién después la cabecera."""
    wb = Workbook()
    ws = wb.active
    if con_metadata:
        ws.append([None, None, None, "TRANSPORTE", None, None, "2026-10-26 00:00:00"])
    ws.append(CABECERA)
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fila(carga, entrega, producto="1277320", anden="L42"):
    return [anden, "E599", carga, entrega, "2026-11-02", "DN", "CTN1", "CONCON",
            "V - Valparaíso", producto, "REFRIGERADOR", "1", "1", "DIEGO C",
            "SAN FERNANDO 46", "961-688998", "d@c.cl", "1", "1 Caja"]


def _subir(contenido: bytes, fecha=FECHA, filename="Download.xlsx") -> dict:
    return _handle_import_archivo({
        "filename": filename, "fecha": fecha.isoformat(),
        "contenido_b64": base64.b64encode(contenido).decode()})


def test_entra_el_adjunto_del_wms_con_sus_filas_de_metadata_arriba():
    """La cabecera real no es la primera fila: si no se busca, no entra nada."""
    r = _subir(_excel_del_wms([_fila("CARGA1000527134", "2919827138"),
                               _fila("CARGA1000527134", "2919827605")]))
    assert r["ok"] is True, r
    assert (r["cargas"], r["items"]) == (1, 2), r


def test_el_numero_de_carga_se_guarda_sin_el_prefijo():
    """En el WMS es CARGACL30047639 y en la app CL30047639: buscar el largo no encuentra."""
    from db import listar_cargas_por_fecha
    _subir(_excel_del_wms([_fila("CARGACL30047639", "2919598106", anden="Z43")]))
    codigos = [c["numero_carga"] for c in listar_cargas_por_fecha(FECHA)]
    assert "CL30047639" in codigos, codigos
    assert "CARGACL30047639" not in codigos


def test_la_carga_queda_en_la_fecha_que_se_pidio():
    """La pantalla filtra por fecha EXACTA: si cae en otro día, no se ve y 'faltó'."""
    from db import listar_cargas_por_fecha
    otro = date(2026, 10, 20)
    _subir(_excel_del_wms([_fila("CARGA1000111222", "2910000001")]), fecha=otro)
    assert "1000111222" in [c["numero_carga"] for c in listar_cargas_por_fecha(otro)]
    assert "1000111222" not in [c["numero_carga"] for c in listar_cargas_por_fecha(FECHA)]


def test_el_mismo_archivo_dos_veces_no_duplica():
    excel = _excel_del_wms([_fila("CARGA1000527777", "2919111111")])
    _subir(excel)
    r = _subir(excel)
    assert (r["cargas"], r["items"]) == (1, 1), r
    from db import listar_cargas_por_fecha
    repetidas = [c["numero_carga"] for c in listar_cargas_por_fecha(FECHA)
                 if c["numero_carga"] == "1000527777"]
    assert len(repetidas) == 1, repetidas


def test_el_archivo_equivocado_avisa_en_vez_de_quedar_mudo():
    """Sin las columnas obligatorias no hay nada que declarar: hay que decirlo."""
    wb = Workbook()
    wb.active.append(["Orden", "Cliente", "Dirección"])
    wb.active.append(["123", "Juan", "Calle 1"])
    buf = io.BytesIO()
    wb.save(buf)
    r = _subir(buf.getvalue())
    assert r["ok"] is False and r["cargas"] == 0
    assert r["errores"], "tiene que decir por qué no entró"


def test_tornado_tambien_publica_la_ruta_del_archivo():
    """Render corre el patch de Tornado, y ahí la ruta no estaba: 405.

    Por eso el panel de bases subía al sheet y Declaración de Daños no se enteraba —
    el 12-11-2026 fueron 5 cargas. Se revisa la ruta Y el orden: PathMatches(r"/api/import")
    no ancla el final, así que si va primero se come /api/import-archivo.
    """
    import streamlit.web.server.server as st_server

    import upload_endpoint as ue

    class _App:
        def __init__(self):
            self.wildcard_router = type("R", (), {"rules": [None]})()

    # El patch envuelve el _create_app que encuentre al instalarse: se le deja este
    # doble para no levantar el servidor de Streamlit de verdad.
    original, patched = st_server.Server._create_app, None
    st_server.Server._create_app = lambda self: _App()
    st_server.Server._upload_patched = False
    try:
        assert ue._install_tornado(), "no se pudo instalar el patch de Tornado"
        app = st_server.Server._create_app(object())
        rutas = [(r.matcher.regex.pattern, r.target.__name__)
                 for r in app.wildcard_router.rules
                 if r is not None and hasattr(r, "matcher")]
    finally:
        st_server.Server._create_app = original
        st_server.Server._upload_patched = False

    assert rutas, "el patch no agregó ninguna ruta"
    assert rutas[0][0].startswith("/api/import-archivo"), rutas
    assert rutas[0][1] == "_ImportArchivoHandler", rutas
    assert any(n == "_ImportHandler" for _, n in rutas), rutas


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for prueba in pruebas:
        prueba()
        print(f"  ok  {prueba.__name__}")
    print(f"\n{len(pruebas)} pruebas OK")
