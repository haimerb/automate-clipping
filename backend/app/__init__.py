"""ClipForge backend.

Carga el archivo .env (raíz del repo o backend/) ANTES de importar cualquier
módulo de la app, para que db/auth lean las variables de entorno a tiempo.
load_dotenv NO sobreescribe variables ya definidas en el entorno.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_APP_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _APP_DIR.parent
_REPO_ROOT = _BACKEND_DIR.parent

load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_BACKEND_DIR / ".env")
