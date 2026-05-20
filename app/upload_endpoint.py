"""Endpoint HTTP `/api/import` inyectado en el servidor Tornado de Streamlit.

Permite que un script local (sync_and_push.py) empuje cargas/items vía POST.
Auth: Bearer token contra env var UPLOAD_TOKEN.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

from tornado.web import RequestHandler
from tornado.routing import Rule, PathMatches
import streamlit.web.server.server as st_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "")


class ImportHandler(RequestHandler):
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
            self.write({"ok": True, "cargas": n_c, "items": n_i})
        except Exception as e:
            self.set_status(500)
            self.write({"error": f"{type(e).__name__}: {e}"})


def install() -> None:
    """Inyecta /api/import en el wildcard_router de Streamlit. Idempotente."""
    if getattr(st_server.Server, "_upload_patched", False):
        return
    original_create_app = st_server.Server._create_app

    def _patched_create_app(self):
        app = original_create_app(self)
        try:
            new_rule = Rule(PathMatches(r"/api/import"), ImportHandler)
            # Insertar después de la regla de seguridad (^//.*$ está en index 0),
            # antes del catch-all StaticFileHandler.
            app.wildcard_router.rules.insert(1, new_rule)
        except Exception as e:
            print(f"[upload_endpoint] WARN: no se pudo inyectar /api/import: {e}")
        return app

    st_server.Server._create_app = _patched_create_app
    st_server.Server._upload_patched = True
