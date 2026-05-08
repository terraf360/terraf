"""
Pipeline — Visualización flexible (`terraf view`).

Genera un mapa Folium componible con las capas solicitadas.
Cada "recurso" (índice, dato vectorial, target, prospectividad…) tiene su
propio "provider" que devuelve una capa que se agrega al mapa.

Filosofía:
  - El usuario combina libremente: `terraf view ior clay geologia targets`.
  - Sin argumentos: muestra todo lo disponible.
  - Las capas se agregan al control de capas de Folium (toggle on/off).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from terraf.db.models import (
    Analisis,
    DatoGeologico,
    FeatureGeologico,
    Imagen,
    IndiceEspectral,
    Proyecto,
    Target,
)
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Configuración de colormaps por recurso
# ──────────────────────────────────────────────────────────────────────────────

_COLORMAPS_RASTER = {
    "ior":             ("YlOrRd",   "Iron Oxide Ratio"),
    "clay":            ("YlOrBr",   "Clay Ratio"),
    "ferrous":         ("OrRd",     "Ferrous Minerals"),
    "ndvi":            ("RdYlGn",   "NDVI (vegetación)"),
    "ndwi":            ("Blues",    "NDWI (agua)"),
    "evi":             ("RdYlGn",   "EVI (vegetación realzada)"),
    "savi":            ("YlGn",     "SAVI"),
    "prospectividad":  ("jet",      "Prospectividad mineral"),
}

_RECURSOS_RASTER = set(_COLORMAPS_RASTER.keys())

_RECURSOS_VECTOR = {
    "geologia",
    "sgm_geofisica",
    "sgm_geologia",
    "sgm_geoquimica",
    "sgm_inventario_minero",
    "inegi_usosue",
}

_RECURSOS_ESPECIALES = {"rgb", "imagen", "targets", "validaciones"}


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ViewResult:
    html_path: Path
    capas_incluidas: list[str]
    capas_no_disponibles: list[str]
    bounds_wgs84: Optional[tuple[float, float, float, float]] = None


# ──────────────────────────────────────────────────────────────────────────────
# Inventario de recursos disponibles
# ──────────────────────────────────────────────────────────────────────────────

def listar_recursos_disponibles(db_path: Path) -> dict[str, dict]:
    """
    Inspecciona la DB y retorna qué recursos pueden visualizarse.

    Returns:
        dict { nombre: { tipo, descripcion, ... } }
    """
    inventario: dict[str, dict] = {}

    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        if proyecto is None:
            return inventario

        # ── Imagen Landsat (RGB) ───────────────────────────────────────────────
        imagen = (
            session.query(Imagen)
            .filter_by(proyecto_id=proyecto.id)
            .first()
        )
        if imagen:
            inventario["rgb"] = {
                "tipo":        "rgb",
                "descripcion": f"Imagen Landsat RGB ({imagen.scene_id})",
                "imagen_id":   imagen.id,
                "ruta":        imagen.ruta_archivo,
            }

            # ── Índices espectrales ────────────────────────────────────────────
            indices = (
                session.query(IndiceEspectral)
                .filter_by(imagen_id=imagen.id)
                .all()
            )
            for idx in indices:
                if idx.ruta_raster and Path(idx.ruta_raster).exists():
                    cmap, label = _COLORMAPS_RASTER.get(
                        idx.nombre_indice, ("viridis", idx.nombre_indice)
                    )
                    inventario[idx.nombre_indice] = {
                        "tipo":        "raster_indice",
                        "descripcion": label,
                        "ruta_raster": idx.ruta_raster,
                        "min_val":     idx.min_val,
                        "max_val":     idx.max_val,
                        "media":       idx.media,
                        "umbral":      idx.umbral,
                        "colormap":    cmap,
                    }

        # ── Mapa de prospectividad ────────────────────────────────────────────
        prosp_path = db_path.parent / "resultados" / "indices" / "prospectividad.tif"
        if prosp_path.exists():
            inventario["prospectividad"] = {
                "tipo":        "raster_prospectividad",
                "descripcion": "Mapa de Prospectividad Mineral",
                "ruta_raster": str(prosp_path),
                "colormap":    "jet",
            }

        # ── Datos vectoriales (geología, SGM, INEGI) ──────────────────────────
        capas = (
            session.query(DatoGeologico)
            .filter_by(proyecto_id=proyecto.id)
            .all()
        )
        for c in capas:
            n_feat = (
                session.query(FeatureGeologico)
                .filter_by(dato_geologico_id=c.id)
                .count()
            )
            if n_feat == 0:
                continue
            # Aceptar tanto el nombre canónico como la categoría
            nombres_alias = [c.capa]
            if c.capa.startswith("sgm_geofisica") or "magnetico" in c.capa.lower():
                nombres_alias.extend(["geofisica", "magnetometria", "magnetico"])
            elif c.capa == "sgm_geologia":
                nombres_alias.append("geologia")
            elif c.capa == "inegi_usosue":
                nombres_alias.extend(["inegi", "uso_suelo"])

            for nombre in nombres_alias:
                inventario[nombre] = {
                    "tipo":        "vector",
                    "descripcion": f"{c.capa} ({n_feat:,} features)",
                    "capa_real":   c.capa,
                    "dato_id":     c.id,
                    "crs":         c.crs,
                    "n_features":  n_feat,
                }

        # ── Targets de análisis ────────────────────────────────────────────────
        analisis = (
            session.query(Analisis)
            .filter_by(proyecto_id=proyecto.id)
            .first()
        )
        if analisis:
            n_tg = (
                session.query(Target)
                .filter_by(analisis_id=analisis.id)
                .count()
            )
            if n_tg > 0:
                inventario["targets"] = {
                    "tipo":        "targets",
                    "descripcion": f"Targets de exploración ({n_tg})",
                    "analisis_id": analisis.id,
                    "n_targets":   n_tg,
                }

    return inventario


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: conversión de raster a PNG con colormap
# ──────────────────────────────────────────────────────────────────────────────

def _raster_a_png(
    raster_path: Path,
    out_png: Path,
    colormap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    reduccion: int = 8,
) -> tuple[tuple[float, float, float, float], tuple[float, float]]:
    """
    Convierte un raster a PNG con colormap, retornando bounds WGS84 y (vmin, vmax).
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import array_bounds
    from rasterio.warp import transform_bounds
    from rasterio.crs import CRS
    import matplotlib.pyplot as plt
    from PIL import Image

    with rasterio.open(raster_path) as ds:
        h = max(ds.height // reduccion, 64)
        w = max(ds.width // reduccion, 64)
        data = ds.read(1, out_shape=(h, w), resampling=Resampling.average).astype(np.float32)
        transform = ds.transform * ds.transform.scale(ds.width / w, ds.height / h)
        crs = ds.crs
        nodata = ds.nodata

    # Manejar nodata y valores no finitos
    if nodata is not None:
        data[data == nodata] = np.nan
    valid = np.isfinite(data)
    if not valid.any():
        raise RuntimeError(f"Raster {raster_path.name} no tiene datos válidos.")

    # Robust scaling (percentiles 2-98) si no se pasan vmin/vmax
    if vmin is None:
        vmin = float(np.nanpercentile(data[valid], 2))
    if vmax is None:
        vmax = float(np.nanpercentile(data[valid], 98))
    if vmax == vmin:
        vmax = vmin + 1e-6

    norm = np.clip((data - vmin) / (vmax - vmin), 0.0, 1.0)
    cmap = plt.get_cmap(colormap)
    rgba = (cmap(norm) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 200, 0).astype(np.uint8)

    Image.fromarray(rgba).save(out_png)

    # Bounds WGS84
    minx, miny, maxx, maxy = array_bounds(h, w, transform)
    if crs and crs.to_epsg() != 4326:
        wmin, smin, emin, nmin = transform_bounds(
            crs, CRS.from_epsg(4326), minx, miny, maxx, maxy
        )
    else:
        wmin, smin, emin, nmin = minx, miny, maxx, maxy

    return (wmin, smin, emin, nmin), (vmin, vmax)


def _generar_rgb_landsat(
    ruta_imagen: str,
    out_png: Path,
    reduccion: int = 8,
) -> Optional[tuple[float, float, float, float]]:
    """
    Genera un PNG RGB true-color a partir de las bandas Landsat (B4/B3/B2).
    `ruta_imagen` apunta al directorio o a una banda; encontramos el resto.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import array_bounds
    from rasterio.warp import transform_bounds
    from rasterio.crs import CRS
    from PIL import Image

    p = Path(ruta_imagen)
    if p.is_file():
        scene_dir = p.parent
    else:
        scene_dir = p

    # Buscar SR_B4, SR_B3, SR_B2
    b4 = list(scene_dir.glob("*SR_B4.TIF")) + list(scene_dir.glob("*SR_B4.tif"))
    b3 = list(scene_dir.glob("*SR_B3.TIF")) + list(scene_dir.glob("*SR_B3.tif"))
    b2 = list(scene_dir.glob("*SR_B2.TIF")) + list(scene_dir.glob("*SR_B2.tif"))
    if not (b4 and b3 and b2):
        return None

    bandas = [b4[0], b3[0], b2[0]]
    arrays = []
    crs = None
    transform = None
    for b in bandas:
        with rasterio.open(b) as ds:
            h = max(ds.height // reduccion, 64)
            w = max(ds.width // reduccion, 64)
            arr = ds.read(1, out_shape=(h, w), resampling=Resampling.average).astype(np.float32)
            arrays.append(arr)
            if crs is None:
                crs = ds.crs
                transform = ds.transform * ds.transform.scale(ds.width / w, ds.height / h)

    rgb = np.stack(arrays, axis=-1)

    # Stretch 2-98 percentil por banda
    out = np.zeros_like(rgb, dtype=np.uint8)
    for i in range(3):
        b = rgb[..., i]
        valid = b > 0
        if not valid.any():
            continue
        p2 = np.percentile(b[valid], 2)
        p98 = np.percentile(b[valid], 98)
        b_norm = np.clip((b - p2) / max(p98 - p2, 1e-6), 0.0, 1.0)
        out[..., i] = (b_norm * 255).astype(np.uint8)

    # Alpha: 0 donde no hay datos
    alpha = np.where(rgb.sum(axis=-1) > 0, 255, 0).astype(np.uint8)
    rgba = np.dstack([out, alpha])
    Image.fromarray(rgba, mode="RGBA").save(out_png)

    # Bounds WGS84
    h, w = arrays[0].shape
    minx, miny, maxx, maxy = array_bounds(h, w, transform)
    if crs and crs.to_epsg() != 4326:
        wmin, smin, emin, nmin = transform_bounds(
            crs, CRS.from_epsg(4326), minx, miny, maxx, maxy
        )
    else:
        wmin, smin, emin, nmin = minx, miny, maxx, maxy

    return (wmin, smin, emin, nmin)


# ──────────────────────────────────────────────────────────────────────────────
# Providers: cada uno agrega una capa al mapa Folium
# ──────────────────────────────────────────────────────────────────────────────

def _provider_raster(
    m,
    nombre: str,
    info: dict,
    out_dir: Path,
    visible: bool = True,
) -> Optional[tuple[float, float, float, float]]:
    """Agrega un raster (índice o prospectividad) como ImageOverlay."""
    import folium
    import branca.colormap as bcm

    out_png = out_dir / f"_overlay_{nombre}.png"
    bounds, (vmin, vmax) = _raster_a_png(
        Path(info["ruta_raster"]),
        out_png,
        colormap=info.get("colormap", "viridis"),
        reduccion=8,
    )
    wmin, smin, emin, nmin = bounds

    label = info.get("descripcion", nombre)
    overlay = folium.raster_layers.ImageOverlay(
        name=label,
        image=str(out_png),
        bounds=[[smin, wmin], [nmin, emin]],
        opacity=0.75,
        interactive=True,
        cross_origin=False,
        show=visible,
    )
    overlay.add_to(m)
    return bounds


def _provider_rgb(m, info: dict, out_dir: Path) -> Optional[tuple]:
    """Agrega imagen RGB Landsat true-color como overlay."""
    import folium

    if not info.get("ruta"):
        return None

    out_png = out_dir / "_overlay_rgb.png"
    bounds = _generar_rgb_landsat(info["ruta"], out_png, reduccion=8)
    if bounds is None:
        return None

    wmin, smin, emin, nmin = bounds
    folium.raster_layers.ImageOverlay(
        name=info.get("descripcion", "Landsat RGB"),
        image=str(out_png),
        bounds=[[smin, wmin], [nmin, emin]],
        opacity=0.85,
        cross_origin=False,
        show=True,
    ).add_to(m)
    return bounds


def _provider_vector(
    m,
    db_path: Path,
    nombre: str,
    info: dict,
) -> Optional[tuple[float, float, float, float]]:
    """Agrega capa vectorial (geología, magnetometría, INEGI) al mapa."""
    import folium
    import geopandas as gpd
    import branca.colormap as bcm
    from shapely import wkt as shapely_wkt

    rows = []
    with open_session(db_path) as session:
        feats = (
            session.query(FeatureGeologico)
            .filter_by(dato_geologico_id=info["dato_id"])
            .all()
        )
        for f in feats:
            row = {}
            if f.atributos_json:
                try:
                    row = json.loads(f.atributos_json)
                except Exception:
                    pass
            row["_tipo"] = f.tipo
            row["_wkt"]  = f.geometria_wkt
            rows.append(row)

    if not rows:
        return None

    geoms, attrs = [], []
    for r in rows:
        wkt_str = r.pop("_wkt", None)
        if not wkt_str:
            continue
        try:
            geoms.append(shapely_wkt.loads(wkt_str))
            attrs.append(r)
        except Exception:
            continue

    gdf = gpd.GeoDataFrame(attrs, geometry=geoms)
    if info.get("crs"):
        try:
            gdf = gdf.set_crs(info["crs"])
        except Exception:
            pass
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    elif gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)

    capa_real = info.get("capa_real", nombre)

    # Estilo según tipo de capa
    if "geofisica" in capa_real or "magnetico" in capa_real.lower():
        return _agregar_geofisica(m, gdf, capa_real)
    elif capa_real == "inegi_usosue":
        return _agregar_inegi(m, gdf)
    else:
        return _agregar_geologia_generica(m, gdf, capa_real)


def _agregar_geofisica(m, gdf, capa_nombre: str) -> tuple:
    """Magnetometría con colormap jet sobre RANGO_CODE."""
    import folium
    import branca.colormap as bcm

    if "RANGO_CODE" not in gdf.columns:
        return _agregar_geologia_generica(m, gdf, capa_nombre)

    try:
        gdf["RANGO_CODE"] = gdf["RANGO_CODE"].astype(float)
    except Exception:
        pass
    serie = gdf["RANGO_CODE"].dropna()
    vmin = float(serie.quantile(0.02))
    vmax = float(serie.quantile(0.98))
    if vmin == vmax:
        vmin, vmax = float(serie.min()), float(serie.max())

    jet_cm = bcm.LinearColormap(
        colors=[
            "#00007F", "#0000FF", "#007FFF", "#00FFFF",
            "#7FFF7F", "#FFFF00", "#FF7F00", "#FF0000", "#7F0000",
        ],
        vmin=vmin, vmax=vmax,
        caption=f"{capa_nombre} — RANGO_CODE",
    )

    def _style(feature):
        raw = feature["properties"].get("RANGO_CODE")
        try:
            v = float(raw)
            v = max(vmin, min(vmax, v))
            color = jet_cm(v)
        except (ValueError, TypeError):
            color = "#888"
        return {"fillColor": color, "color": "none", "weight": 0, "fillOpacity": 0.85}

    cols = [c for c in gdf.columns if c not in ("geometry", "_tipo")][:4]
    gdf_m = gdf[cols + ["geometry"]].copy()
    for c in cols:
        gdf_m[c] = gdf_m[c].astype(str)

    folium.GeoJson(
        gdf_m.__geo_interface__,
        name=capa_nombre,
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=cols, aliases=cols, localize=True),
    ).add_to(m)
    jet_cm.add_to(m)

    minx, miny, maxx, maxy = gdf.total_bounds
    return (minx, miny, maxx, maxy)


def _agregar_inegi(m, gdf) -> tuple:
    """INEGI con paleta predefinida por tipod7."""
    import folium

    preset = {
        "BOSQUES":               "#2d6a4f",
        "MATORRAL":              "#95d5b2",
        "AGRICULTURA":           "#f9c74f",
        "AREA AGRICOLA":         "#f9c74f",
        "PASTIZAL-PRADERA-SABANA": "#b7e4c7",
        "CUERPO DE AGUA":        "#4cc9f0",
        "AREA SIN VEGETACION":   "#e5e5e5",
        "LOCALIDAD":             "#e76f51",
        "SELVA":                 "#1b4332",
    }
    paleta_extra = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f"]
    valores = sorted(gdf["tipod7"].dropna().unique()) if "tipod7" in gdf.columns else []
    color_map = {}
    for i, v in enumerate(valores):
        color_map[str(v)] = preset.get(str(v), paleta_extra[i % len(paleta_extra)])

    def _style(feature):
        v = feature["properties"].get("tipod7")
        return {
            "fillColor":  color_map.get(str(v), "#aaa"),
            "color":      "#555",
            "weight":     0.3,
            "fillOpacity": 0.7,
        }

    cols = [c for c in ["tipod7", "tipo", "fisonomia"] if c in gdf.columns]
    gdf_m = gdf[cols + ["geometry"]].copy()
    for c in cols:
        gdf_m[c] = gdf_m[c].astype(str)

    folium.GeoJson(
        gdf_m.__geo_interface__,
        name="INEGI Uso de Suelo",
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=cols, aliases=cols, localize=True),
    ).add_to(m)
    minx, miny, maxx, maxy = gdf.total_bounds
    return (minx, miny, maxx, maxy)


def _agregar_geologia_generica(m, gdf, capa_nombre: str) -> tuple:
    """Geología u otra capa con paleta categórica simple."""
    import folium

    paleta = [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
        "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    ]
    campo_color = None
    for c in ["DESCRIPCION", "LITOLOGIA", "UNIDAD", "tipo", "_tipo", "SIMBOLO"]:
        if c in gdf.columns and gdf[c].notna().any():
            campo_color = c
            break

    color_map = {}
    if campo_color:
        for i, v in enumerate(sorted(gdf[campo_color].dropna().astype(str).unique())):
            color_map[v] = paleta[i % len(paleta)]

    def _style(feature):
        v = feature["properties"].get(campo_color) if campo_color else None
        return {
            "fillColor":  color_map.get(str(v), "#888"),
            "color":      "#444",
            "weight":     0.4,
            "fillOpacity": 0.6,
        }

    cols = [c for c in gdf.columns if c not in ("geometry", "_tipo")][:4]
    gdf_m = gdf[cols + ["geometry"]].copy()
    for c in cols:
        gdf_m[c] = gdf_m[c].astype(str)

    folium.GeoJson(
        gdf_m.__geo_interface__,
        name=capa_nombre,
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=cols, aliases=cols, localize=True),
    ).add_to(m)
    minx, miny, maxx, maxy = gdf.total_bounds
    return (minx, miny, maxx, maxy)


def _provider_targets(m, db_path: Path, info: dict) -> Optional[tuple]:
    """Marcadores de targets coloreados por prioridad."""
    import folium

    with open_session(db_path) as session:
        targets = (
            session.query(Target)
            .filter_by(analisis_id=info["analisis_id"])
            .all()
        )
        rows = [
            {
                "nombre":     t.nombre or f"T{t.id:03d}",
                "lat":        t.centroide_lat,
                "lon":        t.centroide_lon,
                "prioridad":  t.prioridad or "MEDIA",
                "score":      t.score,
                "area_ha":    t.area_ha,
                "ior":        t.ior_media,
                "clay":       t.clay_media,
            }
            for t in targets
            if t.centroide_lat is not None and t.centroide_lon is not None
        ]

    if not rows:
        return None

    fg = folium.FeatureGroup(name=f"Targets ({len(rows)})", show=True)
    color_prio = {"ALTA": "#ef4444", "MEDIA": "#f59e0b", "BAJA": "#94a3b8"}

    lats, lons = [], []
    for r in rows:
        c = color_prio.get(r["prioridad"], "#888")
        popup = (
            f"<b>{r['nombre']}</b><br>"
            f"Prioridad: <b>{r['prioridad']}</b><br>"
            f"Score: {r['score']:.2f}<br>"
            f"Área: {r['area_ha']:.1f} ha<br>"
            f"IOR: {r['ior']:.2f} · Clay: {r['clay']:.2f}"
        )
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=8,
            color=c,
            fill=True,
            fillColor=c,
            fillOpacity=0.8,
            weight=2,
            popup=folium.Popup(popup, max_width=240),
            tooltip=f"{r['nombre']} — {r['prioridad']}",
        ).add_to(fg)
        lats.append(r["lat"])
        lons.append(r["lon"])

    fg.add_to(m)
    return (min(lons), min(lats), max(lons), max(lats))


# ──────────────────────────────────────────────────────────────────────────────
# Función principal
# ──────────────────────────────────────────────────────────────────────────────

def generar_vista(
    db_path: Path,
    recursos: Optional[list[str]] = None,
    out_path: Optional[Path] = None,
    on_step: Optional[Callable[[str], None]] = None,
) -> ViewResult:
    """
    Genera un mapa Folium con las capas solicitadas.

    Args:
        db_path:  Ruta a terraf.db.
        recursos: Lista de nombres a visualizar (ior, clay, geologia, targets…).
                  Si es None o vacía, muestra TODO lo disponible.
        out_path: Ruta del HTML de salida (default: resultados/mapas/vista.html).
        on_step:  Callback de progreso.

    Returns:
        ViewResult con la lista de capas incluidas y la ruta del HTML.
    """
    import folium

    inventario = listar_recursos_disponibles(db_path)
    if not inventario:
        raise RuntimeError(
            "No hay nada que visualizar todavía. Carga una imagen con "
            "'terraf load' o calcula índices con 'terraf indices'."
        )

    # Resolver recursos solicitados
    if not recursos:
        # Por defecto: rgb (si hay) + prospectividad (si hay) + targets (si hay)
        # + geología + magnetometría — pero NO los 7 índices a la vez (es ruidoso).
        recursos_default = []
        if "rgb" in inventario:
            recursos_default.append("rgb")
        if "prospectividad" in inventario:
            recursos_default.append("prospectividad")
        else:
            # Sin prospectividad, mostrar al menos IOR y Clay como representativos
            for x in ["ior", "clay"]:
                if x in inventario:
                    recursos_default.append(x)
        for v in ["geologia", "sgm_geologia", "magnetico", "geofisica",
                  "sgm_geofisica", "inegi"]:
            if v in inventario and inventario[v].get("capa_real") not in [
                inventario.get(r, {}).get("capa_real") for r in recursos_default
            ]:
                recursos_default.append(v)
                break  # solo agregar uno de cada categoría
        if "targets" in inventario:
            recursos_default.append("targets")
        recursos = recursos_default or list(inventario.keys())[:3]

    # Normalizar nombres a minúsculas
    recursos = [r.lower().strip() for r in recursos]

    incluidos: list[str] = []
    no_disponibles: list[str] = []
    bounds_collected: list[tuple] = []

    if on_step:
        on_step(f"Construyendo mapa con: {', '.join(recursos)}")

    # ── Mapa base centrado provisional ─────────────────────────────────────────
    m = folium.Map(
        location=[23.0, -102.0],   # centro de México como fallback
        zoom_start=5,
        tiles="CartoDB positron",
    )
    folium.TileLayer(
        "Esri.WorldImagery", name="Satélite (Esri)", overlay=False, control=True,
    ).add_to(m)
    folium.TileLayer(
        "OpenStreetMap", name="OpenStreetMap", overlay=False, control=True,
    ).add_to(m)

    out_dir = (out_path.parent if out_path else db_path.parent / "resultados" / "mapas")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Procesar cada recurso solicitado ──────────────────────────────────────
    seen = set()
    for r in recursos:
        if r in seen:
            continue
        seen.add(r)

        info = inventario.get(r)
        if info is None:
            no_disponibles.append(r)
            continue

        try:
            tipo = info["tipo"]
            if on_step:
                on_step(f"  agregando '{r}' ({tipo})...")

            b = None
            if tipo in ("raster_indice", "raster_prospectividad"):
                b = _provider_raster(m, r, info, out_dir, visible=True)
            elif tipo == "rgb":
                b = _provider_rgb(m, info, out_dir)
            elif tipo == "vector":
                # Evitar duplicar la misma capa real bajo distintos alias
                if info.get("capa_real") in [
                    inventario.get(x, {}).get("capa_real") for x in incluidos
                ]:
                    continue
                b = _provider_vector(m, db_path, r, info)
            elif tipo == "targets":
                b = _provider_targets(m, db_path, info)

            if b:
                bounds_collected.append(b)
            incluidos.append(r)

        except Exception as exc:
            if on_step:
                on_step(f"  ! error agregando '{r}': {exc}")

    if not incluidos:
        raise RuntimeError(
            f"Ninguno de los recursos solicitados está disponible. "
            f"Disponibles: {', '.join(inventario.keys())}"
        )

    # ── Centrar y zoom según extensión combinada ─────────────────────────────
    bounds_total: Optional[tuple] = None
    if bounds_collected:
        wmin = min(b[0] for b in bounds_collected)
        smin = min(b[1] for b in bounds_collected)
        emin = max(b[2] for b in bounds_collected)
        nmin = max(b[3] for b in bounds_collected)
        bounds_total = (wmin, smin, emin, nmin)
        m.fit_bounds([[smin, wmin], [nmin, emin]])

    # ── Título flotante ───────────────────────────────────────────────────────
    titulo = (
        f'<div style="position:fixed;top:12px;left:60px;z-index:9999;'
        f'background:rgba(255,255,255,0.95);padding:10px 16px;border-radius:6px;'
        f'font-family:sans-serif;font-size:13px;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.25);">'
        f'<b>Vista del proyecto</b><br>'
        f'<span style="font-size:11px;color:#555;">'
        f'{len(incluidos)} capa(s): {", ".join(incluidos)}'
        f'</span></div>'
    )
    m.get_root().html.add_child(folium.Element(titulo))

    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # ── Guardar ───────────────────────────────────────────────────────────────
    html_path = out_path or (out_dir / "vista.html")
    m.save(str(html_path))

    if on_step:
        on_step(f"Mapa listo: {html_path.name}")

    return ViewResult(
        html_path=html_path,
        capas_incluidas=incluidos,
        capas_no_disponibles=no_disponibles,
        bounds_wgs84=bounds_total,
    )
