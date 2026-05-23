"""Ingesta de cargas desde un archivo Excel o CSV subido manualmente.

Acepta dos formatos:
- CSV del correo (columnas en MAYÚSCULAS: NUMERO CARGA, ENTREGA, CD, ANDEN, ...)
- Excel manual (columnas tipo título: Nro Carga, Entrega, CD, Anden, Región, Unid, ...)

Normaliza nombres de columna, mapea al esquema interno y llama upsert_carga/upsert_item.
"""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import date
from typing import Any

import pandas as pd

from db import init_db, upsert_carga, upsert_item


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _norm_col(c: Any) -> str:
    s = _strip_accents(str(c)).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


COL_ALIASES: dict[str, tuple[str, ...]] = {
    "numero_carga": ("numero carga", "nro carga", "n carga", "n° carga", "no carga"),
    "entrega": ("entrega",),
    "cd": ("cd",),
    "anden": ("anden",),
    "producto": ("producto",),
    "descripcion": ("descripcion",),
    "bultos": ("bultos", "bulto", "bultos totales"),
    "unidades": ("unidades", "unid", "unid.", "cantidad unidades"),
    "nombre_cliente": ("nombre cliente", "nombre"),
    "comuna": ("comuna",),
    "region": ("region",),
}


def _build_col_map(df_cols: list[str]) -> dict[str, str]:
    """Mapea nombre normalizado del Excel → nombre interno. Retorna {interno: col_original}."""
    norm_to_orig = {_norm_col(c): c for c in df_cols}
    result: dict[str, str] = {}
    for interno, aliases in COL_ALIASES.items():
        for alias in aliases:
            if alias in norm_to_orig:
                result[interno] = norm_to_orig[alias]
                break
    return result


def _norm(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _clean_numero_carga(raw: Any) -> str | None:
    s = _norm(raw)
    if not s:
        return None
    return re.sub(r"^CARGA[:\s]*", "", s, flags=re.IGNORECASE) or None


def _parse_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


_HEADER_KEYWORDS = {"nro carga", "numero carga", "entrega"}


def _find_header_row(df_raw: pd.DataFrame) -> int:
    """Busca en las primeras 10 filas cuál contiene las columnas reales del Excel.

    Retorna el índice de esa fila, o -1 si ya la fila 0 sirve como header.
    """
    for i, row in df_raw.head(10).iterrows():
        vals = {_strip_accents(str(v)).strip().lower() for v in row.values if pd.notna(v)}
        if _HEADER_KEYWORDS & vals:
            return int(i)
    return -1


def _read_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("xlsx", "xls"):
        # Primera pasada: leer sin asumir header para detectar filas de metadata
        raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)
        header_row = _find_header_row(raw)
        if header_row >= 0:
            # Usar esa fila como nombres de columna
            df = pd.read_excel(io.BytesIO(file_bytes), header=header_row, dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        return df
    if ext == "csv":
        for sep in (";", ",", "\t"):
            for enc in ("latin-1", "utf-8", "cp1252"):
                try:
                    df = pd.read_csv(
                        io.BytesIO(file_bytes), sep=sep, dtype=str,
                        encoding=enc, on_bad_lines="skip",
                    )
                    if df.shape[1] >= 2:
                        # También detectar header diferido en CSV
                        raw = pd.read_csv(
                            io.BytesIO(file_bytes), sep=sep, dtype=str,
                            encoding=enc, on_bad_lines="skip", header=None,
                        )
                        hr = _find_header_row(raw)
                        if hr > 0:
                            df = pd.read_csv(
                                io.BytesIO(file_bytes), sep=sep, dtype=str,
                                encoding=enc, on_bad_lines="skip", header=hr,
                            )
                        return df
                except Exception:
                    continue
        raise ValueError("No se pudo leer el CSV (probé ;,\\t × latin-1/utf-8/cp1252)")
    raise ValueError(f"Extensión no soportada: '{ext}'. Usa .xlsx, .xls o .csv")


def ingestar_archivo(
    file_bytes: bytes,
    filename: str,
    fecha_correo: date,
) -> dict:
    """Parsea el archivo y hace upsert de cargas + items.

    Retorna: {"cargas": N, "items": M, "errores": [...], "preview": DataFrame|None}
    """
    init_db()

    try:
        df = _read_dataframe(file_bytes, filename)
    except Exception as e:
        return {"cargas": 0, "items": 0, "errores": [str(e)], "preview": None}

    col_map = _build_col_map(list(df.columns))

    faltantes = [k for k in ("numero_carga", "entrega") if k not in col_map]
    if faltantes:
        return {
            "cargas": 0,
            "items": 0,
            "errores": [
                f"Faltan columnas obligatorias: {faltantes}. "
                f"Columnas detectadas: {list(df.columns)}"
            ],
            "preview": df.head(5),
        }

    cargas_vistas: set[str] = set()
    items_count = 0
    errores: list[str] = []

    def _get(row, key: str):
        col = col_map.get(key)
        return row.get(col) if col else None

    for idx, row in df.iterrows():
        numero_carga = _clean_numero_carga(_get(row, "numero_carga"))
        entrega = _norm(_get(row, "entrega"))
        if not numero_carga or not entrega:
            continue

        if numero_carga not in cargas_vistas:
            try:
                upsert_carga(
                    numero_carga=numero_carga,
                    fecha_correo=fecha_correo,
                    cd=_norm(_get(row, "cd")),
                    anden=_norm(_get(row, "anden")),
                )
                cargas_vistas.add(numero_carga)
            except Exception as e:
                errores.append(f"Fila {idx}: upsert_carga falló — {e}")
                continue

        try:
            upsert_item(
                numero_carga=numero_carga,
                entrega=entrega,
                producto=_norm(_get(row, "producto")),
                descripcion=_norm(_get(row, "descripcion")),
                bultos=_parse_float(_get(row, "bultos")),
                unidades=_parse_float(_get(row, "unidades")),
                nombre_cliente=_norm(_get(row, "nombre_cliente")),
                comuna=_norm(_get(row, "comuna")),
                region=_norm(_get(row, "region")),
            )
            items_count += 1
        except Exception as e:
            errores.append(f"Fila {idx} ({numero_carga}/{entrega}): upsert_item falló — {e}")

    return {
        "cargas": len(cargas_vistas),
        "items": items_count,
        "errores": errores,
        "preview": df.head(5),
    }
