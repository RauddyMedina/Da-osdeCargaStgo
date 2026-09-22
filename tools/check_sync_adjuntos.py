"""Check del sync de adjuntos WMS (regresión del 2026-08-07).

Ese día el sheet quedó con 5 cargas y la base de daños con 3, y esas 2 cargas no se
pudieron declarar. Los correos WMS son ACUMULATIVOS: leer el correo equivocado no da
error, da menos cargas en silencio. Este check cubre las tres mitades del arreglo, sin
Outlook y sin tocar la base real:

  1. _correos_de_fecha() elige el ÚLTIMO correo del día aunque la colección venga
     desordenada y con otras fechas entremedio (antes: Sort + break → correo viejo).
  2. _iter_attachments() devuelve TODOS los adjuntos del correo (antes: solo el primero).
  3. Ingerir los adjuntos del día deja las 5 cargas, y re-ingerir no cambia nada.

Corre:  python tools/check_sync_adjuntos.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

# Los dos adjuntos reales del 2026-08-07: el parcial que leyó la base y el completo
# que leyó el sheet.
FIXTURES = PROJECT_ROOT / ".tmp" / "correos_descargados"
PARCIAL = FIXTURES / "670240ec-0c2f-4be3-abbc-6f64f0c25675_Download.xlsx"   # 3 cargas
COMPLETO = FIXTURES / "670240ec-0c2f-4be3-abbc-6f64f0c25676_Download.xlsx"  # 5 cargas

CARGAS_ESPERADAS = {
    "1000523513", "1000523524", "CL00095493", "CL00095560", "CL00095561",
}
ENTREGAS_ESPERADAS = 124


class _FakeAttachment:
    """Imita win32com Attachment: .FileName y .SaveAsFile(ruta)."""

    def __init__(self, origen: Path):
        self._origen = origen
        self.FileName = origen.name

    def SaveAsFile(self, destino):
        Path(destino).write_bytes(self._origen.read_bytes())


class _FakeAttachments:
    def __init__(self, origenes):
        self._items = [_FakeAttachment(o) for o in origenes]

    @property
    def Count(self):
        return len(self._items)

    def Item(self, i):  # COM indexa desde 1
        return self._items[i - 1]


class _FakeMsg:
    def __init__(self, origenes, recibido=None, asunto="Detalle de Cargas Yañez N"):
        self.Attachments = _FakeAttachments(origenes)
        self.ReceivedTime = recibido
        self.Subject = asunto


class _FakeItems:
    """Imita Outlook Items: .Count, .Item(1-based) y un .Sort() que NO hace nada.

    Sort() inerte a propósito: el bug real fue confiar en que ordenara.
    """

    def __init__(self, msgs):
        self._msgs = msgs

    @property
    def Count(self):
        return len(self._msgs)

    def Item(self, i):
        return self._msgs[i - 1]

    def Sort(self, *_a, **_k):
        pass


class _FakeFolder:
    def __init__(self, msgs):
        self.Items = _FakeItems(msgs)


def check_elige_el_ultimo_correo():
    from sync_cargas_outlook import _correos_de_fecha

    target = date(2026, 8, 7)
    viejo = _FakeMsg([PARCIAL], datetime(2026, 8, 7, 11, 31))   # 3 cargas
    nuevo = _FakeMsg([COMPLETO], datetime(2026, 8, 7, 16, 31))  # 5 cargas
    otro_dia = _FakeMsg([COMPLETO], datetime(2026, 8, 6, 23, 59))
    ruido = _FakeMsg([COMPLETO], datetime(2026, 8, 7, 18, 0), asunto="Fuera de tema")
    sin_adj = _FakeMsg([], datetime(2026, 8, 7, 19, 0))

    # Orden hostil: el viejo primero y un correo de otra fecha antes que el nuevo.
    # Con el Sort+break de antes, esto devolvía el correo de las 11:31 (3 cargas).
    folder = _FakeFolder([viejo, otro_dia, ruido, sin_adj, nuevo])
    correos = _correos_de_fecha(folder, target)

    assert len(correos) == 2, f"esperaba 2 correos de la fecha, hubo {len(correos)}"
    assert correos[-1] is nuevo, "el último debe ser el de las 16:31 (el más nuevo)"
    assert correos[0] is viejo, "el orden debe ser del más viejo al más nuevo"
    assert otro_dia not in correos and ruido not in correos and sin_adj not in correos
    print("OK  _correos_de_fecha: elige el último correo pese al orden hostil")


def check_fecha_en_hora_de_chile():
    from sync_cargas_outlook import _recv_date

    # Outlook entrega ReceivedTime en UTC (Chile = UTC-4).
    casos = [
        (datetime(2026, 8, 7, 23, 31, tzinfo=timezone.utc), date(2026, 8, 7), "19:31 CL"),
        (datetime(2026, 8, 8, 0, 10, tzinfo=timezone.utc), date(2026, 8, 7), "20:10 CL"),
        (datetime(2026, 8, 8, 3, 59, tzinfo=timezone.utc), date(2026, 8, 7), "23:59 CL"),
        (datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc), date(2026, 8, 8), "00:00 CL"),
    ]
    for rt, esperado, etiqueta in casos:
        got = _recv_date(_FakeMsg([], rt))
        assert got == esperado, (
            f"correo de {etiqueta} ({rt:%d-%m %H:%M} UTC): quedó en {got}, "
            f"debía quedar en {esperado}"
        )
    # Naive (sin tz) = ya viene en hora local: no se toca.
    assert _recv_date(_FakeMsg([], datetime(2026, 8, 7, 20, 10))) == date(2026, 8, 7)
    print("OK  _recv_date: archiva por hora de Chile, no por UTC")


def check_itera_todos_los_adjuntos():
    from sync_cargas_outlook import _iter_attachments

    msg = _FakeMsg([PARCIAL, COMPLETO])
    leidos = list(_iter_attachments(msg))
    assert len(leidos) == 2, (
        f"_iter_attachments leyó {len(leidos)} adjunto(s), esperaba 2. "
        "Un correo con varias cargas como adjuntos separados pierde datos."
    )
    assert [n for _, n in leidos] == [PARCIAL.name, COMPLETO.name]
    assert all(b[:2] == b"PK" for b, _ in leidos), "los bytes no son xlsx"
    print("OK  _iter_attachments: 2/2 adjuntos")


def check_ingesta_completa_y_idempotente():
    from db import get_conn
    from ingest_archivo import ingestar_archivo

    fecha = date(2026, 8, 7)

    def _estado():
        with get_conn() as conn:
            cargas = {r[0] for r in conn.execute(
                "SELECT numero_carga FROM cargas WHERE fecha_correo=?", (fecha.isoformat(),))}
            entregas = conn.execute(
                "SELECT COUNT(DISTINCT entrega) FROM items").fetchone()[0]
        return cargas, entregas

    # Orden real del día: primero el correo parcial, después el completo.
    for f in (PARCIAL, COMPLETO):
        ingestar_archivo(f.read_bytes(), f.name, fecha)

    cargas, entregas = _estado()
    faltan = CARGAS_ESPERADAS - cargas
    assert not faltan, f"faltan cargas tras ingerir ambos adjuntos: {sorted(faltan)}"
    assert cargas == CARGAS_ESPERADAS, f"cargas inesperadas: {sorted(cargas - CARGAS_ESPERADAS)}"
    assert entregas == ENTREGAS_ESPERADAS, f"entregas={entregas}, esperaba {ENTREGAS_ESPERADAS}"
    print(f"OK  ingesta: {len(cargas)} cargas / {entregas} entregas")

    # Re-ingerir (lo que pasa al recuperar un día) no debe duplicar ni perder nada.
    for f in (PARCIAL, COMPLETO):
        ingestar_archivo(f.read_bytes(), f.name, fecha)
    assert _estado() == (cargas, entregas), "re-ingerir cambió la base: no es idempotente"
    print("OK  idempotencia: re-ingerir no cambia nada")


def main() -> int:
    for f in (PARCIAL, COMPLETO):
        if not f.exists():
            print(f"SKIP  falta el fixture {f.name} en .tmp/correos_descargados/")
            return 0

    tmp = tempfile.mkdtemp(prefix="check_sync_")
    os.environ["DATA_DIR"] = tmp  # db.py lee DATA_DIR → base descartable, no toca la real
    check_fecha_en_hora_de_chile()
    check_elige_el_ultimo_correo()
    check_itera_todos_los_adjuntos()
    check_ingesta_completa_y_idempotente()
    print("\nTodo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
