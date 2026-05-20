"""Endpoint HTTP `/api/import` inyectado en Streamlit.

Soporta ambos modos de servidor:
- Starlette/uvicorn (Render, server.useStarlette=True)
- Tornado (local, server.useStarlette=False)

Auth: Bearer token contra env var UPLOAD_TOKEN.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "")


# ─── Lógica compartida ────────────────────────────────────────────────────────

def _handle_import(payload: dict) -> dict:
    from db import init_db, upsert_carga, upsert_item
    init_db()
    n_c = 0
    for c in payload.get("cargas", []):
        upsert_carga(
            numero_carga=c["numero_carga"],
            fecha_correo=date.fromisoformat(c["fecha_correo"]),
            cd=c.get("cd"),
            anden=c.get("anden"),
        )
        n_c += 1
    n_i = 0
    for it in payload.get("items", []):
        upsert_item(
            numero_carga=it["numero_carga"],
            entrega=it["entrega"],
            producto=it.get("producto"),
            descripcion=it.get("descripcion"),
            bultos=it.get("bultos"),
            unidades=it.get("unidades"),
            nombre_cliente=it.get("nombre_cliente"),
            comuna=it.get("comuna"),
            region=it.get("region"),
        )
        n_i += 1
    return {"ok": True, "cargas": n_c, "items": n_i}


# ─── Starlette handler (Render / uvicorn) ─────────────────────────────────────

async def _starlette_import(request):
    from starlette.responses import JSONResponse
    auth = request.headers.get("Authorization", "")
    if not UPLOAD_TOKEN or auth != f"Bearer {UPLOAD_TOKEN}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        result = _handle_import(payload)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


def _install_starlette() -> bool:
    """Parchea create_streamlit_routes para inyectar /api/import. Retorna True si OK."""
    try:
        import streamlit.web.server.starlette.starlette_app as sa
        from starlette.routing import Route

        if getattr(sa, "_upload_patched", False):
            return True

        original = sa.create_streamlit_routes

        def patched(runtime):
            routes = original(runtime)
            new_route = Route("/api/import", _starlette_import, methods=["POST"])
            routes.insert(0, new_route)
            return routes

        sa.create_streamlit_routes = patched
        sa._upload_patched = True
        return True
    except Exception as e:
        print(f"[upload_endpoint] Starlette patch falló: {e}")
        return False


# ─── Tornado handler (local) ──────────────────────────────────────────────────

def _install_tornado() -> bool:
    """Parchea Server._create_app para inyectar /api/import en Tornado. Retorna True si OK."""
    try:
        from tornado.web import RequestHandler
        from tornado.routing import Rule, PathMatches
        import streamlit.web.server.server as st_server

        if getattr(st_server.Server, "_upload_patched", False):
            return True

        class _ImportHandler(RequestHandler):
            def set_default_headers(self):
                self.set_header("Content-Type", "application/json")

            def post(self):
                auth = self.request.headers.get("Authorization", "")
                if not UPLOAD_TOKEN or auth != f"Bearer {UPLOAD_TOKEN}":
                    self.set_status(401)
                    self.write({"error": "unauthorized"})
                    return
                try:
                    payload = json.loads(self.request.body or b"{}")
                    result = _handle_import(payload)
                    self.write(result)
                except Exception as e:
                    self.set_status(500)
                    self.write({"error": f"{type(e).__name__}: {e}"})

        original = st_server.Server._create_app

        def _patched(self):
            app = original(self)
            try:
                new_rule = Rule(PathMatches(r"/api/import"), _ImportHandler)
                app.wildcard_router.rules.insert(1, new_rule)
            except Exception as e:
                print(f"[upload_endpoint] Tornado rule inject falló: {e}")
            return app

        st_server.Server._create_app = _patched
        st_server.Server._upload_patched = True
        return True
    except Exception as e:
        print(f"[upload_endpoint] Tornado patch falló: {e}")
        return False


# ─── Entry point ──────────────────────────────────────────────────────────────

def install() -> None:
    """Inyecta /api/import en Streamlit (Starlette o Tornado). Idempotente."""
    ok_starlette = _install_starlette()
    ok_tornado = _install_tornado()
    if not ok_starlette and not ok_tornado:
        print("[upload_endpoint] WARN: no se pudo instalar el endpoint /api/import")
