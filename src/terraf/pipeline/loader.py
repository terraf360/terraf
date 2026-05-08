"""
Pipeline — Fase 0a: Carga de imagen satelital.

Lee los metadatos de un directorio Landsat 9 (solo cabecera, sin cargar
bandas en RAM) y persiste un registro `Imagen` en la base de datos.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from terraf.db.models import Imagen, Proyecto
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ImagenCargada:
    """Resumen de una imagen registrada (o ya existente) en la DB."""
    imagen_id: int
    scene_id: str
    sensor: str
    fecha_adquisicion: Optional[str]
    crs: Optional[str]
    ancho_px: Optional[int]
    alto_px: Optional[int]
    resolucion_m: Optional[float]
    bandas: list[str] = field(default_factory=list)
    already_existed: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _detect_sensor(path: Path) -> str:
    """Detecta el sensor a partir del nombre del directorio o archivos."""
    name = path.name.upper()
    if name.startswith("LC09") or name.startswith("LC08"):
        return "Landsat 9 L2SP"
    if name.startswith("S2"):
        return "Sentinel-2 L2A"
    # Fallback: buscar archivos de banda
    if any(path.glob("*_SR_B*.TIF")):
        return "Landsat 9 L2SP"
    return "Desconocido"


def _parse_mtl(path: Path) -> dict:
    """
    Lee el archivo MTL de Landsat y extrae los campos que nos interesan.
    Retorna dict vacío si no se encuentra el MTL.
    """
    mtl_files = list(path.glob("*_MTL.txt"))
    if not mtl_files:
        mtl_files = list(path.glob("*_MTL.json"))  # Landsat Collection 2 también tiene JSON

    if not mtl_files:
        return {}

    meta: dict = {}
    mtl = mtl_files[0]

    if mtl.suffix.lower() == ".json":
        try:
            data = json.loads(mtl.read_text(encoding="utf-8", errors="replace"))
            attrs = (
                data.get("LANDSAT_METADATA_FILE", {})
                    .get("IMAGE_ATTRIBUTES", {})
            )
            meta["fecha_adquisicion"] = attrs.get("DATE_ACQUIRED")
        except Exception:
            pass
        return meta

    # Formato texto (KEY = VALUE)
    with open(mtl, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"')
            if key == "DATE_ACQUIRED":
                meta["fecha_adquisicion"] = val
            elif key == "SPACECRAFT_ID":
                meta["spacecraft"] = val
            elif key == "SENSOR_ID":
                meta["sensor_id"] = val

    return meta


def _read_spatial_meta(path: Path) -> dict:
    """
    Abre la primera banda Landsat con rasterio para leer la cabecera espacial.
    No carga datos de píxeles en memoria. Retorna dict vacío si falla.
    """
    try:
        import rasterio  # noqa: PLC0415 — importación tardía para no fallar si no está instalado
    except ImportError:
        return {}

    band_files = sorted(path.glob("*_SR_B*.TIF"))
    if not band_files:
        return {}

    try:
        with rasterio.open(band_files[0]) as src:
            bounds = src.bounds
            return {
                "crs": src.crs.to_string() if src.crs else None,
                "ancho_px": src.width,
                "alto_px": src.height,
                "resolucion_m": float(src.res[0]),
                "bounds_json": json.dumps({
                    "left": bounds.left,
                    "bottom": bounds.bottom,
                    "right": bounds.right,
                    "top": bounds.top,
                }),
                "transform_json": json.dumps(list(src.transform)),
            }
    except Exception:
        return {}


def _list_bands(path: Path) -> list[str]:
    """Lista las bandas SR disponibles ordenadas (B1, B2, …)."""
    bandas: list[str] = []
    for bf in sorted(path.glob("*_SR_B*.TIF")):
        m = re.search(r"SR_(B\d+)", bf.name)
        if m:
            bandas.append(m.group(1))
    return bandas


# ──────────────────────────────────────────────────────────────────────────────
# Función principal
# ──────────────────────────────────────────────────────────────────────────────

def load_image_to_db(
    ruta: Path,
    db_path: Path,
    sensor_override: Optional[str] = None,
    nombre: Optional[str] = None,
) -> ImagenCargada:
    """
    Registra una imagen satelital en la base de datos del proyecto.

    Pasos:
    1. Valida que la ruta sea un directorio accesible.
    2. Detecta el sensor (o usa el override).
    3. Lee metadatos del MTL (sin cargar píxeles).
    4. Lee cabecera espacial de la primera banda.
    5. Valida que existan archivos de bandas.
    6. Persiste `Imagen` en la DB de forma idempotente.

    Args:
        ruta:            Directorio de la escena (ej: LC09_L2SP_031042_…/).
        db_path:         Ruta al archivo terraf.db.
        sensor_override: Sobreescribe la detección automática de sensor.
        nombre:          Alias descriptivo (no se persiste aún, reservado).

    Returns:
        ImagenCargada con todos los metadatos leídos y `already_existed`
        indicando si ya existía en la DB.

    Raises:
        FileNotFoundError: Si la ruta no existe.
        ValueError:        Si no se encuentran archivos de bandas.
        RuntimeError:      Si la DB no contiene ningún proyecto.
    """
    ruta = Path(ruta).resolve()

    # ── 1. Validar ruta ───────────────────────────────────────────────────────
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró la ruta: {ruta}")
    if not ruta.is_dir():
        raise ValueError(
            f"La ruta debe ser un directorio con los archivos de la imagen.\n"
            f"  Ruta proporcionada: {ruta}"
        )

    # ── 2. Detectar sensor y scene_id ─────────────────────────────────────────
    scene_id = ruta.name
    sensor = sensor_override or _detect_sensor(ruta)

    # ── 3. Leer MTL ───────────────────────────────────────────────────────────
    mtl = _parse_mtl(ruta)
    fecha = mtl.get("fecha_adquisicion")

    # ── 4. Metadatos espaciales (cabecera de la primera banda) ─────────────────
    spatial = _read_spatial_meta(ruta)

    # ── 5. Validar que existan bandas ─────────────────────────────────────────
    bandas = _list_bands(ruta)
    if not bandas:
        raise ValueError(
            f"No se encontraron archivos de bandas (*_SR_B*.TIF) en:\n"
            f"  {ruta}\n"
            f"Verifica que la imagen esté descomprimida y sea una escena "
            f"Landsat 9 Level-2 Surface Reflectance."
        )

    # ── 6. Persistir en DB (idempotente) ──────────────────────────────────────
    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        if proyecto is None:
            raise RuntimeError(
                "No se encontró el proyecto en la base de datos. "
                "Ejecuta 'terraf init' primero."
            )

        # Idempotencia: si ya existe la misma escena, devolvemos sin duplicar
        existing = (
            session.query(Imagen)
            .filter_by(proyecto_id=proyecto.id, scene_id=scene_id)
            .first()
        )
        if existing is not None:
            return ImagenCargada(
                imagen_id=existing.id,
                scene_id=existing.scene_id,
                sensor=existing.sensor,
                fecha_adquisicion=existing.fecha_adquisicion,
                crs=existing.crs,
                ancho_px=existing.ancho_px,
                alto_px=existing.alto_px,
                resolucion_m=existing.resolucion_m,
                bandas=json.loads(existing.bandas_json) if existing.bandas_json else [],
                already_existed=True,
            )

        imagen = Imagen(
            proyecto_id=proyecto.id,
            scene_id=scene_id,
            sensor=sensor,
            fecha_adquisicion=fecha,
            crs=spatial.get("crs"),
            ancho_px=spatial.get("ancho_px"),
            alto_px=spatial.get("alto_px"),
            resolucion_m=spatial.get("resolucion_m"),
            bounds_json=spatial.get("bounds_json"),
            transform_json=spatial.get("transform_json"),
            ruta_archivo=str(ruta),
            bandas_json=json.dumps(bandas),
        )
        session.add(imagen)
        session.flush()
        imagen_id = imagen.id

    return ImagenCargada(
        imagen_id=imagen_id,
        scene_id=scene_id,
        sensor=sensor,
        fecha_adquisicion=fecha,
        crs=spatial.get("crs"),
        ancho_px=spatial.get("ancho_px"),
        alto_px=spatial.get("alto_px"),
        resolucion_m=spatial.get("resolucion_m"),
        bandas=bandas,
        already_existed=False,
    )
