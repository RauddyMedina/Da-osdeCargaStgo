"""SQLite database helpers for Declaración de Daños de Carga.

Schema and CRUD operations used by the Streamlit app and the sync/email tools.
Run this module directly to initialize the database:
    python tools/db.py
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# DATA_DIR puede setearse via env var (en Render apunta al disco persistente).
# Default: data/ dentro del proyecto (modo local).
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "declaracion.db"

TIPOS_DANO = ("01", "02", "03", "04", "Rechazado en anden por daños")

OPERARIOS_DEFECTO = (
    "Vicente Caniullan",
    "Benjamin",
    "Maryari",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS cargas (
    numero_carga    TEXT PRIMARY KEY,
    fecha_correo    DATE NOT NULL,
    cd              TEXT,
    anden           TEXT,
    estado          TEXT NOT NULL DEFAULT 'por_declarar'
                    CHECK(estado IN ('por_declarar','finalizada')),
    sin_danos       INTEGER NOT NULL DEFAULT 0,
    finalizada_por  TEXT,
    finalizada_at   TIMESTAMP,
    enviada_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_carga    TEXT NOT NULL REFERENCES cargas(numero_carga),
    entrega         TEXT NOT NULL,
    producto        TEXT,
    descripcion     TEXT,
    bultos          REAL,
    unidades        REAL,
    nombre_cliente  TEXT,
    comuna          TEXT,
    region          TEXT,
    UNIQUE(numero_carga, entrega, producto)
);
CREATE INDEX IF NOT EXISTS idx_items_carga ON items(numero_carga);
CREATE INDEX IF NOT EXISTS idx_items_entrega ON items(entrega);

CREATE TABLE IF NOT EXISTS danos (
    numero_carga    TEXT NOT NULL REFERENCES cargas(numero_carga),
    entrega         TEXT NOT NULL,
    tipo_dano       TEXT NOT NULL
                    CHECK(tipo_dano IN ('01','02','03','04','Rechazado en anden por daños')),
    declarado_por   TEXT NOT NULL,
    declarado_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (numero_carga, entrega, tipo_dano)
);

CREATE TABLE IF NOT EXISTS usuarios (
    nombre  TEXT PRIMARY KEY,
    activo  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS fotos_carga (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_carga    TEXT NOT NULL REFERENCES cargas(numero_carga),
    ruta_archivo    TEXT NOT NULL,
    subida_por      TEXT NOT NULL,
    subida_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fotos_carga ON fotos_carga(numero_carga);

CREATE TABLE IF NOT EXISTS processed_emails (
    message_id      TEXT PRIMARY KEY,
    procesado_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _migrar_danos_pk(conn: sqlite3.Connection) -> None:
    """Si la tabla `danos` existe con PK (numero_carga, entrega), migra a
    PK (numero_carga, entrega, tipo_dano) para permitir múltiples daños por entrega."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='danos'"
    ).fetchone()
    if not row:
        return  # tabla aún no existe; el SCHEMA la creará con la PK nueva

    cols = conn.execute("PRAGMA table_info(danos)").fetchall()
    pk_cols = [c[1] for c in cols if c[5] > 0]  # c[5] = pk position
    if "tipo_dano" in pk_cols:
        return  # ya migrada

    conn.executescript(
        """
        BEGIN;
        CREATE TABLE danos_new (
            numero_carga    TEXT NOT NULL REFERENCES cargas(numero_carga),
            entrega         TEXT NOT NULL,
            tipo_dano       TEXT NOT NULL
                            CHECK(tipo_dano IN ('01','02','03','04','Rechazado en anden por daños')),
            declarado_por   TEXT NOT NULL,
            declarado_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (numero_carga, entrega, tipo_dano)
        );
        INSERT INTO danos_new (numero_carga, entrega, tipo_dano, declarado_por, declarado_at)
            SELECT numero_carga, entrega, tipo_dano, declarado_por, declarado_at FROM danos;
        DROP TABLE danos;
        ALTER TABLE danos_new RENAME TO danos;
        COMMIT;
        """
    )


def _seed_usuarios_defecto(conn: sqlite3.Connection) -> None:
    """Si la tabla `usuarios` está vacía, agrega los operarios iniciales.
    Idempotente: solo siembra si no hay nadie."""
    n = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if n > 0:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO usuarios (nombre, activo) VALUES (?, 1)",
        [(n,) for n in OPERARIOS_DEFECTO],
    )


def init_db() -> None:
    """Create tables if they don't exist and enable WAL for concurrency."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        _migrar_danos_pk(conn)
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _seed_usuarios_defecto(conn)
        conn.commit()


@contextmanager
def get_conn():
    """Yield a sqlite3 connection with row factory and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- Usuarios ----------

def listar_usuarios_activos() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT nombre FROM usuarios WHERE activo=1 ORDER BY nombre"
        ).fetchall()
    return [r["nombre"] for r in rows]


def upsert_usuario(nombre: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO usuarios (nombre, activo) VALUES (?, 1)",
            (nombre,),
        )


# ---------- Cargas ----------

def upsert_carga(
    numero_carga: str,
    fecha_correo: date,
    cd: str | None,
    anden: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO cargas (numero_carga, fecha_correo, cd, anden)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(numero_carga) DO NOTHING
            """,
            (numero_carga, fecha_correo.isoformat(), cd, anden),
        )


def listar_cargas_por_fecha(
    fecha: date,
    estado: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT c.*,
               (SELECT COUNT(DISTINCT entrega) FROM items WHERE numero_carga=c.numero_carga) AS total_entregas,
               (SELECT COUNT(DISTINCT entrega) FROM danos WHERE numero_carga=c.numero_carga) AS total_danos
        FROM cargas c
        WHERE c.fecha_correo = ?
    """
    params: list = [fecha.isoformat()]
    if estado:
        query += " AND c.estado = ?"
        params.append(estado)
    query += " ORDER BY c.numero_carga"
    with get_conn() as conn:
        return conn.execute(query, params).fetchall()


def listar_fechas_con_cargas() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT fecha_correo FROM cargas ORDER BY fecha_correo DESC"
        ).fetchall()
    return [r["fecha_correo"] for r in rows]


def obtener_carga(numero_carga: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM cargas WHERE numero_carga = ?", (numero_carga,)
        ).fetchone()


def finalizar_carga(
    numero_carga: str,
    finalizada_por: str,
    sin_danos: bool = False,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE cargas
               SET estado='finalizada',
                   sin_danos=?,
                   finalizada_por=?,
                   finalizada_at=CURRENT_TIMESTAMP
             WHERE numero_carga=?
            """,
            (1 if sin_danos else 0, finalizada_por, numero_carga),
        )


def reabrir_carga(numero_carga: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE cargas
               SET estado='por_declarar',
                   sin_danos=0,
                   finalizada_por=NULL,
                   finalizada_at=NULL
             WHERE numero_carga=? AND enviada_at IS NULL
            """,
            (numero_carga,),
        )


def cargas_pendientes_de_envio() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT * FROM cargas
             WHERE estado='finalizada' AND sin_danos=0 AND enviada_at IS NULL
             ORDER BY numero_carga
            """
        ).fetchall()


def marcar_cargas_enviadas(numeros: list[str]) -> None:
    if not numeros:
        return
    placeholders = ",".join("?" * len(numeros))
    with get_conn() as conn:
        conn.execute(
            f"UPDATE cargas SET enviada_at=CURRENT_TIMESTAMP "
            f"WHERE numero_carga IN ({placeholders})",
            numeros,
        )


# ---------- Items ----------

def upsert_item(
    numero_carga: str,
    entrega: str,
    producto: str | None,
    descripcion: str | None,
    bultos: float | None,
    unidades: float | None,
    nombre_cliente: str | None,
    comuna: str | None,
    region: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO items
                (numero_carga, entrega, producto, descripcion, bultos,
                 unidades, nombre_cliente, comuna, region)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                numero_carga,
                str(entrega),
                producto,
                descripcion,
                bultos,
                unidades,
                nombre_cliente,
                comuna,
                region,
            ),
        )


def listar_entregas_de_carga(numero_carga: str) -> list[sqlite3.Row]:
    """Return one row per unique entrega with aggregated info."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT entrega,
                   MAX(nombre_cliente) AS nombre_cliente,
                   MAX(comuna)          AS comuna,
                   MAX(region)          AS region,
                   COUNT(*)             AS lineas,
                   SUM(bultos)          AS total_bultos
              FROM items
             WHERE numero_carga = ?
             GROUP BY entrega
             ORDER BY entrega
            """,
            (numero_carga,),
        ).fetchall()


# ---------- Daños ----------

def upsert_dano(
    numero_carga: str,
    entrega: str,
    tipo_dano: str,
    declarado_por: str,
) -> None:
    """Agrega un tipo de daño para (carga, entrega). Permite múltiples tipos por entrega.
    Si ya existe ese tipo, refresca declarado_por y declarado_at."""
    if tipo_dano not in TIPOS_DANO:
        raise ValueError(f"Tipo de daño inválido: {tipo_dano}")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO danos (numero_carga, entrega, tipo_dano, declarado_por)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(numero_carga, entrega, tipo_dano) DO UPDATE SET
                declarado_por=excluded.declarado_por,
                declarado_at=CURRENT_TIMESTAMP
            """,
            (numero_carga, str(entrega), tipo_dano, declarado_por),
        )


def set_danos_for_entrega(
    numero_carga: str,
    entrega: str,
    tipos: list[str],
    declarado_por: str,
) -> None:
    """Reemplaza el conjunto de daños declarados para una entrega.
    Si `tipos` está vacío, elimina todos los daños de esa entrega."""
    for t in tipos:
        if t not in TIPOS_DANO:
            raise ValueError(f"Tipo de daño inválido: {t}")
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM danos WHERE numero_carga=? AND entrega=?",
            (numero_carga, str(entrega)),
        )
        if tipos:
            conn.executemany(
                """
                INSERT INTO danos (numero_carga, entrega, tipo_dano, declarado_por)
                VALUES (?, ?, ?, ?)
                """,
                [(numero_carga, str(entrega), t, declarado_por) for t in tipos],
            )


def eliminar_dano(numero_carga: str, entrega: str) -> None:
    """Elimina TODOS los tipos de daño declarados para esa entrega."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM danos WHERE numero_carga=? AND entrega=?",
            (numero_carga, str(entrega)),
        )


def listar_danos_de_carga(numero_carga: str) -> dict[str, list[sqlite3.Row]]:
    """Retorna {entrega: [rows_de_tipos_de_dano]}. Una entrega puede tener varios tipos."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM danos WHERE numero_carga=? ORDER BY entrega, tipo_dano",
            (numero_carga,),
        ).fetchall()
    result: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        result.setdefault(r["entrega"], []).append(r)
    return result


# ---------- Fotos ----------

def agregar_foto(numero_carga: str, ruta_archivo: str, subida_por: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO fotos_carga (numero_carga, ruta_archivo, subida_por)
            VALUES (?, ?, ?)
            """,
            (numero_carga, ruta_archivo, subida_por),
        )
        return cur.lastrowid


def listar_fotos_de_carga(numero_carga: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM fotos_carga WHERE numero_carga=? ORDER BY subida_at",
            (numero_carga,),
        ).fetchall()


def eliminar_foto(foto_id: int) -> str | None:
    """Delete a photo row, return its file path so the caller can delete the file."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ruta_archivo FROM fotos_carga WHERE id=?", (foto_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM fotos_carga WHERE id=?", (foto_id,))
    return row["ruta_archivo"]


def eliminar_fotos_de_cargas(numeros_carga: list[str]) -> int:
    """Borra todos los registros fotos_carga para las cargas dadas. Devuelve filas borradas."""
    if not numeros_carga:
        return 0
    placeholders = ",".join("?" * len(numeros_carga))
    with get_conn() as conn:
        cur = conn.execute(
            f"DELETE FROM fotos_carga WHERE numero_carga IN ({placeholders})",
            numeros_carga,
        )
        return cur.rowcount


# ---------- Emails procesados ----------

def email_ya_procesado(message_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_emails WHERE message_id=?", (message_id,)
        ).fetchone()
    return row is not None


def marcar_email_procesado(message_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_emails (message_id) VALUES (?)",
            (message_id,),
        )


if __name__ == "__main__":
    init_db()
    print(f"DB inicializada en: {DB_PATH}")
