"""
Pipeline — Fase 2: Cálculo de índices espectrales.

Carga las bandas desde el path registrado en DB, delega el cálculo a
Spectraf y persiste las estadísticas + raster resultante en la DB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from terraf.db.models import Imagen, IndiceEspectral, Proyecto
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Catálogo de índices
# ──────────────────────────────────────────────────────────────────────────────

def _lazy_catalogue() -> dict:
    """
    Importa las funciones de Spectraf de forma tardía para que el módulo
    pueda cargarse incluso si rasterio/numpy no están instalados.
    """
    from spectraf.indices import (  # noqa: PLC0415
        calculate_clay_ratio,
        calculate_evi,
        calculate_ferrous_minerals_ratio,
        calculate_iron_oxide_ratio,
        calculate_ndvi,
        calculate_ndwi,
        calculate_savi,
    )
    return {
        "ior": {
            "nombre":        "Iron Oxide Ratio",
            "fn":            calculate_iron_oxide_ratio,
            "banda":         "Iron_Oxide_Ratio",
            "formula":       "B4 / B2",
            "umbral_default": 0.65,
        },
        "clay": {
            "nombre":        "Clay Ratio",
            "fn":            calculate_clay_ratio,
            "banda":         "Clay_Ratio",
            "formula":       "B6 / B7",
            "umbral_default": 0.55,
        },
        "ferrous": {
            "nombre":        "Ferrous Minerals",
            "fn":            calculate_ferrous_minerals_ratio,
            "banda":         "Ferrous_Minerals_Ratio",
            "formula":       "B6 / B5",
            "umbral_default": 0.50,
        },
        "ndvi": {
            "nombre":        "NDVI",
            "fn":            calculate_ndvi,
            "banda":         "NDVI",
            "formula":       "(B5 - B4) / (B5 + B4)",
            "umbral_default": 0.20,
        },
        "ndwi": {
            "nombre":        "NDWI",
            "fn":            calculate_ndwi,
            "banda":         "NDWI",
            "formula":       "(B3 - B5) / (B3 + B5)",
            "umbral_default": 0.00,
        },
        "evi": {
            "nombre":        "EVI",
            "fn":            calculate_evi,
            "banda":         "EVI",
            "formula":       "2.5 × (B5-B4) / (B5 + 6×B4 - 7.5×B2 + 1)",
            "umbral_default": 0.20,
        },
        "savi": {
            "nombre":        "SAVI",
            "fn":            calculate_savi,
            "banda":         "SAVI",
            "formula":       "(B5-B4) / (B5+B4+0.5) × 1.5",
            "umbral_default": 0.20,
        },
    }


INDICES_DISPONIBLES = ["ior", "clay", "ferrous", "ndvi", "ndwi", "evi", "savi"]


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IndiceCalculado:
    clave: str                       # "ior", "clay", …
    nombre: str
    formula: str
    umbral: float
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    media: Optional[float] = None
    desv_std: Optional[float] = None
    percentil_25: Optional[float] = None
    percentil_75: Optional[float] = None
    px_sobre_umbral: Optional[int] = None
    pct_sobre_umbral: Optional[float] = None
    ruta_raster: Optional[str] = None
    indice_id: int = -1
    already_existed: bool = False
    error: Optional[str] = None


@dataclass
class IndicesResultado:
    imagen_id: int
    scene_id: str
    indices: list[IndiceCalculado] = field(default_factory=list)

    @property
    def ok(self) -> list[IndiceCalculado]:
        return [i for i in self.indices if i.error is None]

    @property
    def errores(self) -> list[IndiceCalculado]:
        return [i for i in self.indices if i.error is not None]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _load_bands(scene_path: Path) -> tuple[dict, dict]:
    """
    Carga bandas SR B1-B7 con rasterio directamente desde el path de la escena.

    Returns:
        (bands_dict, spatial_meta) donde spatial_meta contiene crs, transform
        y profile para guardar rasters de salida.
    """
    import rasterio  # noqa: PLC0415

    bands: dict[str, np.ndarray] = {}
    profile: dict = {}

    for b in ["B1", "B2", "B3", "B4", "B5", "B6", "B7"]:
        candidate = scene_path / f"{scene_path.name}_SR_{b}.TIF"
        if candidate.exists():
            with rasterio.open(candidate) as src:
                bands[b] = src.read(1).astype(float)
                if not profile:
                    profile = src.profile.copy()
                    profile.update(dtype="float32", count=1, nodata=float("nan"))

    return bands, profile


def _compute_stats(arr: np.ndarray, umbral: float) -> dict:
    """Estadísticas descriptivas sobre píxeles válidos (no-NaN)."""
    valid = arr[np.isfinite(arr)]
    if len(valid) == 0:
        return {}
    px_sobre = int(np.sum(valid > umbral))
    return {
        "min_val":         float(np.min(valid)),
        "max_val":         float(np.max(valid)),
        "media":           float(np.mean(valid)),
        "desv_std":        float(np.std(valid)),
        "percentil_25":    float(np.percentile(valid, 25)),
        "percentil_75":    float(np.percentile(valid, 75)),
        "px_sobre_umbral": px_sobre,
        "pct_sobre_umbral": float(px_sobre / len(valid) * 100),
    }


def _save_raster(arr: np.ndarray, profile: dict, out_path: Path) -> None:
    """Guarda un array 2-D como GeoTIFF float32."""
    import rasterio  # noqa: PLC0415

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr.astype("float32"), 1)


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def calcular_indices(
    db_path: Path,
    claves: Optional[list[str]] = None,
    umbrales: Optional[dict[str, float]] = None,
    guardar_rasters: bool = True,
    forzar: bool = False,
    on_index: Optional[Callable[[str], None]] = None,
) -> IndicesResultado:
    """
    Calcula índices espectrales para la imagen registrada en el proyecto.

    Args:
        db_path:        Ruta al archivo terraf.db.
        claves:         Lista de claves a calcular; None = todas.
        umbrales:       Dict {clave: umbral} para sobreescribir defaults.
        guardar_rasters: Si True, guarda cada índice como GeoTIFF en resultados/.
        forzar:         Si True, recalcula aunque ya exista en la DB.
        on_index:       Callback(clave) llamado antes de calcular cada índice.

    Returns:
        IndicesResultado con un IndiceCalculado por cada índice.

    Raises:
        RuntimeError: Si no hay imagen registrada en el proyecto.
        FileNotFoundError: Si la ruta de la imagen no existe en disco.
    """
    catalogo = _lazy_catalogue()
    claves_a_calcular = claves or list(catalogo.keys())
    umbrales = umbrales or {}

    # ── Obtener imagen de la DB ───────────────────────────────────────────────
    with open_session(db_path) as session:
        imagen = (
            session.query(Imagen)
            .join(Proyecto)
            .order_by(Imagen.cargada_en.desc())
            .first()
        )
        if imagen is None:
            raise RuntimeError(
                "No hay imagen registrada en este proyecto.\n"
                "Ejecuta 'terraf load <ruta>' primero."
            )
        imagen_id = imagen.id
        scene_id  = imagen.scene_id
        ruta_archivo = imagen.ruta_archivo

    scene_path = Path(ruta_archivo)
    if not scene_path.exists():
        raise FileNotFoundError(
            f"La ruta de la imagen ya no existe:\n  {scene_path}\n"
            "Verifica que el directorio de la escena no haya sido movido."
        )

    resultado = IndicesResultado(imagen_id=imagen_id, scene_id=scene_id)

    # ── Cargar bandas una sola vez (caro en memoria) ──────────────────────────
    try:
        bands, profile = _load_bands(scene_path)
    except ImportError:
        for clave in claves_a_calcular:
            info = catalogo[clave]
            resultado.indices.append(IndiceCalculado(
                clave=clave,
                nombre=info["nombre"],
                formula=info["formula"],
                umbral=umbrales.get(clave, info["umbral_default"]),
                error="rasterio no está instalado. Instala con: pip install rasterio",
            ))
        return resultado

    if not bands:
        for clave in claves_a_calcular:
            info = catalogo[clave]
            resultado.indices.append(IndiceCalculado(
                clave=clave,
                nombre=info["nombre"],
                formula=info["formula"],
                umbral=umbrales.get(clave, info["umbral_default"]),
                error=f"No se encontraron bandas en {scene_path}",
            ))
        return resultado

    # Construir SatelliteImage de Spectraf
    from spectraf.core import SatelliteImage  # noqa: PLC0415
    sat_image = SatelliteImage(
        bands=bands,
        metadata={"scene_id": scene_id},
        sensor_type="landsat9",
    )

    # Directorio de salida para rasters
    resultados_dir = db_path.parent / "resultados" / "indices"

    # ── Calcular cada índice ──────────────────────────────────────────────────
    for clave in claves_a_calcular:
        if clave not in catalogo:
            resultado.indices.append(IndiceCalculado(
                clave=clave, nombre=clave, formula="", umbral=0.0,
                error=f"Índice '{clave}' no reconocido.",
            ))
            continue

        info    = catalogo[clave]
        umbral  = umbrales.get(clave, info["umbral_default"])

        # Idempotencia (a menos que --force)
        with open_session(db_path) as session:
            existing = (
                session.query(IndiceEspectral)
                .filter_by(imagen_id=imagen_id, nombre_indice=clave)
                .first()
            )
            if existing is not None and not forzar:
                resultado.indices.append(IndiceCalculado(
                    clave=clave,
                    nombre=info["nombre"],
                    formula=info["formula"],
                    umbral=existing.umbral or umbral,
                    min_val=existing.min_val,
                    max_val=existing.max_val,
                    media=existing.media,
                    desv_std=existing.desv_std,
                    percentil_25=existing.percentil_25,
                    percentil_75=existing.percentil_75,
                    px_sobre_umbral=existing.px_sobre_umbral,
                    pct_sobre_umbral=existing.pct_sobre_umbral,
                    ruta_raster=existing.ruta_raster,
                    indice_id=existing.id,
                    already_existed=True,
                ))
                continue

        # Notificar progreso solo para índices que se van a calcular
        if on_index is not None:
            on_index(clave)

        # ── Calcular ──────────────────────────────────────────────────────────
        try:
            index_image = info["fn"](sat_image)
            arr = index_image.get_band(info["banda"])
        except Exception as exc:
            resultado.indices.append(IndiceCalculado(
                clave=clave, nombre=info["nombre"], formula=info["formula"],
                umbral=umbral, error=str(exc),
            ))
            continue

        stats = _compute_stats(arr, umbral)

        # ── Guardar raster ────────────────────────────────────────────────────
        ruta_raster: Optional[str] = None
        if guardar_rasters and profile:
            try:
                out_path = resultados_dir / f"{scene_id}_{clave}.TIF"
                _save_raster(arr, profile, out_path)
                ruta_raster = str(out_path)
            except Exception:
                pass  # raster opcional; no abortar si falla

        # ── Persistir en DB ───────────────────────────────────────────────────
        with open_session(db_path) as session:
            # Si existe y es --force, eliminar el anterior
            old = (
                session.query(IndiceEspectral)
                .filter_by(imagen_id=imagen_id, nombre_indice=clave)
                .first()
            )
            if old is not None:
                session.delete(old)
                session.flush()

            rec = IndiceEspectral(
                imagen_id=imagen_id,
                nombre_indice=clave,
                formula=info["formula"],
                umbral=umbral,
                ruta_raster=ruta_raster,
                **stats,
            )
            session.add(rec)
            session.flush()
            indice_id = rec.id

        resultado.indices.append(IndiceCalculado(
            clave=clave,
            nombre=info["nombre"],
            formula=info["formula"],
            umbral=umbral,
            indice_id=indice_id,
            ruta_raster=ruta_raster,
            **stats,
        ))

    return resultado
