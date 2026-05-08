"""
Gestión de terraf.toml — lectura y escritura de configuración del proyecto.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w  # para escritura

from terraf import __version__

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "proyecto": {
        "nombre": "",
        "creado": str(date.today()),
        "version_terraf": __version__,
    },
    "procesamiento": {
        "umbral_ior": 0.65,
        "umbral_clay": 0.55,
        "buffer_litologia": 500,
        "min_area_cluster": 10,
    },
    "exportacion": {
        "formato_default": "geojson",
        "directorio_salida": "./resultados",
    },
    "database": {
        "ruta": "./terraf.db",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def load(config_path: Path) -> dict[str, Any]:
    """Lee terraf.toml y retorna el diccionario de configuración."""
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def save(config: dict[str, Any], config_path: Path) -> None:
    """Escribe el diccionario de configuración en terraf.toml."""
    with open(config_path, "wb") as f:
        tomli_w.dump(config, f)


def create_default(nombre: str, config_path: Path) -> dict[str, Any]:
    """Crea un terraf.toml con los valores por defecto y el nombre del proyecto."""
    cfg = _deep_copy(DEFAULT_CONFIG)
    cfg["proyecto"]["nombre"] = nombre
    save(cfg, config_path)
    return cfg


def get_value(config: dict[str, Any], key: str) -> Any:
    """
    Lee un valor usando notación de punto (ej: 'procesamiento.umbral_ior').
    Retorna None si la clave no existe.
    """
    parts = key.split(".")
    node = config
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_value(config: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    """
    Establece un valor usando notación de punto. Intenta preservar el tipo
    original (float, int, bool) convirtiendo el string de entrada.
    """
    parts = key.split(".")
    node = config
    for part in parts[:-1]:
        node = node.setdefault(part, {})

    leaf_key = parts[-1]
    existing = node.get(leaf_key)
    node[leaf_key] = _coerce(value, existing)
    return config


def find_config(start: Path | None = None) -> Path | None:
    """Busca terraf.toml subiendo desde el directorio actual."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / "terraf.toml"
        if candidate.exists():
            return candidate
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _deep_copy(obj: Any) -> Any:
    """Copia profunda simple sin importar copy."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj


def _coerce(value: str, existing: Any) -> Any:
    """Convierte un string al tipo del valor existente."""
    if isinstance(existing, bool):
        return value.lower() in ("true", "1", "yes", "si")
    if isinstance(existing, int):
        return int(value)
    if isinstance(existing, float):
        return float(value)
    return value
