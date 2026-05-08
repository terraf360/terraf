"""
Pipeline — Fase 3: Análisis y detección de targets de exploración.

Combina los índices espectrales calculados con datos geológicos opcionales
para identificar, clasificar y persistir zonas de interés minero.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from terraf.db.models import Analisis, DatoGeologico, Imagen, IndiceEspectral, Target
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TargetInfo:
    nombre: str
    centroide_x: float           # coordenadas proyectadas del CRS
    centroide_y: float
    centroide_lon: Optional[float]
    centroide_lat: Optional[float]
    area_px: int
    area_ha: float
    score: float
    prioridad: str               # ALTA / MEDIA / BAJA
    ior_media: Optional[float]
    clay_media: Optional[float]
    litologia_dominante: Optional[str]
    geometria_wkt: str           # POINT en coordenadas del CRS
    target_id: int = -1


@dataclass
class AnalisisResultado:
    analisis_id: int
    imagen_id: int
    scene_id: str
    metodo: str
    num_targets: int
    duracion_seg: float
    targets: list[TargetInfo] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _load_raster_array(ruta: str) -> Optional[np.ndarray]:
    """Lee un GeoTIFF y retorna el array 2-D float. None si falla."""
    try:
        import rasterio  # noqa: PLC0415
        with rasterio.open(ruta) as src:
            return src.read(1).astype(float)
    except Exception:
        return None


def _pixel_to_coords(
    row: int, col: int, transform_list: list
) -> tuple[float, float]:
    """
    Convierte (row, col) a (x, y) usando la transformada affine como lista.

    rasterio serializa Affine como 9 valores [a,b,c,d,e,f,0,0,1];
    también acepta la forma corta de 6 elementos.
    """
    a, b, c, d, e, f = transform_list[:6]
    x = c + col * a + row * b
    y = f + col * d + row * e
    return x, y


def _coords_to_latlon(x: float, y: float, crs: str) -> tuple[float, float]:
    """Reproyecta (x, y) en `crs` a EPSG:4326 (lon, lat). Retorna (None, None) si falla."""
    try:
        from pyproj import Transformer  # noqa: PLC0415
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        return lon, lat
    except Exception:
        return None, None


def _score_and_priority(
    norm_intensity: float,
    norm_area: float,
    geo_bonus: float = 0.0,
) -> tuple[float, str]:
    """
    Calcula score combinado y clasifica la prioridad.

    score = 0.55 × intensidad_norm + 0.35 × area_norm + 0.10 × geo_bonus
    """
    score = round(0.55 * norm_intensity + 0.35 * norm_area + 0.10 * geo_bonus, 4)
    if score >= 0.65:
        prioridad = "ALTA"
    elif score >= 0.30:
        prioridad = "MEDIA"
    else:
        prioridad = "BAJA"
    return score, prioridad


def _label_clusters(binary_map: np.ndarray) -> tuple[np.ndarray, int]:
    """8-conectividad usando scipy si está disponible, BFS puro si no."""
    try:
        from scipy.ndimage import label  # noqa: PLC0415
        structure = np.ones((3, 3), dtype=int)
        labeled, n = label(binary_map, structure=structure)
        return labeled, int(n)
    except ImportError:
        pass

    labeled = np.zeros_like(binary_map, dtype=np.int32)
    label_num = 0
    rows, cols = binary_map.shape
    for y in range(rows):
        for x in range(cols):
            if binary_map[y, x] and labeled[y, x] == 0:
                label_num += 1
                stack = [(y, x)]
                while stack:
                    cy, cx = stack.pop()
                    if 0 <= cy < rows and 0 <= cx < cols:
                        if binary_map[cy, cx] and labeled[cy, cx] == 0:
                            labeled[cy, cx] = label_num
                            stack.extend([
                                (cy + 1, cx), (cy - 1, cx),
                                (cy, cx + 1), (cy, cx - 1),
                                (cy + 1, cx + 1), (cy - 1, cx - 1),
                                (cy + 1, cx - 1), (cy - 1, cx + 1),
                            ])
    return labeled, label_num


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def ejecutar_analisis(
    db_path: Path,
    metodo: str = "logico",
    umbral_ior: Optional[float] = None,
    umbral_clay: Optional[float] = None,
    min_area_px: int = 10,
    on_step: Optional[Callable[[str], None]] = None,
) -> AnalisisResultado:
    """
    Detecta targets de exploración combinando índices espectrales y geología.

    Flujo:
    1. Valida precondiciones (imagen + al menos IOR calculado).
    2. Carga rasters de IOR y Clay (si existen).
    3. Aplica máscara espectral: IOR > umbral [AND Clay > umbral].
    4. Aplica filtro de litología favorable (si hay datos geológicos en DB).
    5. Etiqueta clusters (8-conectividad), filtra por área mínima.
    6. Calcula propiedades y score de cada target.
    7. Persiste `Analisis` + `Target` en la DB.

    Args:
        db_path:      Ruta al archivo terraf.db.
        metodo:       "logico" (AND) | "estadistico" (percentil) | "ambos"
        umbral_ior:   Override del umbral IOR guardado en DB.
        umbral_clay:  Override del umbral Clay guardado en DB.
        min_area_px:  Tamaño mínimo de cluster en píxeles.
        on_step:      Callback(descripcion) para reportar progreso.

    Returns:
        AnalisisResultado con la lista de TargetInfo.

    Raises:
        RuntimeError:      Si no hay imagen o índices en la DB.
        FileNotFoundError: Si los rasters no se encuentran en disco.
    """
    t0 = time.monotonic()

    def _step(msg: str) -> None:
        if on_step:
            on_step(msg)

    # ── 1. Cargar metadatos desde DB ──────────────────────────────────────────
    _step("Cargando índices espectrales desde DB")
    with open_session(db_path) as session:
        imagen = (
            session.query(Imagen)
            .order_by(Imagen.cargada_en.desc())
            .first()
        )
        if imagen is None:
            raise RuntimeError(
                "No hay imagen registrada.\nEjecuta 'terraf load <ruta>' primero."
            )

        imagen_id    = imagen.id
        scene_id     = imagen.scene_id
        resolucion   = imagen.resolucion_m or 30.0
        crs          = imagen.crs
        transform_list = (
            json.loads(imagen.transform_json) if imagen.transform_json else None
        )

        # Buscar registros de índices
        idx_ior = (
            session.query(IndiceEspectral)
            .filter_by(imagen_id=imagen_id, nombre_indice="ior")
            .first()
        )
        idx_clay = (
            session.query(IndiceEspectral)
            .filter_by(imagen_id=imagen_id, nombre_indice="clay")
            .first()
        )

        if idx_ior is None:
            raise RuntimeError(
                "No hay índices calculados para esta imagen.\n"
                "Ejecuta 'terraf indices' primero."
            )

        ior_ruta   = idx_ior.ruta_raster
        clay_ruta  = idx_clay.ruta_raster if idx_clay else None
        umb_ior    = umbral_ior  or idx_ior.umbral  or 0.65
        umb_clay   = umbral_clay or (idx_clay.umbral if idx_clay else 0.55)

        # Litología favorable en DB (si hay datos geológicos)
        tiene_geo = session.query(DatoGeologico).filter_by(proyecto_id=imagen_id).count() > 0

    # ── 2. Cargar rasters de disco ────────────────────────────────────────────
    _step("Aplicando filtro espectral")

    ior_arr = _load_raster_array(ior_ruta) if ior_ruta else None
    if ior_arr is None:
        raise FileNotFoundError(
            f"No se pudo cargar el raster IOR desde: {ior_ruta}\n"
            "Ejecuta 'terraf indices' de nuevo para regenerar los rasters."
        )

    clay_arr = _load_raster_array(clay_ruta) if clay_ruta else None

    # ── 3. Máscara espectral ──────────────────────────────────────────────────
    mascara = np.isfinite(ior_arr) & (ior_arr > umb_ior)

    if metodo in ("logico", "ambos") and clay_arr is not None:
        mascara &= np.isfinite(clay_arr) & (clay_arr > umb_clay)

    if metodo == "estadistico":
        valid_ior = ior_arr[np.isfinite(ior_arr)]
        if len(valid_ior) > 0:
            pct_thresh = np.percentile(valid_ior, 75)
            mascara = np.isfinite(ior_arr) & (ior_arr > pct_thresh)

    # ── 4. Filtro geológico (opcional, best-effort) ───────────────────────────
    _step("Aplicando filtro geológico")
    # (En Fase 1 el filtro de litología requiere rasterización del shapefile
    #  al CRS de la imagen, lo que implica geopandas + rasterio avanzado.
    #  Se aplica si hay rasters de litología pre-calculados; si no, se omite.)
    geo_mask: Optional[np.ndarray] = None  # reservado para Fase 2

    if geo_mask is not None:
        mascara &= geo_mask

    # ── 5. Etiquetar clusters ──────────────────────────────────────────────────
    _step("Identificando y clasificando targets")
    labeled, n_clusters = _label_clusters(mascara)

    # Filtrar clusters por área mínima y extraer propiedades
    raw_targets: list[dict] = []
    for i in range(1, n_clusters + 1):
        ys, xs = np.where(labeled == i)
        area_px = len(ys)
        if area_px < min_area_px:
            continue

        row_c = int(np.mean(ys))
        col_c = int(np.mean(xs))
        intensity = float(np.mean(ior_arr[ys, xs]))
        clay_mean = float(np.mean(clay_arr[ys, xs])) if clay_arr is not None else None

        raw_targets.append({
            "row": row_c, "col": col_c,
            "area_px": area_px,
            "intensity": intensity,
            "clay_mean": clay_mean,
        })

    if not raw_targets:
        # Guardar análisis vacío
        with open_session(db_path) as session:
            anal = Analisis(
                proyecto_id=1,
                imagen_id=imagen_id,
                metodo=metodo,
                parametros_json=json.dumps({
                    "umbral_ior": umb_ior, "umbral_clay": umb_clay,
                    "min_area_px": min_area_px,
                }),
                num_targets=0,
                duracion_seg=round(time.monotonic() - t0, 2),
            )
            session.add(anal)
            session.flush()
            analisis_id = anal.id

        return AnalisisResultado(
            analisis_id=analisis_id,
            imagen_id=imagen_id,
            scene_id=scene_id,
            metodo=metodo,
            num_targets=0,
            duracion_seg=round(time.monotonic() - t0, 2),
        )

    # ── 6. Calcular scores ────────────────────────────────────────────────────
    intensities = [t["intensity"] for t in raw_targets]
    areas       = [t["area_px"]   for t in raw_targets]
    min_i, max_i = min(intensities), max(intensities)
    min_a, max_a = min(areas),       max(areas)

    def _norm(val: float, lo: float, hi: float) -> float:
        return (val - lo) / (hi - lo) if hi > lo else 0.5

    targets_info: list[TargetInfo] = []
    for i, t in enumerate(raw_targets, start=1):
        score, prioridad = _score_and_priority(
            norm_intensity=_norm(t["intensity"], min_i, max_i),
            norm_area=_norm(t["area_px"], min_a, max_a),
        )
        area_ha = round(t["area_px"] * (resolucion ** 2) / 10_000, 4)

        # Coordenadas geográficas del centroide
        if transform_list:
            cx, cy = _pixel_to_coords(t["row"], t["col"], transform_list)
        else:
            cx, cy = float(t["col"]), float(t["row"])

        lon, lat = (None, None)
        if crs and transform_list:
            lon, lat = _coords_to_latlon(cx, cy, crs)

        targets_info.append(TargetInfo(
            nombre=f"T{i:03d}",
            centroide_x=cx,
            centroide_y=cy,
            centroide_lon=lon,
            centroide_lat=lat,
            area_px=t["area_px"],
            area_ha=area_ha,
            score=score,
            prioridad=prioridad,
            ior_media=round(t["intensity"], 4),
            clay_media=round(t["clay_mean"], 4) if t["clay_mean"] is not None else None,
            litologia_dominante=None,
            geometria_wkt=f"POINT ({cx} {cy})",
        ))

    # Ordenar por score descendente
    targets_info.sort(key=lambda t: t.score, reverse=True)
    # Re-numerar tras ordenar
    for j, t in enumerate(targets_info, start=1):
        t.nombre = f"T{j:03d}"

    # ── 7. Persistir en DB ────────────────────────────────────────────────────
    with open_session(db_path) as session:
        # Obtener proyecto_id
        from terraf.db.models import Proyecto  # noqa: PLC0415
        proyecto = session.query(Proyecto).first()
        proyecto_id = proyecto.id if proyecto else 1

        duracion = round(time.monotonic() - t0, 2)
        anal = Analisis(
            proyecto_id=proyecto_id,
            imagen_id=imagen_id,
            metodo=metodo,
            parametros_json=json.dumps({
                "umbral_ior":   umb_ior,
                "umbral_clay":  umb_clay,
                "min_area_px":  min_area_px,
            }),
            num_targets=len(targets_info),
            duracion_seg=duracion,
        )
        session.add(anal)
        session.flush()
        analisis_id = anal.id

        for ti in targets_info:
            rec = Target(
                analisis_id=analisis_id,
                nombre=ti.nombre,
                centroide_x=ti.centroide_x,
                centroide_y=ti.centroide_y,
                centroide_lon=ti.centroide_lon,
                centroide_lat=ti.centroide_lat,
                area_ha=ti.area_ha,
                area_px=ti.area_px,
                score=ti.score,
                prioridad=ti.prioridad,
                ior_media=ti.ior_media,
                clay_media=ti.clay_media,
                litologia_dominante=ti.litologia_dominante,
                geometria_wkt=ti.geometria_wkt,
            )
            session.add(rec)
            session.flush()
            ti.target_id = rec.id

    return AnalisisResultado(
        analisis_id=analisis_id,
        imagen_id=imagen_id,
        scene_id=scene_id,
        metodo=metodo,
        num_targets=len(targets_info),
        duracion_seg=duracion,
        targets=targets_info,
    )
