"""
Pipeline — Fase 0b: Carga de datos geológicos SGM.

Escanea un directorio en busca de shapefiles, detecta el tipo de capa
por nombre de archivo, y persiste `DatoGeologico` + `FeatureGeologico`
en la base de datos del proyecto.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from terraf.db.models import DatoGeologico, FeatureGeologico, Proyecto
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de capa reconocidos
# ──────────────────────────────────────────────────────────────────────────────

# Mapeo de palabras clave → nombre canónico de capa
_LAYER_KEYWORDS: dict[str, list[str]] = {
    "litologia":        ["litolog", "litho"],
    "geoquimica":       ["geoqu", "geoch"],
    "inventarios":      ["inventar", "miner", "sitio"],
    "campo_magnetico":  ["magnet", "campo_mag", "campmag"],
    "geocronologia":    ["geocron", "chronol"],
    "fallas":           ["falla", "fault"],
    "estructuras":      ["estruct", "struct"],
}

CAPAS_SOPORTADAS = list(_LAYER_KEYWORDS.keys())


def _detect_layer_type(filename: str) -> str:
    """Detecta el tipo de capa a partir del nombre del archivo."""
    lower = filename.lower()
    for capa, keywords in _LAYER_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return capa
    return "otro"


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CapaCargada:
    """Resultado de cargar una capa geológica."""
    capa: str                       # tipo canónico
    ruta: Path
    num_features: int
    crs: Optional[str]
    carta_id: Optional[str]
    dato_geologico_id: int
    already_existed: bool = False
    error: Optional[str] = None     # mensaje de error si la carga falló


@dataclass
class GeologiaCargada:
    """Resultado global de `load_geology_to_db`."""
    capas: list[CapaCargada] = field(default_factory=list)

    @property
    def total_features(self) -> int:
        return sum(c.num_features for c in self.capas if c.error is None)

    @property
    def capas_ok(self) -> list[CapaCargada]:
        return [c for c in self.capas if c.error is None]

    @property
    def capas_error(self) -> list[CapaCargada]:
        return [c for c in self.capas if c.error is not None]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _extract_carta_id(path: Path) -> Optional[str]:
    """
    Intenta inferir el ID de carta del directorio.

    Estrategias (en orden):
    1. Nombre del directorio si tiene forma alfanumérica tipo 'A18022026162831O'.
    2. Buscar patrón 'G\\d+_\\d+' en nombre de archivos shp (ej: G13_5).
    3. Retorna None si no puede inferirlo.
    """
    # Estrategia 1: nombre del directorio
    name = path.name
    if re.match(r"^[A-Z]\d{14}[A-Z]$", name):
        return name

    # Estrategia 2: patrón en archivos SHP
    for shp in path.rglob("*.shp"):
        m = re.search(r"(G\d+_\d+)", shp.name)
        if m:
            return m.group(1)

    return None


def _load_shapefile(
    shp_path: Path,
) -> tuple[int, Optional[str], list[dict]]:
    """
    Lee un shapefile con geopandas.

    Returns:
        (num_features, crs_string, lista_de_features_como_dict)

    Raises:
        ImportError si geopandas no está disponible.
        Exception  si el archivo está corrupto o no se puede leer.
    """
    import geopandas as gpd  # noqa: PLC0415

    gdf = gpd.read_file(shp_path)
    crs = gdf.crs.to_string() if gdf.crs else None
    features: list[dict] = []

    for _, row in gdf.iterrows():
        geom = row.geometry
        attrs = {
            col: (
                str(row[col])
                if not hasattr(row[col], "__geo_interface__")
                else None
            )
            for col in gdf.columns
            if col != "geometry"
        }
        features.append({
            "geometria_wkt": geom.wkt if geom is not None else None,
            "atributos": attrs,
        })

    return len(gdf), crs, features


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def scan_sgm_directory(ruta: Path) -> list[tuple[str, Path]]:
    """
    Escanea el directorio buscando shapefiles y retorna lista de (capa, ruta).
    Solo incluye archivos .shp (ignora .dbf, .prj, etc.).
    """
    ruta = Path(ruta).resolve()
    found: list[tuple[str, Path]] = []
    for shp in sorted(ruta.rglob("*.shp")):
        capa = _detect_layer_type(shp.name)
        found.append((capa, shp))
    return found


def load_geology_to_db(
    ruta: Path,
    db_path: Path,
    carta_id: Optional[str] = None,
    capas_filtro: Optional[list[str]] = None,
    on_layer: Optional[object] = None,  # callback(capa: str) para progreso
) -> GeologiaCargada:
    """
    Carga datos geológicos SGM en la base de datos del proyecto.

    Flujo por cada shapefile encontrado:
    1. Detecta el tipo de capa.
    2. Verifica idempotencia (capa + ruta ya registrada).
    3. Lee con geopandas.
    4. Persiste `DatoGeologico` + `FeatureGeologico`.

    Args:
        ruta:         Directorio raíz con los shapefiles SGM.
        db_path:      Ruta al archivo terraf.db.
        carta_id:     ID de carta (autodetectado si no se indica).
        capas_filtro: Lista de tipos de capa a cargar; None = todas.
        on_layer:     Callable(capa_name: str) llamado antes de cargar cada capa.

    Returns:
        GeologiaCargada con la lista de CapaCargada.

    Raises:
        FileNotFoundError: Si la ruta no existe.
        ValueError:        Si no se encuentran shapefiles.
        RuntimeError:      Si la DB no contiene ningún proyecto.
    """
    ruta = Path(ruta).resolve()

    # ── Validar ruta ──────────────────────────────────────────────────────────
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró la ruta: {ruta}")
    if not ruta.is_dir():
        raise ValueError(f"La ruta debe ser un directorio: {ruta}")

    # ── Descubrir shapefiles ──────────────────────────────────────────────────
    disponibles = scan_sgm_directory(ruta)
    if not disponibles:
        raise ValueError(
            f"No se encontraron archivos .shp en:\n  {ruta}\n"
            "Verifica que la ruta contenga datos SGM descomprimidos."
        )

    # Aplicar filtro de capas si se especificó
    if capas_filtro:
        disponibles = [(c, p) for c, p in disponibles if c in capas_filtro]
        if not disponibles:
            raise ValueError(
                f"Ninguna de las capas solicitadas ({capas_filtro}) fue "
                f"encontrada en el directorio."
            )

    # Inferir carta_id si no se proveyó
    carta = carta_id or _extract_carta_id(ruta)

    resultado = GeologiaCargada()

    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        if proyecto is None:
            raise RuntimeError(
                "No se encontró el proyecto en la base de datos. "
                "Ejecuta 'terraf init' primero."
            )

        for capa, shp_path in disponibles:
            # Notificar progreso
            if on_layer is not None:
                on_layer(capa)

            # ── Idempotencia ──────────────────────────────────────────────────
            existing = (
                session.query(DatoGeologico)
                .filter_by(
                    proyecto_id=proyecto.id,
                    ruta_archivo=str(shp_path),
                )
                .first()
            )
            if existing is not None:
                resultado.capas.append(CapaCargada(
                    capa=existing.capa,
                    ruta=shp_path,
                    num_features=existing.num_features or 0,
                    crs=existing.crs,
                    carta_id=existing.carta_id,
                    dato_geologico_id=existing.id,
                    already_existed=True,
                ))
                continue

            # ── Leer shapefile ────────────────────────────────────────────────
            try:
                num_features, crs, features = _load_shapefile(shp_path)
            except ImportError:
                resultado.capas.append(CapaCargada(
                    capa=capa,
                    ruta=shp_path,
                    num_features=0,
                    crs=None,
                    carta_id=carta,
                    dato_geologico_id=-1,
                    error=(
                        "geopandas no está instalado. "
                        "Instala con: pip install geopandas"
                    ),
                ))
                continue
            except Exception as exc:
                resultado.capas.append(CapaCargada(
                    capa=capa,
                    ruta=shp_path,
                    num_features=0,
                    crs=None,
                    carta_id=carta,
                    dato_geologico_id=-1,
                    error=str(exc),
                ))
                continue

            # ── Persistir DatoGeologico ───────────────────────────────────────
            dato = DatoGeologico(
                proyecto_id=proyecto.id,
                carta_id=carta,
                capa=capa,
                num_features=num_features,
                crs=crs,
                ruta_archivo=str(shp_path),
            )
            session.add(dato)
            session.flush()  # obtener dato.id antes del commit

            # ── Persistir FeatureGeologico ────────────────────────────────────
            for feat in features:
                fg = FeatureGeologico(
                    dato_geologico_id=dato.id,
                    geometria_wkt=feat["geometria_wkt"],
                    atributos_json=json.dumps(feat["atributos"], ensure_ascii=False),
                )
                session.add(fg)

            resultado.capas.append(CapaCargada(
                capa=capa,
                ruta=shp_path,
                num_features=num_features,
                crs=crs,
                carta_id=carta,
                dato_geologico_id=dato.id,
                already_existed=False,
            ))

    return resultado
