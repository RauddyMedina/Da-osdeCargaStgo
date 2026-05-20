"""Entrypoint personalizado para Render.

Inyecta /api/import ANTES de que Streamlit inicie el servidor,
luego arranca la app normalmente via bootstrap.run().

Uso (en render.yaml startCommand):
    python app/start.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
TOOLS_DIR = PROJECT_ROOT / "tools"

sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(APP_DIR))

# Parchear create_streamlit_routes ANTES de que Streamlit inicie el servidor
from upload_endpoint import _install_starlette, _install_tornado  # noqa: E402
_install_starlette()
_install_tornado()

# Ahora arrancar Streamlit con los mismos flags que el startCommand anterior
from streamlit.web import bootstrap  # noqa: E402

flag_options: dict = {
    "server.port": int(os.environ.get("PORT", "8501")),
    "server.address": "0.0.0.0",
    "server.headless": True,
}

bootstrap.run(
    main_script_path=str(APP_DIR / "streamlit_app.py"),
    is_hello=False,
    args=[],
    flag_options=flag_options,
)
