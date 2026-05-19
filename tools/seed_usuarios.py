"""Seed la tabla `usuarios` con los operarios iniciales del andén.

Idempotente: usa INSERT OR IGNORE. Se puede correr múltiples veces.
"""

from __future__ import annotations

from db import init_db, upsert_usuario, listar_usuarios_activos

OPERARIOS_INICIALES = [
    "Vicente Caniullan",
    "Benjamin",
    "Maryari",
]


def main() -> None:
    init_db()
    for nombre in OPERARIOS_INICIALES:
        upsert_usuario(nombre)
    activos = listar_usuarios_activos()
    print(f"Usuarios activos ({len(activos)}):")
    for nombre in activos:
        print(f"  - {nombre}")


if __name__ == "__main__":
    main()
