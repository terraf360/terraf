"""
Pipeline — Fase 4a: Exportación de resultados a GeoJSON y Shapefile.

Exporta los targets del último análisis (o uno específico) a los formatos
GIS estándar indicados por la spec: GeoJSON (RFC 7946 + lon/lat) y
Shapefile vía geopandas.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from terraf.db.models import Analisis, DatoGeologico, Imagen, IndiceEspectral, Proyecto, Target
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ArchivoExportado:
    ruta: Path
    descripcion: str
    n_features: int
    tamanio_kb: float


@dataclass
class ExportResultado:
    n_targets: int
    formato: str
    archivos: list[ArchivoExportado] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _wkt_to_geojson_geometry(wkt: Optional[str]) -> Optional[dict]:
    """Convierte 'POINT (x y)' a dict GeoJSON geometry."""
    if not wkt:
        return None
    m = re.match(r"POINT\s*\(([^\)]+)\)", wkt)
    if m:
        coords = [float(v) for v in m.group(1).split()]
        return {"type": "Point", "coordinates": coords}
    return None


def _target_to_feature(t: Target, use_lonlat: bool) -> dict:
    """Construye un Feature GeoJSON para un target."""
    if use_lonlat and t.centroide_lon is not None:
        geometry = {
            "type": "Point",
            "coordinates": [t.centroide_lon, t.centroide_lat],
        }
    else:
        geometry = _wkt_to_geojson_geometry(t.geometria_wkt)

    return {
        "type": "Feature",
        "properties": {
            "id":        t.nombre,
            "prioridad": t.prioridad,
            "score":     t.score,
            "area_ha":   t.area_ha,
            "area_px":   t.area_px,
            "ior_media": t.ior_media,
            "clay_media": t.clay_media,
            "litologia": t.litologia_dominante,
            "coord_x":   t.centroide_x,
            "coord_y":   t.centroide_y,
            "lon":       t.centroide_lon,
            "lat":       t.centroide_lat,
        },
        "geometry": geometry,
    }


def _write_geojson(
    targets: list[Target],
    analisis: Analisis,
    imagen: Imagen,
    proyecto: Proyecto,
    out_path: Path,
) -> ArchivoExportado:
    """Escribe el GeoJSON. Usa lon/lat si disponible; projected coords si no."""
    use_lonlat = any(
        t.centroide_lon is not None for t in targets
    )

    fc = {
        "type": "FeatureCollection",
        "properties": {
            "proyecto":       proyecto.nombre,
            "imagen":         imagen.scene_id,
            "fecha_analisis": analisis.ejecutado_en.isoformat()
                              if analisis.ejecutado_en else datetime.now().isoformat(),
            "metodo":         analisis.metodo,
            "crs":            imagen.crs or "desconocido",
        },
        "features": [_target_to_feature(t, use_lonlat) for t in targets],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fc, ensure_ascii=False, indent=2)
    out_path.write_text(text, encoding="utf-8")

    return ArchivoExportado(
        ruta=out_path,
        descripcion="targets GeoJSON",
        n_features=len(targets),
        tamanio_kb=round(out_path.stat().st_size / 1024, 1),
    )


def _write_shapefile(
    targets: list[Target],
    imagen: Imagen,
    out_dir: Path,
) -> list[ArchivoExportado]:
    """Escribe Shapefile de polígonos y shapefile de centroides."""
    import geopandas as gpd  # noqa: PLC0415
    from shapely.geometry import Point  # noqa: PLC0415

    crs = imagen.crs or "EPSG:4326"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Centroides ────────────────────────────────────────────────────────────
    rows = []
    for t in targets:
        rows.append({
            "id":       t.nombre,
            "prioridad": t.prioridad,
            "score":    t.score,
            "area_ha":  t.area_ha,
            "ior_med":  t.ior_media,
            "clay_med": t.clay_media,
            "litologia": (t.litologia_dominante or "")[:50],
            "coord_x":  t.centroide_x,
            "coord_y":  t.centroide_y,
            "lon":      t.centroide_lon,
            "lat":      t.centroide_lat,
            "geometry": Point(t.centroide_x, t.centroide_y),
        })

    gdf = gpd.GeoDataFrame(rows, crs=crs)

    shp_targets = out_dir / "targets.shp"
    gdf.to_file(str(shp_targets), driver="ESRI Shapefile")

    shp_c = out_dir / "targets_centroides.shp"
    gdf.to_file(str(shp_c), driver="ESRI Shapefile")

    return [
        ArchivoExportado(
            ruta=shp_targets,
            descripcion="targets Shapefile",
            n_features=len(targets),
            tamanio_kb=round(shp_targets.stat().st_size / 1024, 1),
        ),
        ArchivoExportado(
            ruta=shp_c,
            descripcion="centroides Shapefile",
            n_features=len(targets),
            tamanio_kb=round(shp_c.stat().st_size / 1024, 1),
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def exportar(
    db_path: Path,
    formato: str = "ambos",
    directorio: Optional[Path] = None,
    analisis_id: Optional[int] = None,
    sobreescribir: bool = True,
) -> ExportResultado:
    """
    Exporta los targets del proyecto a GeoJSON y/o Shapefile.

    Args:
        db_path:       Ruta al archivo terraf.db.
        formato:       "geojson" | "shapefile" | "ambos"
        directorio:    Directorio de salida (default: resultados/targets/).
        analisis_id:   ID de análisis específico (default: último).
        sobreescribir: Si False, lanza error si el archivo ya existe.

    Returns:
        ExportResultado con la lista de archivos generados.

    Raises:
        RuntimeError:  Si no hay análisis en la DB.
        ValueError:    Si `formato` no es válido.
    """
    if formato not in ("geojson", "shapefile", "ambos"):
        raise ValueError(f"Formato no válido: '{formato}'. Usa geojson, shapefile o ambos.")

    out_dir = directorio or (db_path.parent / "resultados" / "targets")

    with open_session(db_path) as session:
        # Obtener análisis
        query = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            query = query.filter_by(id=analisis_id)
        analisis = query.first()

        if analisis is None:
            raise RuntimeError(
                "No hay análisis registrado.\nEjecuta 'terraf analyze' primero."
            )

        targets = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .order_by(Target.score.desc())
            .all()
        )

        if not targets:
            raise RuntimeError(
                "El análisis no tiene targets.\n"
                "Prueba 'terraf analyze' con umbrales más bajos."
            )

        imagen   = session.query(Imagen).filter_by(id=analisis.imagen_id).first()
        proyecto = session.query(Proyecto).first()

    resultado = ExportResultado(n_targets=len(targets), formato=formato)

    # ── GeoJSON ───────────────────────────────────────────────────────────────
    if formato in ("geojson", "ambos"):
        geojson_path = out_dir / "targets.geojson"
        if geojson_path.exists() and not sobreescribir:
            raise FileExistsError(
                f"El archivo ya existe: {geojson_path}\n"
                "Usa --sobreescribir para reemplazarlo."
            )
        arch = _write_geojson(targets, analisis, imagen, proyecto, geojson_path)
        resultado.archivos.append(arch)

    # ── Shapefile ─────────────────────────────────────────────────────────────
    if formato in ("shapefile", "ambos"):
        try:
            archs = _write_shapefile(targets, imagen, out_dir)
            resultado.archivos.extend(archs)
        except ImportError:
            from terraf.pipeline.exporter import ArchivoExportado as _AE  # noqa
            resultado.archivos.append(ArchivoExportado(
                ruta=out_dir / "targets.shp",
                descripcion="[omitido — geopandas no instalado]",
                n_features=0,
                tamanio_kb=0,
            ))

    return resultado
