"""Detecta y borra filas fotos_carga cuyo archivo no existe en disco.

Uso CLI:
    python tools/limpiar_fotos_huerfanas.py           # dry-run global
    python tools/limpiar_fotos_huerfanas.py --apply   # aplica borrado

Uso programático (desde Streamlit admin):
    from limpiar_fotos_huerfanas import escanear_huerfanas
    result = escanear_huerfanas(apply=True)
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from db import DATA_DIR, eliminar_fotos_por_ids, listar_todas_las_fotos


def _resolver(p: str) -> Path:
    pth = Path(p)
    if pth.is_absolute():
        return pth
    cand = DATA_DIR / p
    if cand.exists():
        return cand
    return Path(__file__).parent.parent / p


def escanear_huerfanas(apply: bool = False) -> dict:
    rows = listar_todas_las_fotos()
    huerfanas_por_carga: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if not _resolver(r["ruta_archivo"]).exists():
            huerfanas_por_carga[r["numero_carga"]].append(r["id"])

    total_huerfanas = sum(len(v) for v in huerfanas_por_carga.values())
    result = {
        "cargas_afectadas": len(huerfanas_por_carga),
        "huerfanas_total": total_huerfanas,
        "fotos_validas": len(rows) - total_huerfanas,
        "applied": False,
        "borradas": 0,
        "detalle": {nc: len(ids) for nc, ids in huerfanas_por_carga.items()},
    }
    if apply and total_huerfanas:
        ids_all = [i for ids in huerfanas_por_carga.values() for i in ids]
        result["borradas"] = eliminar_fotos_por_ids(ids_all)
        result["applied"] = True
    return result


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    r = escanear_huerfanas(apply=apply)
    print(f"Cargas afectadas: {r['cargas_afectadas']}")
    print(f"Filas huérfanas:  {r['huerfanas_total']}")
    print(f"Fotos válidas:    {r['fotos_validas']}")
    for nc, n in sorted(r["detalle"].items(), key=lambda x: -x[1])[:20]:
        print(f"  {nc}: {n} huérfanas")
    if apply:
        print(f"\n✅ Borradas: {r['borradas']} filas")
    else:
        print("\n[DRY-RUN] Re-ejecuta con --apply para borrar.")
