"""Limpia fotos duplicadas en una carga, dejando solo las originales + N recientes.

Uso:
    python tools/cleanup_fotos_duplicadas.py CL30041333          # dry-run, solo muestra
    python tools/cleanup_fotos_duplicadas.py CL30041333 --apply  # ejecuta el borrado

Estrategia:
- Detecta el "corte" entre fotos antiguas (sync Outlook, antes de hoy) y las nuevas
  (subidas hoy por la app via file_uploader, con prefijo CARGA_<nc>_<uid>).
- Para las nuevas: mantiene solo las únicas por tamaño de archivo (las del bug eran
  copias byte a byte del mismo upload).
- Borra registros de DB Y los archivos físicos del disco.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from db import DATA_DIR, get_conn


def _resolver(p: str) -> Path:
    pth = Path(p)
    if pth.is_absolute():
        return pth
    cand = DATA_DIR / p
    if cand.exists():
        return cand
    return Path(__file__).parent.parent / p


def main(numero_carga: str, apply: bool = False) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ruta_archivo, subida_at FROM fotos_carga "
            "WHERE numero_carga=? ORDER BY subida_at, id",
            (numero_carga,),
        ).fetchall()

    print(f"Total fotos en {numero_carga}: {len(rows)}")
    if not rows:
        return

    # Agrupa por tamaño de archivo (los duplicados del bug son byte-idénticos)
    by_size: dict[int, list] = defaultdict(list)
    huerfanas: list = []
    for r in rows:
        ruta = _resolver(r["ruta_archivo"])
        if not ruta.exists():
            huerfanas.append(r)
            continue
        size = ruta.stat().st_size
        by_size[size].append((r, ruta))

    a_borrar_ids: list[int] = []
    a_borrar_files: list[Path] = []
    a_mantener = 0

    for size, items in by_size.items():
        if len(items) == 1:
            a_mantener += 1
            continue
        # Mantener el más viejo (subida_at menor) de ese grupo y borrar el resto
        items.sort(key=lambda x: (x[0]["subida_at"], x[0]["id"]))
        a_mantener += 1
        for r, ruta in items[1:]:
            a_borrar_ids.append(r["id"])
            a_borrar_files.append(ruta)

    # Registros huérfanos en DB sin archivo → también borrar
    for r in huerfanas:
        a_borrar_ids.append(r["id"])

    print(f"  Archivos huérfanos (sin disco):  {len(huerfanas)}")
    print(f"  Duplicados a borrar:             {len(a_borrar_ids) - len(huerfanas)}")
    print(f"  Únicos a MANTENER:               {a_mantener}")
    print(f"  Espacio a liberar:               "
          f"{sum(p.stat().st_size for p in a_borrar_files) / 1024 / 1024:.1f} MB")

    if not apply:
        print("\n[DRY-RUN] No se borró nada. Re-ejecuta con --apply para aplicar.")
        return

    with get_conn() as conn:
        for chunk_start in range(0, len(a_borrar_ids), 500):
            chunk = a_borrar_ids[chunk_start:chunk_start + 500]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(
                f"DELETE FROM fotos_carga WHERE id IN ({placeholders})",
                chunk,
            )

    borrados_disco = 0
    for p in a_borrar_files:
        try:
            p.unlink()
            borrados_disco += 1
        except Exception as e:
            print(f"  ! No se pudo borrar {p}: {e}")

    print(f"\n✅ Borrados {len(a_borrar_ids)} registros DB, {borrados_disco} archivos.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python tools/cleanup_fotos_duplicadas.py <NUMERO_CARGA> [--apply]")
        sys.exit(1)
    nc = sys.argv[1]
    apply = "--apply" in sys.argv
    main(nc, apply=apply)
