"""PWA mobile para Declaración de Daños de Carga en Andén.

Ejecutar:
    streamlit run app/streamlit_app.py

Diseño:
    - Login → selector de operario
    - Cargas del día → con flechas ◄ ► para navegar fechas
    - Detalle de carga → declarar daños, subir fotos, finalizar
    - Tabs: Por declarar / Finalizados / Admin
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = PROJECT_ROOT.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PARENT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from db import (  # noqa: E402
    TIPOS_DANO,
    agregar_foto,
    cargas_pendientes_de_envio,
    eliminar_dano,
    eliminar_foto,
    finalizar_carga,
    init_db,
    listar_cargas_por_fecha,
    listar_danos_de_carga,
    listar_entregas_de_carga,
    listar_fotos_de_carga,
    listar_usuarios_activos,
    obtener_carga,
    reabrir_carga,
    set_danos_for_entrega,
)

DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
FOTOS_DIR = DATA_DIR / "fotos"
MIN_FOTOS = int(os.getenv("MIN_FOTOS_POR_CARGA", "1"))


def _resolver_ruta_foto(path_str: str) -> Path:
    """Resuelve la ruta de una foto (DB guarda paths relativos).
    Acepta paths nuevos (relativos a DATA_DIR) y legacy (relativos a PROJECT_ROOT).
    """
    p = Path(path_str)
    if p.is_absolute():
        return p
    nuevo = DATA_DIR / p
    if nuevo.exists():
        return nuevo
    legacy = PROJECT_ROOT / p
    return legacy if legacy.exists() else nuevo

# ---------- Config & CSS ----------

st.set_page_config(
    page_title="Declaración Daños Andén",
    page_icon="🚚",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  /* ===== BOX-SIZING GLOBAL (evita overflow por padding) ===== */
  *, *::before, *::after {
    box-sizing: border-box !important;
  }

  /* ===== GLOBAL DARK THEME + OVERFLOW PREVENTION ===== */
  html, body {
    background: #0f1117 !important;
    color: #e8e8ed !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    overflow-x: hidden !important;
    max-width: 100vw !important;
    width: 100% !important;
  }
  /* Todos los contenedores de Streamlit: nunca más anchos que el viewport */
  [data-testid="stApp"],
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"],
  section.main {
    background: #0f1117 !important;
    color: #e8e8ed !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    overflow-x: hidden !important;
    max-width: 100vw !important;
    width: 100% !important;
  }
  .main .block-container {
    padding: 0 0.8rem 5rem 0.8rem !important;
    max-width: 480px !important;
    width: 100% !important;
    overflow-x: hidden !important;
  }
  /* Columnas siempre en fila sin desbordar (no sólo en mobile) */
  div[data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    gap: 8px !important;
    max-width: 100% !important;
    width: 100% !important;
  }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
  div[data-testid="stHorizontalBlock"] > div {
    min-width: 0 !important;
    flex: 1 1 0 !important;
    width: auto !important;
    max-width: 100% !important;
  }
  [data-testid="stHeader"] { background: transparent !important; }
  [data-testid="stSidebar"] { background: #181a20 !important; }
  section[data-testid="stSidebar"] * { color: #e8e8ed !important; }
  hr { border-color: rgba(255,255,255,0.08) !important; }

  /* ===== HEADER BAR ===== */
  .app-header {
    background: linear-gradient(135deg, #e65100, #f57c00, #ff9800);
    color: white;
    padding: 16px 20px;
    margin: -1rem -0.8rem 1.2rem -0.8rem;
    font-size: 18px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    letter-spacing: 0.3px;
    box-shadow: 0 4px 20px rgba(245,124,0,0.35);
    position: relative;
    z-index: 10;
    max-width: calc(100% + 1.6rem);
    overflow: hidden;
  }

  /* ===== CARGA CARDS — glassmorphism ===== */
  .carga-card {
    background: rgba(255,255,255,0.04);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255,183,77,0.2);
    border-radius: 16px;
    padding: 18px 20px;
    margin-bottom: 12px;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  }
  .carga-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(245,124,0,0.15);
    border-color: rgba(255,183,77,0.45);
  }
  .carga-card.finalizada {
    background: rgba(46,125,50,0.08);
    border-color: rgba(129,199,132,0.3);
  }
  .carga-card.finalizada:hover {
    box-shadow: 0 8px 25px rgba(46,125,50,0.15);
    border-color: rgba(129,199,132,0.5);
  }
  .carga-card.sin-danos {
    background: rgba(156,39,176,0.06);
    border-color: rgba(206,147,216,0.25);
  }
  .carga-titulo {
    color: #ffb74d;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.5px;
  }
  .carga-sub {
    color: rgba(255,255,255,0.5);
    font-size: 13px;
    margin-top: 6px;
    font-weight: 400;
  }

  /* ===== BADGES ===== */
  .badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 10px;
    font-weight: 700;
    margin-left: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    vertical-align: middle;
  }
  .badge-warn {
    background: rgba(255,167,38,0.15);
    color: #ffb74d;
    border: 1px solid rgba(255,167,38,0.3);
  }
  .badge-ok {
    background: rgba(76,175,80,0.15);
    color: #81c784;
    border: 1px solid rgba(76,175,80,0.3);
    animation: pulse-green 2s ease-in-out infinite;
  }
  .badge-sin {
    background: rgba(186,104,200,0.15);
    color: #ce93d8;
    border: 1px solid rgba(186,104,200,0.3);
  }
  @keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 0 0 rgba(76,175,80,0); }
    50% { box-shadow: 0 0 8px 2px rgba(76,175,80,0.2); }
  }

  /* ===== BUTTONS ===== */
  /* Estilo base (default = secondary glass) - aplica a todos los botones */
  div.stButton > button,
  div[data-testid="stButton"] > button,
  div[data-testid="stBaseButton-secondary"],
  button[data-testid*="stBaseButton-secondary"] {
    width: 100%;
    padding: 12px 0;
    font-weight: 600;
    font-family: 'Inter', sans-serif !important;
    border-radius: 12px !important;
    font-size: 14px !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.3px;
    background: rgba(255,255,255,0.06) !important;
    color: #e8e8ed !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
  }
  div.stButton > button:hover,
  div[data-testid="stButton"] > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
    background: rgba(255,255,255,0.1) !important;
    border-color: rgba(255,183,77,0.3) !important;
  }
  div.stButton > button:active {
    transform: scale(0.98) !important;
  }
  /* Primary CTA — orange gradient (sobrescribe el default) */
  div.stButton > button[kind="primary"],
  div[data-testid="stButton"] > button[kind="primary"],
  button[data-testid*="stBaseButton-primary"] {
    background: linear-gradient(135deg, #e65100, #f57c00) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(230,81,0,0.3) !important;
  }
  div.stButton > button[kind="primary"]:hover,
  div[data-testid="stButton"] > button[kind="primary"]:hover,
  button[data-testid*="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #bf360c, #e65100) !important;
    box-shadow: 0 6px 20px rgba(230,81,0,0.4) !important;
    border-color: transparent !important;
  }

  /* ===== TEXT INPUTS — dark glass ===== */
  /* Wrapper de BaseWeb (Streamlit ≥1.32): el fondo visible está aquí, no en <input> */
  div[data-testid="stTextInput"] > div,
  div[data-testid="stTextInput"] [data-baseweb="input"],
  div[data-testid="stTextInput"] [data-baseweb="base-input"],
  div[data-testid="stTextInputRootElement"] {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 12px !important;
    color: #e8e8ed !important;
  }
  div[data-testid="stTextInput"] input {
    font-size: 16px !important;
    padding: 14px 16px !important;
    border-radius: 12px !important;
    background: transparent !important;
    border: none !important;
    color: #e8e8ed !important;
    font-family: 'Inter', sans-serif !important;
    transition: border-color 0.2s ease !important;
  }
  div[data-testid="stTextInput"] input:focus {
    border-color: #f57c00 !important;
    box-shadow: 0 0 0 2px rgba(245,124,0,0.2) !important;
  }
  div[data-testid="stTextInput"] input::placeholder {
    color: rgba(255,255,255,0.3) !important;
  }
  div[data-testid="stTextInput"] label {
    color: rgba(255,255,255,0.5) !important;
  }

  /* ===== SELECT BOXES ===== */
  div[data-testid="stSelectbox"] > div > div {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 12px !important;
    color: #e8e8ed !important;
  }
  div[data-testid="stSelectbox"] label {
    color: rgba(255,255,255,0.6) !important;
    font-weight: 500 !important;
  }

  /* ===== EXPANDERS ===== */
  details[data-testid="stExpander"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 14px !important;
    margin-bottom: 8px;
    transition: border-color 0.2s ease;
  }
  details[data-testid="stExpander"]:hover {
    border-color: rgba(255,183,77,0.25) !important;
  }
  details[data-testid="stExpander"] summary {
    color: #e8e8ed !important;
    font-weight: 500 !important;
    padding: 14px 16px !important;
  }
  details[data-testid="stExpander"] > div {
    border-top: 1px solid rgba(255,255,255,0.06) !important;
  }

  /* ===== RADIO BUTTONS ===== */
  div[data-testid="stRadio"] label {
    color: rgba(255,255,255,0.7) !important;
  }
  div[data-testid="stRadio"] label span {
    color: #e8e8ed !important;
  }

  /* ===== DATE NAV ===== */
  .date-nav {
    text-align: center;
    font-weight: 700;
    font-size: 15px;
    padding: 8px 0;
    color: rgba(255,255,255,0.7);
    letter-spacing: 0.5px;
  }
  .date-nav span {
    color: #ffb74d;
  }

  /* ===== TAB PILLS ===== */
  .tab-active {
    background: linear-gradient(135deg, #e65100, #f57c00) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(230,81,0,0.3) !important;
  }

  /* ===== LOGIN SCREEN ===== */
  .login-logo {
    text-align: center;
    margin: 2rem 0 1rem 0;
  }
  .login-logo .icon {
    font-size: 64px;
    display: block;
    margin-bottom: 8px;
    animation: float 3s ease-in-out infinite;
  }
  .login-title {
    text-align: center;
    font-size: 24px;
    font-weight: 800;
    background: linear-gradient(135deg, #ffb74d, #f57c00);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 4px;
  }
  .login-subtitle {
    text-align: center;
    color: rgba(255,255,255,0.4);
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 2rem;
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  @keyframes float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-8px); }
  }

  /* ===== DETAIL STATS ROW ===== */
  .stat-row {
    display: flex;
    gap: 10px;
    margin: 12px 0 16px 0;
  }
  .stat-chip {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 10px 8px;
    text-align: center;
  }
  .stat-chip .val {
    font-size: 20px;
    font-weight: 800;
    color: #ffb74d;
    display: block;
  }
  .stat-chip .lbl {
    font-size: 10px;
    color: rgba(255,255,255,0.4);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 2px;
    display: block;
  }

  /* ===== ALERTS & MESSAGES ===== */
  div[data-testid="stAlert"] {
    border-radius: 12px !important;
    font-family: 'Inter', sans-serif !important;
  }
  .stCaption, [data-testid="stCaptionContainer"] {
    color: rgba(255,255,255,0.4) !important;
  }

  /* ===== CAMERA INPUT ===== */
  [data-testid="stCameraInput"] > div {
    border-radius: 14px !important;
    overflow: hidden;
  }

  /* ===== IMAGE GALLERY ===== */
  [data-testid="stImage"] {
    border-radius: 12px;
    overflow: hidden;
  }

  /* ===== MARKDOWN OVERRIDES ===== */
  .main .block-container p, .main .block-container li {
    color: #e8e8ed;
  }
  .main .block-container strong {
    color: #ffb74d;
  }
  .main .block-container code {
    background: rgba(255,183,77,0.1);
    color: #ffb74d;
    padding: 2px 6px;
    border-radius: 6px;
    font-size: 13px;
  }
  h1, h2, h3, h4 {
    color: #e8e8ed !important;
    font-family: 'Inter', sans-serif !important;
  }

  /* ===== SPINNER ===== */
  .stSpinner > div {
    border-top-color: #f57c00 !important;
  }

  /* ===== SCROLLBAR ===== */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 4px; }

  /* ===== HIDE STREAMLIT BRANDING ===== */
  #MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden !important; }
  .viewerBadge_container__r5tak { display: none !important; }

  /* ===== STICKY BOTTOM NAV ===== */
  div[data-testid="stVerticalBlock"]:has(> div > div > div > div > .bottom-nav-marker),
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.bottom-nav-marker) {
      position: fixed !important;
      bottom: 0 !important;
      left: 0 !important;
      width: 100% !important;
      max-width: 100vw !important;
      box-sizing: border-box !important;
      background: rgba(15,17,23,0.95) !important;
      backdrop-filter: blur(10px) !important;
      padding: 12px 15px 25px 15px !important;
      z-index: 9999 !important;
      border-top: 1px solid rgba(255,255,255,0.08) !important;
  }
  .main .block-container {
      padding-bottom: 100px !important;
  }

  /* ===== CLICKABLE CARDS (BUTTON AS CARD) ===== */
  div[data-testid="stVerticalBlock"]:has(> div > div > div > div > .clickable-card-marker) div[data-testid="stButton"] button,
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.clickable-card-marker) div[data-testid="stButton"] button {
      background: rgba(255,255,255,0.04) !important;
      backdrop-filter: blur(12px) !important;
      border: 1px solid rgba(255,183,77,0.2) !important;
      border-radius: 16px !important;
      padding: 16px 20px !important;
      height: auto !important;
      text-align: left !important;
      justify-content: flex-start !important;
      white-space: pre-wrap !important;
      font-size: 14px !important;
      line-height: 1.6 !important;
      color: rgba(255,255,255,0.6) !important;
      display: block !important;
  }
  div[data-testid="stVerticalBlock"]:has(> div > div > div > div > .clickable-card-marker) div[data-testid="stButton"] button p,
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.clickable-card-marker) div[data-testid="stButton"] button p {
      margin: 0 !important;
  }
  div[data-testid="stVerticalBlock"]:has(> div > div > div > div > .clickable-card-marker) div[data-testid="stButton"] button strong,
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.clickable-card-marker) div[data-testid="stButton"] button strong {
      color: #ffb74d !important;
      font-size: 16px !important;
      font-weight: 800 !important;
      display: block !important;
      margin-bottom: 4px !important;
  }
  div[data-testid="stVerticalBlock"]:has(> div > div > div > div > .clickable-card-marker) div[data-testid="stButton"] button:hover,
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.clickable-card-marker) div[data-testid="stButton"] button:hover {
      transform: translateY(-2px) !important;
      box-shadow: 0 8px 25px rgba(245,124,0,0.15) !important;
      border-color: rgba(255,183,77,0.45) !important;
  }
  .bottom-nav-marker, .clickable-card-marker { display: none !important; }

  /* ===== MOBILE ADJUSTMENTS ===== */
  /* Sobrescribe el auto-stack de Streamlit <640px con alta especificidad */
  @media (max-width: 640px) {
    section.main div[data-testid="stHorizontalBlock"],
    [data-testid="stMain"] div[data-testid="stHorizontalBlock"],
    div[data-testid="stHorizontalBlock"][data-testid="stHorizontalBlock"] {
      display: flex !important;
      flex-direction: row !important;
      flex-wrap: nowrap !important;
      gap: 6px !important;
      width: 100% !important;
      max-width: 100% !important;
    }
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
    [data-testid="stMain"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"][data-testid="column"] {
      flex: 1 1 0 !important;
      min-width: 0 !important;
      width: auto !important;
      max-width: 100% !important;
    }
    div.stButton > button {
      font-size: 13px !important;
      padding: 10px 4px !important;
      white-space: normal !important;
      word-break: break-word !important;
    }
  }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------- State init ----------

if "view" not in st.session_state:
    st.session_state.view = "login"
if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "auth_ok" not in st.session_state:
    st.session_state.auth_ok = False
if "fecha_sel" not in st.session_state:
    st.session_state.fecha_sel = date.today()
if "carga_sel" not in st.session_state:
    st.session_state.carga_sel = None
if "tab" not in st.session_state:
    st.session_state.tab = "por_declarar"

APP_PASSWORD = os.getenv("APP_PASSWORD", "")

init_db()
FOTOS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Helpers ----------

def header(titulo: str, mostrar_atras: bool = False, mostrar_sync: bool = False):
    st.markdown(f"<div class='app-header'>{titulo}</div>", unsafe_allow_html=True)
    if mostrar_atras or mostrar_sync:
        cols = st.columns([1, 6, 1])
        with cols[0]:
            if mostrar_atras:
                if st.button("← Volver", key=f"back_{titulo}"):
                    if st.session_state.view == "detalle":
                        st.session_state.view = "lista_cargas"
                    else:
                        st.session_state.view = "selector_fecha"
                    st.rerun()
        with cols[2]:
            if mostrar_sync:
                if st.button("↻ Sync", key=f"sync_{titulo}", help="Sincronizar correos"):
                    with st.spinner("Sincronizando correos de Outlook..."):
                        try:
                            from sync_cargas_imap import main as sync_main
                            result = sync_main()
                            st.session_state["sync_result"] = ("ok",
                                f"Sync OK — {result['correos_procesados']} correos, "
                                f"{result['cargas_nuevas']} cargas, "
                                f"{result['items_nuevos']} items"
                            )
                        except SystemExit as e:
                            st.session_state["sync_result"] = ("error", f"Sync abortado: {e}")
                        except Exception as e:
                            st.session_state["sync_result"] = ("error", f"Error en sync: {e}")
                    st.rerun()


def logout_button():
    with st.sidebar:
        st.write(f"👷 **{st.session_state.usuario}**")
        if st.button("Cerrar sesión"):
            st.session_state.usuario = None
            st.session_state.view = "login"
            st.rerun()


# ---------- Vista Login ----------

def _render_login_header():
    st.markdown("<div class='app-header'>Declaración Daños Andén</div>",
                unsafe_allow_html=True)
    st.markdown(
        "<div class='login-logo'><span class='icon'>🚚</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='login-title'>Declaración de Daños</div>", unsafe_allow_html=True)
    st.markdown("<div class='login-subtitle'>Lastmile · Andén</div>", unsafe_allow_html=True)


def view_password_gate():
    """Paso 1: pedir password compartido antes del selector de operario."""
    _render_login_header()

    if not APP_PASSWORD:
        st.warning(
            "⚠️ APP_PASSWORD no configurado en el entorno. Saltando auth (modo desarrollo)."
        )
        st.session_state.auth_ok = True
        st.rerun()
        return

    with st.form("password_form", clear_on_submit=False):
        pwd = st.text_input(
            "🔒 Password de acceso",
            type="password",
            placeholder="Ingresa el password compartido",
        )
        submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if submitted:
        if pwd == APP_PASSWORD:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Password incorrecto")


def view_login():
    """Paso 2: seleccionar operario (después de pasar el password gate)."""
    _render_login_header()

    usuarios = listar_usuarios_activos()
    if not usuarios:
        st.error("No hay usuarios cargados. Ejecuta `python tools/seed_usuarios.py`")
        return

    nombre = st.selectbox("👷 Selecciona tu nombre", usuarios, key="login_select")
    st.write("")
    if st.button("🚀 Ingresar a Cargas", type="primary", use_container_width=True):
        st.session_state.usuario = nombre
        st.session_state.view = "selector_fecha"
        st.session_state.fecha_sel = date.today()
        st.rerun()

    st.write("")
    if st.button("🛡️ Panel Supervisor", use_container_width=True):
        st.session_state.usuario = nombre
        st.session_state.view = "admin"
        st.rerun()


# ---------- Vista Cargas ----------

# ---------- Bottom Nav Helper ----------

def render_bottom_nav():
    st.markdown("<span class='bottom-nav-marker'></span>", unsafe_allow_html=True)
    fecha_sel = st.session_state.get("fecha_sel", date.today())
    n_pend = len(listar_cargas_por_fecha(fecha_sel, estado="por_declarar"))
    c1, c2 = st.columns(2)
    with c1:
        is_active = st.session_state.tab == "por_declarar"
        label_pend = f"📋 Por declarar ({n_pend})" if n_pend else "📋 Por declarar"
        if st.button(label_pend, key="nav_pd", use_container_width=True, type="primary" if is_active else "secondary"):
            st.session_state.tab = "por_declarar"
            st.session_state.view = "lista_cargas"
            st.rerun()
    with c2:
        is_active = st.session_state.tab == "finalizadas"
        if st.button("✅ Finalizados", key="nav_fin", use_container_width=True, type="primary" if is_active else "secondary"):
            st.session_state.tab = "finalizadas"
            st.session_state.view = "lista_cargas"
            st.rerun()


# ---------- Vista Selección de Fecha ----------

def view_selector_fecha():
    logout_button()
    header("Declaración Andén", mostrar_sync=True)

    if "sync_result" in st.session_state:
        kind, msg = st.session_state["sync_result"]
        del st.session_state["sync_result"]
        if kind == "ok":
            st.success(msg)
        else:
            st.error(msg)

    st.markdown(
        "<div style='text-align:center; margin-top: 30px; margin-bottom: 20px;'>"
        "<h3 style='color:#e8e8ed; font-weight:800;'>📅 Selecciona la fecha</h3>"
        "</div>",
        unsafe_allow_html=True
    )

    fecha = st.session_state.fecha_sel
    hoy = date.today()
    if fecha == hoy:
        fecha_txt = "Hoy"
    elif fecha == hoy - timedelta(days=1):
        fecha_txt = "Ayer"
    elif fecha == hoy + timedelta(days=1):
        fecha_txt = "Mañana"
    else:
        fecha_txt = fecha.strftime("%d/%m/%Y")

    st.markdown(
        f"<div style='text-align:center; margin-bottom: 24px;'>"
        f"<div style='font-size:48px; font-weight:800; color:#ffb74d;'>{fecha_txt}</div>"
        f"<div style='font-size:18px; color:rgba(255,255,255,0.6);'>{fecha.isoformat()}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("◄", key="prev_day", use_container_width=True):
            st.session_state.fecha_sel -= timedelta(days=1)
            st.rerun()
    with c2:
        if st.button("►", key="next_day", use_container_width=True):
            st.session_state.fecha_sel += timedelta(days=1)
            st.rerun()

    st.markdown(
        "<div style='text-align:center; color:rgba(255,255,255,0.4); margin-top: 50px; font-size: 14px;'>"
        "👇 Usa los botones de abajo para ver las cargas de esta fecha."
        "</div>", 
        unsafe_allow_html=True
    )

    with st.container():
        render_bottom_nav()


# ---------- Vista Cargas (Lista) ----------

def view_lista_cargas():
    logout_button()
    
    tab_label = "📋 Por declarar" if st.session_state.tab == "por_declarar" else "✅ Finalizados"
    fecha_txt = st.session_state.fecha_sel.strftime("%d/%m/%Y")
    
    header(f"{tab_label} - {fecha_txt}", mostrar_atras=True)

    st.write("")

    estado_filtro = "por_declarar" if st.session_state.tab == "por_declarar" else "finalizada"
    cargas = listar_cargas_por_fecha(st.session_state.fecha_sel, estado=estado_filtro)

    if not cargas:
        st.markdown(
            "<div class='carga-card' style='text-align:center;padding:32px 20px;'>"
            "<div style='font-size:40px;margin-bottom:12px;'>📭</div>"
            "<div style='color:rgba(255,255,255,0.5);font-size:14px;'>"
            "No hay cargas en este tab para la fecha seleccionada</div></div>",
            unsafe_allow_html=True,
        )
    else:
        for c in cargas:
            badge_txt = ""
            if c["estado"] == "finalizada":
                if c["sin_danos"]: badge_txt = "SIN DAÑOS"
                elif c["enviada_at"]: badge_txt = "ENVIADA"
                else: badge_txt = "FINALIZADA"
            else:
                badge_txt = f"{c['total_danos']}/{c['total_entregas']} DECLARADOS"

            label = f"📦 CARGA: {c['numero_carga']}   [{badge_txt}]\nCD {c['cd'] or '-'} · Andén {c['anden'] or '-'} · {c['total_entregas']} entregas"
            
            with st.container():
                st.markdown("<span class='clickable-card-marker'></span>", unsafe_allow_html=True)
                if st.button(label, key=f"open_{c['numero_carga']}", use_container_width=True):
                    st.session_state.carga_sel = c["numero_carga"]
                    st.session_state.view = "detalle"
                    st.rerun()

    with st.container():
        render_bottom_nav()


# ---------- Vista Detalle de carga ----------

def view_detalle():
    logout_button()
    nc = st.session_state.carga_sel
    if not nc:
        st.session_state.view = "cargas"
        st.rerun()
        return

    carga = obtener_carga(nc)
    if not carga:
        st.error(f"Carga {nc} no encontrada.")
        return

    header(f"CARGA {nc}", mostrar_atras=True)

    # Resumen
    danos_dict = listar_danos_de_carga(nc)
    entregas = listar_entregas_de_carga(nc)
    total_entregas = len(entregas)
    total_danos = len(danos_dict)
    fotos_raw = listar_fotos_de_carga(nc)
    # UI defensiva: ignora filas huérfanas (archivo no existe en disco)
    fotos = [f for f in fotos_raw if _resolver_ruta_foto(f["ruta_archivo"]).exists()]

    # Info card
    st.markdown(
        f"<div class='carga-card' style='padding:12px 16px;'>"
        f"<div class='carga-sub' style='margin:0;'>"
        f"📍 CD <strong>{carga['cd'] or '-'}</strong> · "
        f"Andén <strong>{carga['anden'] or '-'}</strong> · "
        f"Correo <strong>{carga['fecha_correo']}</strong></div></div>",
        unsafe_allow_html=True,
    )

    # Stat chips
    estado_emoji = "🟢" if carga["estado"] == "finalizada" else "🟡"
    fotos_color = "#81c784" if len(fotos) >= MIN_FOTOS else "#ffb74d"
    st.markdown(
        f"""<div class="stat-row">
          <div class="stat-chip"><span class="val">{total_danos}/{total_entregas}</span><span class="lbl">Daños</span></div>
          <div class="stat-chip"><span class="val" style="color:{fotos_color}">{len(fotos)}</span><span class="lbl">Fotos</span></div>
          <div class="stat-chip"><span class="val" style="font-size:14px;">{estado_emoji} {carga['estado'].upper()}</span><span class="lbl">Estado</span></div>
        </div>""",
        unsafe_allow_html=True,
    )

    if carga["estado"] == "finalizada" and not carga["enviada_at"]:
        if st.button("↺ Reabrir carga para editar"):
            reabrir_carga(nc)
            st.rerun()
    elif carga["enviada_at"]:
        st.info("Esta carga ya fue enviada en el correo consolidado. No se puede modificar.")

    # ====== Resumen de daños declarados ======
    if danos_dict:
        cliente_por_entrega = {e["entrega"]: (e["nombre_cliente"] or "-") for e in entregas}
        with st.expander(f"📋 Ver {total_danos} daño(s) declarado(s)", expanded=False):
            for entrega in sorted(danos_dict.keys()):
                tipos = [d["tipo_dano"] for d in danos_dict[entrega]]
                cliente = cliente_por_entrega.get(entrega, "-")
                st.markdown(
                    f"<div style='padding:8px 10px;margin:4px 0;background:rgba(255,183,77,0.08);"
                    f"border-left:3px solid #ffb74d;border-radius:6px;'>"
                    f"<strong style='color:#ffb74d;'>📦 {entrega}</strong> "
                    f"<span style='color:rgba(255,255,255,0.6);font-size:13px;'>· {cliente}</span><br>"
                    f"<span style='color:#e8e8ed;font-size:13px;'>{' · '.join(tipos)}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # Buscador con filtrado en tiempo real
    st.write("---")
    search_key = f"search_{nc}"
    if search_key not in st.session_state:
        st.session_state[search_key] = ""

    def _on_search_change():
        pass  # el rerun es automático al cambiar el widget

    def _clear_search():
        st.session_state[search_key] = ""

    col_s, col_x = st.columns([5, 1])
    with col_s:
        busqueda = st.text_input(
            "🔍 Buscar ENTREGA",
            key=search_key,
            placeholder="Escribe cualquier parte del número...",
            on_change=_on_search_change,
            label_visibility="collapsed",
        ).strip()
    with col_x:
        st.button(
            "✕",
            key=f"clear_{nc}",
            help="Limpiar búsqueda",
            use_container_width=True,
            on_click=_clear_search,
        )

    # Lista de entregas
    bloqueado = carga["estado"] == "finalizada" and carga["enviada_at"] is not None

    if busqueda:
        # Con búsqueda: mostrar todo lo que coincida (el usuario busca algo específico)
        entregas_filtradas = [e for e in entregas if busqueda in str(e["entrega"])]
        st.caption(f"{len(entregas_filtradas)} resultado(s) para \"{busqueda}\"")
    elif not bloqueado:
        # Sin búsqueda y carga activa: solo mostrar las NO declaradas
        entregas_filtradas = [e for e in entregas if e["entrega"] not in danos_dict]
        n_ocultas = len(entregas) - len(entregas_filtradas)
        if n_ocultas:
            st.caption(f"✅ {n_ocultas} entrega(s) con daños ya declarados — ver en resumen de arriba")
    else:
        # Carga finalizada/enviada: mostrar todas (vista de solo lectura)
        entregas_filtradas = entregas

    for e in entregas_filtradas:
        entrega = e["entrega"]
        danos_actuales = danos_dict.get(entrega, [])
        tipos_actuales = [d["tipo_dano"] for d in danos_actuales]
        label_badge = f" — **{', '.join(tipos_actuales)}**" if tipos_actuales else ""

        with st.expander(
            f"📦 {entrega} · {e['nombre_cliente'] or '-'}{label_badge}",
            expanded=False,
        ):
            st.caption(f"Comuna: {e['comuna'] or '-'} · Líneas: {e['lineas']} · Bultos: {e['total_bultos'] or 0:.0f}")

            st.markdown("**Tipo(s) de daño** _(puedes marcar varios)_")
            seleccionados: list[str] = []
            for tipo in TIPOS_DANO:
                marcado = st.checkbox(
                    tipo,
                    value=tipo in tipos_actuales,
                    key=f"chk_{nc}_{entrega}_{tipo}",
                    disabled=bloqueado,
                )
                if marcado:
                    seleccionados.append(tipo)

            col_g, col_d = st.columns(2)
            with col_g:
                if st.button("Guardar", key=f"save_{nc}_{entrega}", disabled=bloqueado, use_container_width=True):
                    set_danos_for_entrega(nc, entrega, seleccionados, st.session_state.usuario)
                    st.rerun()
            with col_d:
                if tipos_actuales and st.button("Eliminar", key=f"del_{nc}_{entrega}", disabled=bloqueado, use_container_width=True):
                    eliminar_dano(nc, entrega)
                    st.rerun()

    # ====== PASO 2: Fotos (después de declarar todos los daños) ======
    st.write("---")
    st.markdown(
        f"<div class='date-nav'>📷 <span>Paso 2: Fotos</span> de la hoja física ({len(fotos)})</div>",
        unsafe_allow_html=True,
    )
    st.caption("Una vez declarados los daños de todas las entregas, sube las fotos aquí.")

    if not bloqueado:
        # Opción A: adjuntar desde galería (multi-archivo) con botón explícito de "Subir"
        upload_seed_key = f"upload_seed_{nc}"
        if upload_seed_key not in st.session_state:
            st.session_state[upload_seed_key] = 0

        uploaded = st.file_uploader(
            "📁 Adjuntar fotos desde el celular",
            type=["jpg", "jpeg", "png", "heic", "heif", "webp"],
            accept_multiple_files=True,
            key=f"upload_{nc}_{st.session_state[upload_seed_key]}",
            help="Selecciona una o varias fotos de la galería",
        )
        if uploaded:
            if st.button(
                f"⬆️ Subir {len(uploaded)} foto(s)",
                key=f"do_upload_{nc}",
                type="primary",
                use_container_width=True,
            ):
                for f in uploaded:
                    uid = uuid.uuid4().hex[:8]
                    ext = Path(f.name).suffix.lower() or ".jpg"
                    filename = f"CARGA_{nc}_{uid}{ext}"
                    ruta = FOTOS_DIR / filename
                    ruta.write_bytes(f.getbuffer())
                    agregar_foto(nc, str(ruta.relative_to(DATA_DIR)), st.session_state.usuario)
                st.session_state[upload_seed_key] += 1  # resetea uploader
                st.rerun()

        # Opción B: tomar foto con la cámara del dispositivo (solo se activa al pulsar el botón)
        cam_key = f"cam_active_{nc}"
        if cam_key not in st.session_state:
            st.session_state[cam_key] = False

        if not st.session_state[cam_key]:
            if st.button("📷 Activar cámara para tomar foto", key=f"cam_btn_{nc}", use_container_width=True):
                st.session_state[cam_key] = True
                st.rerun()
        else:
            col_cam, col_close = st.columns([5, 1])
            with col_close:
                if st.button("✕", key=f"cam_close_{nc}", help="Cerrar cámara", use_container_width=True):
                    st.session_state[cam_key] = False
                    st.rerun()
            foto = st.camera_input("Tomar foto", key=f"cam_{nc}", label_visibility="collapsed")
            if foto is not None:
                uid = uuid.uuid4().hex[:8]
                filename = f"CARGA_{nc}_{uid}.jpg"
                ruta = FOTOS_DIR / filename
                ruta.write_bytes(foto.getbuffer())
                agregar_foto(nc, str(ruta.relative_to(DATA_DIR)), st.session_state.usuario)
                st.session_state[cam_key] = False
                st.rerun()

    # Galería de fotos ya cargadas (colapsada por defecto)
    if fotos:
        with st.expander(f"🖼️ Ver fotos cargadas ({len(fotos)})", expanded=False):
            cols = st.columns(min(3, len(fotos)))
            for i, f in enumerate(fotos):
                with cols[i % 3]:
                    ruta = _resolver_ruta_foto(f["ruta_archivo"])
                    if ruta.exists():
                        try:
                            st.image(str(ruta), use_container_width=True)
                        except Exception:
                            st.caption(f"📎 {ruta.name}")
                    if not bloqueado and st.button("🗑️ Eliminar", key=f"delfoto_{f['id']}", use_container_width=True):
                        path_str = eliminar_foto(f["id"])
                        if path_str:
                            p = _resolver_ruta_foto(path_str)
                            if p.exists():
                                p.unlink()
                        st.rerun()
    else:
        st.markdown(
            "<div class='carga-card' style='text-align:center;padding:24px 20px;'>"
            "<div style='font-size:36px;margin-bottom:8px;'>📸</div>"
            "<div style='color:rgba(255,255,255,0.4);font-size:13px;'>"
            "Aún no hay fotos — adjunta desde galería o toma con la cámara</div></div>",
            unsafe_allow_html=True,
        )

    # Footer: botones de finalización
    if carga["estado"] == "por_declarar":
        st.write("---")
        n_fotos = len(fotos)
        n_danos = total_danos

        c1, c2 = st.columns(2)
        with c1:
            disabled_danos = n_danos == 0 or n_fotos < MIN_FOTOS
            help_danos = None
            if n_danos == 0:
                help_danos = "Declara al menos 1 daño"
            elif n_fotos < MIN_FOTOS:
                help_danos = f"Sube al menos {MIN_FOTOS} foto"
            if st.button(
                f"📤 Enviar daños de Carga {nc}",
                type="primary",
                disabled=disabled_danos,
                help=help_danos,
                use_container_width=True,
            ):
                finalizar_y_appendear(nc, sin_danos=False)
                st.session_state.view = "cargas"
                st.rerun()

        with c2:
            disabled_sin = n_danos > 0 or n_fotos < MIN_FOTOS
            help_sin = None
            if n_danos > 0:
                help_sin = "Hay daños declarados — usa el otro botón"
            elif n_fotos < MIN_FOTOS:
                help_sin = f"Sube al menos {MIN_FOTOS} foto"

            confirm_key = f"confirm_sd_{nc}"
            if st.session_state.get(confirm_key):
                st.warning(f"¿Marcar **{nc}** como **SIN DAÑOS**? No irá al correo consolidado.")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("Sí, confirmar", key=f"yes_sd_{nc}", use_container_width=True):
                        finalizar_y_appendear(nc, sin_danos=True)
                        st.session_state[confirm_key] = False
                        st.session_state.view = "cargas"
                        st.rerun()
                with cc2:
                    if st.button("Cancelar", key=f"no_sd_{nc}", use_container_width=True):
                        st.session_state[confirm_key] = False
                        st.rerun()
            else:
                if st.button(
                    "✓ Carga sin daños",
                    disabled=disabled_sin,
                    help=help_sin,
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = True
                    st.rerun()


def finalizar_y_appendear(numero_carga: str, sin_danos: bool) -> None:
    finalizar_carga(numero_carga, st.session_state.usuario, sin_danos=sin_danos)
    try:
        from append_carga_to_sheet import append_carga
        append_carga(numero_carga)
    except Exception as e:
        st.warning(f"Carga finalizada localmente, pero falló append a Sheets: {e}")


# ---------- Vista Admin ----------

def render_admin():
    st.markdown(
        "<div style='text-align:center;margin:8px 0 16px 0;'>"
        "<div style='font-size:32px;'>🛡️</div>"
        "<div style='font-size:18px;font-weight:700;color:#e8e8ed;'>Panel Supervisor</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    pendientes = cargas_pendientes_de_envio()

    if not pendientes:
        st.markdown(
            "<div class='carga-card' style='text-align:center;padding:32px 20px;'>"
            "<div style='font-size:40px;margin-bottom:12px;'>✅</div>"
            "<div style='color:rgba(255,255,255,0.5);font-size:14px;'>"
            "No hay cargas finalizadas pendientes de envío</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='date-nav'>📤 <span>{len(pendientes)}</span> carga(s) listas para envío</div>",
            unsafe_allow_html=True,
        )
        for c in pendientes:
            danos = listar_danos_de_carga(c["numero_carga"])
            fotos = listar_fotos_de_carga(c["numero_carga"])
            st.markdown(
                f"<div class='carga-card finalizada'>"
                f"<div class='carga-titulo'>{c['numero_carga']}</div>"
                f"<div class='carga-sub'>"
                f"{len(danos)} daño(s) · {len(fotos)} foto(s) · "
                f"por <strong>{c['finalizada_por']}</strong></div></div>",
                unsafe_allow_html=True,
            )

        st.write("---")
        if st.button("📋 Preparar correo consolidado", type="primary", use_container_width=True):
            try:
                from send_consolidado_email import _gather_data
                from collections import defaultdict
                from datetime import date as _date
                import urllib.parse, os as _os

                cargas_data, fotos = _gather_data()
                if not cargas_data:
                    st.info("No hay cargas con daños pendientes de envío.")
                else:
                    hoy = _date.today()
                    fecha_str = hoy.strftime("%d-%m-%Y")
                    asunto = f"Respaldo de Productos declarados con daños de embalaje en andenes {fecha_str}"

                    # Construir HTML agrupando daños por entrega
                    bloques = []
                    for c in cargas_data:
                        grouped = defaultdict(list)
                        for entrega, tipo in c["danos"]:
                            grouped[entrega].append(tipo)
                        filas_html = "".join(
                            f"<tr>"
                            f"<td style='border:1px solid #444;padding:4px 8px;'>{entrega}</td>"
                            f"<td style='border:1px solid #444;padding:4px 8px;'>{' / '.join(tipos)}</td>"
                            f"</tr>"
                            for entrega, tipos in sorted(grouped.items())
                        )
                        bloques.append(f"""
<table style="border-collapse:collapse;margin-bottom:18px;font-family:Arial,sans-serif;font-size:13px;">
  <tr>
    <td style="background:#a9d08e;font-weight:bold;padding:6px 12px;border:1px solid #444;width:140px;">{fecha_str}</td>
    <td style="background:#a9d08e;font-weight:bold;padding:6px 12px;border:1px solid #444;">CARGA:{c['numero_carga']}</td>
  </tr>
  <tr>
    <td style="background:#a9d08e;font-weight:bold;padding:4px 8px;border:1px solid #444;">OP/CL</td>
    <td style="background:#a9d08e;font-weight:bold;padding:4px 8px;border:1px solid #444;">DAÑO</td>
  </tr>
  {filas_html}
</table>""")

                    html = (
                        "<html><body style='font-family:Arial,sans-serif;font-size:13px;'>"
                        "<p>Estimados,</p>"
                        "<p>A continuación, le envío los respaldos de productos identificados con daños de embalaje en andenes:</p>"
                        + "".join(bloques)
                        + "<p>Adjunto fotos de las hojas de carga físicas como respaldo.</p>"
                        "<p>Saludos cordiales.</p>"
                        "</body></html>"
                    )

                    destinatarios = [s.strip() for s in _os.getenv("DESTINATARIOS_DANOS", "").split(",") if s.strip()]
                    mailto = f"mailto:{','.join(destinatarios)}?subject={urllib.parse.quote(asunto)}"

                    st.success(f"✅ {len(cargas_data)} carga(s) con daños · {len(fotos)} foto(s)")
                    st.markdown(f"**Asunto:** `{asunto}`")

                    # Botón abrir Outlook
                    st.markdown(
                        f'<a href="{mailto}" target="_blank" style="display:inline-block;'
                        f'background:#ff6600;color:white;padding:10px 20px;border-radius:8px;'
                        f'text-decoration:none;font-weight:bold;margin-bottom:12px;">'
                        f'📧 Abrir Outlook con asunto y destinatarios</a>',
                        unsafe_allow_html=True,
                    )

                    # Botón copiar HTML al portapapeles via JS
                    html_escaped = html.replace("\\", "\\\\").replace("`", "\\`")
                    st.components.v1.html(f"""
<style>
  #btn-copy {{
    background: #444; color: white; border: none; padding: 10px 20px;
    border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: bold;
    margin-bottom: 8px; width: 100%;
  }}
  #btn-copy:hover {{ background: #555; }}
</style>
<textarea id="html-src" style="position:absolute;left:-9999px;top:-9999px;">{html.replace('<', '&lt;').replace('>', '&gt;')}</textarea>
<button id="btn-copy" onclick="
  var t = document.createElement('textarea');
  t.value = `{html_escaped}`;
  document.body.appendChild(t);
  t.select();
  document.execCommand('copy');
  document.body.removeChild(t);
  this.textContent = '✅ HTML copiado al portapapeles';
  setTimeout(() => this.textContent = '📋 Copiar HTML al portapapeles', 3000);
">📋 Copiar HTML al portapapeles</button>
""", height=60)

                    st.caption("Flujo: Abrí Outlook → nuevo correo → pegá el HTML en el cuerpo (Ctrl+V) → enviá → volvé acá y presioná 'Marcar como enviadas'.")
                    st.markdown("**Vista previa del correo:**")
                    st.markdown(html, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Error generando contenido: {e}")

        if st.button("✅ Marcar como enviadas (envío manual)", use_container_width=True):
            try:
                from send_consolidado_email import _gather_data
                from db import marcar_cargas_enviadas
                cargas_data, _ = _gather_data()
                if not cargas_data:
                    st.info("No hay cargas pendientes de marcar.")
                else:
                    numeros = [c["numero_carga"] for c in cargas_data]
                    marcar_cargas_enviadas(numeros)
                    st.success(f"✅ {len(numeros)} carga(s) marcadas como enviadas: {', '.join(numeros)}")
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

        if st.button("📝 Crear borrador en Outlook", use_container_width=True):
            with st.spinner("Armando correo y guardando borrador..."):
                try:
                    from send_consolidado_email import main as send_main
                    result = send_main(mode="draft")
                    st.success(
                        f"✅ Borrador creado en carpeta '{result.get('folder', 'Drafts')}'. "
                        f"{result['enviadas']} carga(s) · {result['fotos']} foto(s) · "
                        f"{result['destinatarios']} destinatario(s).\n\n"
                        f"Abre Outlook → **Borradores**, revísalo y envíalo manualmente."
                    )
                except Exception as e:
                    st.error(f"Error al crear borrador: {e}")

    # ====== Mantenimiento ======
    st.write("---")
    st.markdown(
        "<div class='date-nav'>🛠️ <span>Mantenimiento</span></div>",
        unsafe_allow_html=True,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔎 Detectar fotos huérfanas", use_container_width=True):
            from limpiar_fotos_huerfanas import escanear_huerfanas
            r = escanear_huerfanas(apply=False)
            if r["huerfanas_total"] == 0:
                st.success("✅ No hay fotos huérfanas. DB limpia.")
            else:
                top = sorted(r["detalle"].items(), key=lambda x: -x[1])[:5]
                detalle_txt = "\n".join(f"- {nc}: {n}" for nc, n in top)
                st.warning(
                    f"⚠️ {r['huerfanas_total']} filas huérfanas en "
                    f"{r['cargas_afectadas']} carga(s). Top 5:\n{detalle_txt}"
                )
    with col_b:
        if st.button("🧹 Limpiar huérfanas", type="secondary", use_container_width=True):
            from limpiar_fotos_huerfanas import escanear_huerfanas
            with st.spinner("Limpiando..."):
                r = escanear_huerfanas(apply=True)
            st.success(
                f"✅ Borradas {r['borradas']} filas huérfanas de "
                f"{r['cargas_afectadas']} carga(s)."
            )
            st.rerun()

    # ====== Recordatorio ======
    st.write("---")
    st.markdown(
        "<div class='date-nav'>🔔 <span>Recordatorio manual</span></div>",
        unsafe_allow_html=True,
    )
    if st.button("📧 Enviar recordatorio de pendientes (hoy)", use_container_width=True):
        from send_reminder_cargas import main as _send_reminder
        with st.spinner("Enviando..."):
            n = _send_reminder()
        if n:
            st.success(f"✅ Recordatorio enviado — {n} carga(s) pendientes mencionadas.")
        else:
            st.info("No hay cargas pendientes hoy. No se envió correo.")


# ---------- Router ----------

if not st.session_state.auth_ok:
    view_password_gate()
elif st.session_state.usuario is None:
    view_login()
elif st.session_state.view == "selector_fecha":
    view_selector_fecha()
elif st.session_state.view == "lista_cargas":
    view_lista_cargas()
elif st.session_state.view == "detalle":
    view_detalle()
elif st.session_state.view == "admin":
    logout_button()
    header("Panel Supervisor", mostrar_atras=True)
    render_admin()
else:
    st.session_state.view = "selector_fecha"
    st.rerun()
