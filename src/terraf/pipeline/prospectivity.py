"""
Pipeline — Mapa de prospectividad mineral (Mineral Prospectivity Map).

Combina todas las evidencias disponibles en el proyecto (índices espectrales,
geología, magnetometría, gravimetría) en un mapa continuo de probabilidad
0→1 usando lógica difusa (fuzzy logic) — método estándar en exploración
minera moderna (Bonham-Carter, Carranza).

Filosofía:
  - Cada evidencia se transforma a [0, 1] con una función de pertenencia
    apropiada al tipo de dato (sigmoid, gaussian, categórica).
  - Las evidencias se combinan con el operador fuzzy gamma, que captura
    tanto sinergia (AND) como complementariedad (OR).
  - El resultado es un raster de probabilidad y un mapa HTML con colormap jet.
  - Los targets se extraen como picos locales del mapa de probabilidad.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from terraf.db.models import (
    DatoGeologico,
    FeatureGeologico,
    Imagen,
    IndiceEspectral,
    Proyecto,
)
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Configuración de evidencias por tipo
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EvidenciaConfig:
    """
    Define cómo transformar una evidencia a [0, 1] (membresía fuzzy).

    Atributos:
        tipo:        'sigmoid_up'  → valores altos = alta prob (IOR, Clay)
                     'sigmoid_dn'  → valores bajos = alta prob (NDVI)
                     'gaussian'    → valores cercanos a 'centro' = alta prob
                     'categorica'  → mapeo directo de categorías a [0,1]
        peso:        contribución relativa al combinar (0-1, normalizado)
        params:      parámetros de la función (umbral, pendiente, centro, etc.)
    """
    tipo: str
    peso: float = 1.0
    params: dict = field(default_factory=dict)


# Configuración por defecto orientada a alteración hidrotermal (pórfidos Cu/Au, epitermales)
EVIDENCIAS_DEFAULT: dict[str, EvidenciaConfig] = {
    # ── Índices espectrales ────────────────────────────────────────────────
    "ior":     EvidenciaConfig("sigmoid_up", peso=0.30,
                                params={"umbral": 1.2, "pendiente": 4.0}),
    "clay":    EvidenciaConfig("sigmoid_up", peso=0.25,
                                params={"umbral": 1.2, "pendiente": 4.0}),
    "ferrous": EvidenciaConfig("sigmoid_up", peso=0.20,
                                params={"umbral": 1.1, "pendiente": 4.0}),
    "ndvi":    EvidenciaConfig("sigmoid_dn", peso=0.10,
                                params={"umbral": 0.30, "pendiente": 6.0}),
    # ── Datos vectoriales (rasterizados) ────────────────────────────────────
    "geologia":   EvidenciaConfig("categorica", peso=0.20, params={}),
    "magnetico":  EvidenciaConfig("gaussian",   peso=0.15,
                                   params={"modo": "extremos"}),  # alto o bajo
    "gravimetria": EvidenciaConfig("gaussian",  peso=0.15,
                                    params={"modo": "alto"}),
}


# ──────────────────────────────────────────────────────────────────────────────
# Funciones de pertenencia fuzzy
# ──────────────────────────────────────────────────────────────────────────────

def _fuzzy_sigmoid_up(x: np.ndarray, umbral: float, pendiente: float) -> np.ndarray:
    """Sigmoid creciente: valores >> umbral tienden a 1, valores << umbral a 0."""
    with np.errstate(over="ignore"):
        return 1.0 / (1.0 + np.exp(-pendiente * (x - umbral)))


def _fuzzy_sigmoid_dn(x: np.ndarray, umbral: float, pendiente: float) -> np.ndarray:
    """Sigmoid decreciente: valores << umbral tienden a 1, valores >> umbral a 0."""
    return 1.0 - _fuzzy_sigmoid_up(x, umbral, pendiente)


def _fuzzy_gaussian(
    x: np.ndarray,
    centro: float,
    sigma: float,
) -> np.ndarray:
    """Pertenencia gaussiana: valores cerca de 'centro' tienden a 1."""
    return np.exp(-0.5 * ((x - centro) / max(sigma, 1e-9)) ** 2)


def _fuzzy_extremos(x: np.ndarray, p_low: float, p_high: float) -> np.ndarray:
    """
    Pertenencia para anomalías: valores en los extremos (alto o bajo) tienden a 1.
    Útil para magnetometría (anomalías altas y bajas indican mineralización).
    """
    media = (p_low + p_high) / 2.0
    rango = (p_high - p_low) / 2.0
    desv  = np.abs(x - media) / max(rango, 1e-9)
    return np.clip(desv, 0.0, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Operadores fuzzy de combinación
# ──────────────────────────────────────────────────────────────────────────────

def _fuzzy_and(layers: list[np.ndarray]) -> np.ndarray:
    """AND fuzzy = mínimo (todas las evidencias deben coincidir)."""
    return np.minimum.reduce(layers)


def _fuzzy_or(layers: list[np.ndarray]) -> np.ndarray:
    """OR fuzzy = máximo (cualquier evidencia fuerte cuenta)."""
    return np.maximum.reduce(layers)


def _fuzzy_algebraic_sum(layers: list[np.ndarray]) -> np.ndarray:
    """Suma algebraica = 1 - prod(1-xi). Premia coincidencias múltiples."""
    inv = np.ones_like(layers[0])
    for layer in layers:
        inv = inv * (1.0 - layer)
    return 1.0 - inv


def _fuzzy_algebraic_product(layers: list[np.ndarray]) -> np.ndarray:
    """Producto algebraico = prod(xi). Penaliza si alguna evidencia es baja."""
    out = np.ones_like(layers[0])
    for layer in layers:
        out = out * layer
    return out


def _fuzzy_gamma(layers: list[np.ndarray], gamma: float = 0.7) -> np.ndarray:
    """
    Operador gamma fuzzy: combinación balanceada entre suma y producto.
        gamma_op = (suma_algebraica)^gamma * (producto_algebraico)^(1-gamma)

    gamma → 1: comportamiento "OR" (cualquier evidencia cuenta)
    gamma → 0: comportamiento "AND" (todas deben coincidir)
    gamma = 0.7-0.9: balance recomendado para prospectividad mineral.
    """
    suma = _fuzzy_algebraic_sum(layers)
    prod = _fuzzy_algebraic_product(layers)
    return np.power(suma, gamma) * np.power(prod, 1.0 - gamma)


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProspectivityResult:
    """Resultado de generar el mapa de prospectividad."""
    raster_path: Path
    html_path: Path
    evidencias_usadas: list[str]
    pesos_normalizados: dict[str, float]
    metodo: str
    bounds: tuple[float, float, float, float]   # WGS84
    estadisticas: dict                            # min, max, media, std, p_alta


# ──────────────────────────────────────────────────────────────────────────────
# Detección de evidencias disponibles
# ──────────────────────────────────────────────────────────────────────────────

def _detectar_evidencias(db_path: Path) -> dict[str, dict]:
    """
    Inspecciona la DB y retorna qué evidencias hay disponibles.

    Returns:
        dict { nombre_evidencia: { tipo, ruta_raster | features_count, ... } }
    """
    disponibles: dict[str, dict] = {}

    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        if proyecto is None:
            return disponibles

        # Índices espectrales (rasters)
        imagen = (
            session.query(Imagen)
            .filter_by(proyecto_id=proyecto.id)
            .first()
        )
        if imagen:
            indices = (
                session.query(IndiceEspectral)
                .filter_by(imagen_id=imagen.id)
                .all()
            )
            for idx in indices:
                if idx.ruta_raster and Path(idx.ruta_raster).exists():
                    disponibles[idx.nombre_indice] = {
                        "tipo":         "raster",
                        "ruta_raster":  idx.ruta_raster,
                        "min_val":      idx.min_val,
                        "max_val":      idx.max_val,
                        "media":        idx.media,
                    }

        # Datos geológicos / geofísicos (vectores)
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
            # Mapear capa SGM a evidencia conocida
            if "geofisica" in c.capa or "magnetico" in c.capa.lower():
                key = "magnetico"
            elif "gravim" in c.capa.lower() or "geofisica" in c.capa and "grav" in c.capa.lower():
                key = "gravimetria"
            elif "geologia" in c.capa or c.capa.startswith("sgm_geologia"):
                key = "geologia"
            else:
                continue
            disponibles[key] = {
                "tipo":         "vector",
                "capa":         c.capa,
                "dato_id":      c.id,
                "crs":          c.crs,
                "n_features":   n_feat,
            }

    return disponibles


# ──────────────────────────────────────────────────────────────────────────────
# Carga y rasterización de evidencias
# ──────────────────────────────────────────────────────────────────────────────

def _cargar_raster_referencia(
    rasters_paths: list[Path],
    reduccion: int = 4,
) -> tuple:
    """
    Carga el primer raster como referencia para definir el grid común.
    Reduce la resolución por un factor para acelerar (default: 1/4).

    Returns:
        (data_ref, transform, crs, height, width, nodata)
    """
    import rasterio
    from rasterio.enums import Resampling

    with rasterio.open(rasters_paths[0]) as ds:
        h, w = ds.height // reduccion, ds.width // reduccion
        data = ds.read(
            1,
            out_shape=(h, w),
            resampling=Resampling.average,
        )
        # Recalcular transform para la nueva resolución
        transform = ds.transform * ds.transform.scale(
            ds.width / w, ds.height / h
        )
        crs = ds.crs
        nodata = ds.nodata

    return data, transform, crs, h, w, nodata


def _cargar_raster_indice(
    ruta: Path,
    out_shape: tuple[int, int],
) -> np.ndarray:
    """Carga un raster a la resolución del grid de referencia."""
    import rasterio
    from rasterio.enums import Resampling

    with rasterio.open(ruta) as ds:
        data = ds.read(
            1,
            out_shape=out_shape,
            resampling=Resampling.average,
        ).astype(np.float32)
    return data


def _rasterizar_vector(
    db_path: Path,
    dato_id: int,
    crs_referencia,
    transform_referencia,
    out_shape: tuple[int, int],
    crs_origen: Optional[str] = None,
    valor_field: Optional[str] = None,
) -> np.ndarray:
    """
    Convierte features WKT de la DB a un raster alineado al grid de referencia.

    Si valor_field se especifica, rasteriza ese atributo numérico.
    Si no, rasteriza con valor 1 donde hay feature, 0 donde no.
    """
    import geopandas as gpd
    from shapely import wkt as shapely_wkt
    from rasterio.features import rasterize

    # Leer features
    rows = []
    with open_session(db_path) as session:
        features = (
            session.query(FeatureGeologico)
            .filter_by(dato_geologico_id=dato_id)
            .all()
        )
        for f in features:
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
        return np.zeros(out_shape, dtype=np.float32)

    # Construir GeoDataFrame
    geoms = []
    attrs = []
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
    if crs_origen:
        gdf = gdf.set_crs(crs_origen)

    # Reproyectar al CRS del raster de referencia
    if gdf.crs is not None and crs_referencia is not None:
        try:
            gdf = gdf.to_crs(crs_referencia)
        except Exception:
            pass

    # Determinar valor a rasterizar
    if valor_field and valor_field in gdf.columns:
        try:
            gdf["_valor"] = gdf[valor_field].astype(float)
        except Exception:
            gdf["_valor"] = 1.0
        shapes = ((g, v) for g, v in zip(gdf.geometry, gdf["_valor"]))
        dtype = np.float32
        fill = np.nan
    else:
        shapes = ((g, 1.0) for g in gdf.geometry)
        dtype = np.float32
        fill = 0.0

    raster = rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform_referencia,
        fill=fill,
        dtype=dtype,
        all_touched=False,
    )
    return raster


# ──────────────────────────────────────────────────────────────────────────────
# Transformaciones fuzzy aplicadas a los datos cargados
# ──────────────────────────────────────────────────────────────────────────────

def _aplicar_fuzzy(
    data: np.ndarray,
    config: EvidenciaConfig,
    nombre: str,
) -> np.ndarray:
    """Aplica la función de pertenencia fuzzy según la configuración."""
    valid_mask = np.isfinite(data)
    out = np.zeros_like(data, dtype=np.float32)

    if config.tipo == "sigmoid_up":
        umbral = float(config.params.get("umbral", 1.0))
        pend   = float(config.params.get("pendiente", 4.0))
        out[valid_mask] = _fuzzy_sigmoid_up(data[valid_mask], umbral, pend)

    elif config.tipo == "sigmoid_dn":
        umbral = float(config.params.get("umbral", 0.5))
        pend   = float(config.params.get("pendiente", 4.0))
        out[valid_mask] = _fuzzy_sigmoid_dn(data[valid_mask], umbral, pend)

    elif config.tipo == "gaussian":
        modo = config.params.get("modo", "extremos")
        valid_data = data[valid_mask]
        if len(valid_data) == 0:
            return out
        p2  = float(np.nanpercentile(valid_data, 2))
        p98 = float(np.nanpercentile(valid_data, 98))
        if modo == "extremos":
            out[valid_mask] = _fuzzy_extremos(valid_data, p2, p98)
        elif modo == "alto":
            centro = p98
            sigma  = max((p98 - p2) / 4.0, 1e-6)
            out[valid_mask] = _fuzzy_gaussian(valid_data, centro, sigma)
        else:  # bajo
            centro = p2
            sigma  = max((p98 - p2) / 4.0, 1e-6)
            out[valid_mask] = _fuzzy_gaussian(valid_data, centro, sigma)

    elif config.tipo == "categorica":
        # Para geología: presencia=1, ausencia=0 (más sofisticado en futuro)
        out[valid_mask] = np.clip(data[valid_mask], 0.0, 1.0)

    else:
        out[valid_mask] = np.clip(data[valid_mask], 0.0, 1.0)

    return out


# ──────────────────────────────────────────────────────────────────────────────
# Función principal
# ──────────────────────────────────────────────────────────────────────────────

def generar_mapa_prospectividad(
    db_path: Path,
    metodo: str = "fuzzy",
    evidencias_solicitadas: Optional[list[str]] = None,
    pesos_custom: Optional[dict[str, float]] = None,
    gamma: float = 0.75,
    reduccion: int = 4,
    on_step: Optional[Callable[[str], None]] = None,
) -> ProspectivityResult:
    """
    Genera mapa de prospectividad mineral combinando todas las evidencias
    disponibles en la DB del proyecto.

    Args:
        db_path:      Ruta a terraf.db
        metodo:       'fuzzy' (gamma operator), 'overlay' (suma ponderada),
                      'and' (mínimo), 'or' (máximo)
        evidencias_solicitadas:
                      Lista de nombres a usar. Si None, usa todas las disponibles.
        pesos_custom: Override de pesos: {'ior': 0.4, ...}. Se normalizan a 1.
        gamma:        Parámetro del operador fuzzy gamma (0-1). Default 0.75.
        reduccion:    Factor de reducción del raster (1=full res, 4=1/4).
        on_step:      Callback de progreso.

    Returns:
        ProspectivityResult con paths al GeoTIFF y HTML generados.
    """
    import rasterio
    from rasterio.transform import array_bounds
    from rasterio.warp import transform_bounds
    from rasterio.crs import CRS

    if on_step:
        on_step("Detectando evidencias disponibles...")

    disponibles = _detectar_evidencias(db_path)
    if not disponibles:
        raise RuntimeError(
            "No hay evidencias disponibles. Ejecuta primero 'terraf indices' "
            "para calcular índices espectrales."
        )

    # Filtrar a las solicitadas (si aplica)
    if evidencias_solicitadas:
        disponibles = {
            k: v for k, v in disponibles.items()
            if k in evidencias_solicitadas
        }

    if not disponibles:
        raise RuntimeError("Ninguna de las evidencias solicitadas está disponible.")

    if on_step:
        nombres = ", ".join(disponibles.keys())
        on_step(f"Evidencias detectadas: {nombres}")

    # ── Cargar raster de referencia (de un índice raster) ────────────────────
    rasters_disponibles = [
        Path(d["ruta_raster"]) for d in disponibles.values()
        if d["tipo"] == "raster"
    ]
    if not rasters_disponibles:
        raise RuntimeError(
            "Se requiere al menos un índice espectral (raster) como base. "
            "Ejecuta 'terraf indices' primero."
        )

    if on_step:
        on_step(f"Cargando grid de referencia (reducción 1/{reduccion})...")

    _, transform, crs_ref, h, w, _ = _cargar_raster_referencia(
        rasters_disponibles, reduccion=reduccion,
    )
    out_shape = (h, w)

    # ── Cargar y aplicar fuzzy a cada evidencia ──────────────────────────────
    fuzzy_layers: dict[str, np.ndarray] = {}
    pesos_efectivos: dict[str, float] = {}

    for nombre, info in disponibles.items():
        config = EVIDENCIAS_DEFAULT.get(nombre)
        if config is None:
            if on_step:
                on_step(f"  [skip] '{nombre}' sin configuración fuzzy definida")
            continue

        if on_step:
            on_step(f"  procesando '{nombre}' ({info['tipo']})...")

        if info["tipo"] == "raster":
            data = _cargar_raster_indice(Path(info["ruta_raster"]), out_shape)
            data = data.astype(np.float32)
            data[~np.isfinite(data)] = np.nan

        elif info["tipo"] == "vector":
            valor_field = None
            if nombre == "magnetico":
                valor_field = "RANGO_CODE"
            elif nombre == "gravimetria":
                valor_field = "VALOR"
            data = _rasterizar_vector(
                db_path,
                dato_id=info["dato_id"],
                crs_referencia=crs_ref,
                transform_referencia=transform,
                out_shape=out_shape,
                crs_origen=info.get("crs"),
                valor_field=valor_field,
            )
        else:
            continue

        fuzzy = _aplicar_fuzzy(data, config, nombre)
        fuzzy_layers[nombre] = fuzzy

        peso = (
            pesos_custom.get(nombre) if pesos_custom else None
        ) or config.peso
        pesos_efectivos[nombre] = float(peso)

    if not fuzzy_layers:
        raise RuntimeError("No se pudo procesar ninguna evidencia.")

    # Normalizar pesos a suma 1
    suma_pesos = sum(pesos_efectivos.values()) or 1.0
    pesos_norm = {k: v / suma_pesos for k, v in pesos_efectivos.items()}

    # ── Combinar capas ────────────────────────────────────────────────────────
    if on_step:
        on_step(f"Combinando {len(fuzzy_layers)} capas con método '{metodo}'...")

    # Aplicar pesos: capa_ponderada = capa^(1/peso_norm * 0.5)
    # (peso alto = menos atenuación, peso bajo = más atenuación)
    layers_pond: list[np.ndarray] = []
    for nombre, layer in fuzzy_layers.items():
        p = pesos_norm[nombre]
        # Escalar exponencialmente: peso 0.5 → exp 1.0 (sin cambio)
        exp = 0.5 / max(p, 0.05)
        layers_pond.append(np.power(layer, exp))

    if metodo == "fuzzy":
        prob = _fuzzy_gamma(layers_pond, gamma=gamma)
    elif metodo == "overlay":
        # Suma ponderada lineal
        prob = np.zeros_like(layers_pond[0])
        for nombre, layer in fuzzy_layers.items():
            prob = prob + pesos_norm[nombre] * layer
    elif metodo == "and":
        prob = _fuzzy_and(list(fuzzy_layers.values()))
    elif metodo == "or":
        prob = _fuzzy_or(list(fuzzy_layers.values()))
    else:
        raise ValueError(f"Método desconocido: {metodo}")

    prob = np.clip(prob, 0.0, 1.0).astype(np.float32)

    # ── Estadísticas ─────────────────────────────────────────────────────────
    valid = np.isfinite(prob)
    estadisticas = {
        "min":     float(np.nanmin(prob[valid])) if valid.any() else 0.0,
        "max":     float(np.nanmax(prob[valid])) if valid.any() else 0.0,
        "media":   float(np.nanmean(prob[valid])) if valid.any() else 0.0,
        "std":     float(np.nanstd(prob[valid])) if valid.any() else 0.0,
        "p_alta":  float((prob[valid] > 0.7).sum()) / max(valid.sum(), 1),
        "p_muy_alta": float((prob[valid] > 0.85).sum()) / max(valid.sum(), 1),
    }

    # ── Guardar GeoTIFF ──────────────────────────────────────────────────────
    project_dir = db_path.parent
    out_dir = project_dir / "resultados" / "indices"
    out_dir.mkdir(parents=True, exist_ok=True)
    raster_path = out_dir / "prospectividad.tif"

    if on_step:
        on_step(f"Guardando raster: {raster_path.name}")

    with rasterio.open(
        raster_path, "w",
        driver="GTiff",
        height=h, width=w,
        count=1, dtype="float32",
        crs=crs_ref,
        transform=transform,
        nodata=np.nan,
        compress="deflate",
    ) as dst:
        dst.write(prob, 1)

    # ── Generar HTML con Folium ──────────────────────────────────────────────
    if on_step:
        on_step("Generando mapa HTML...")

    html_path = _generar_mapa_html(
        raster_path=raster_path,
        prob=prob,
        transform=transform,
        crs=crs_ref,
        evidencias=list(fuzzy_layers.keys()),
        pesos=pesos_norm,
        metodo=metodo,
        estadisticas=estadisticas,
        out_dir=project_dir / "resultados" / "mapas",
    )

    # Bounds en WGS84 para el resultado
    minx, miny, maxx, maxy = array_bounds(h, w, transform)
    if crs_ref and crs_ref.to_epsg() != 4326:
        bounds_wgs84 = transform_bounds(crs_ref, CRS.from_epsg(4326),
                                         minx, miny, maxx, maxy)
    else:
        bounds_wgs84 = (minx, miny, maxx, maxy)

    if on_step:
        on_step(f"Mapa de prospectividad listo: {html_path.name}")

    return ProspectivityResult(
        raster_path=raster_path,
        html_path=html_path,
        evidencias_usadas=list(fuzzy_layers.keys()),
        pesos_normalizados=pesos_norm,
        metodo=metodo,
        bounds=bounds_wgs84,
        estadisticas=estadisticas,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Generación de mapa HTML
# ──────────────────────────────────────────────────────────────────────────────

def _generar_mapa_html(
    raster_path: Path,
    prob: np.ndarray,
    transform,
    crs,
    evidencias: list[str],
    pesos: dict[str, float],
    metodo: str,
    estadisticas: dict,
    out_dir: Path,
) -> Path:
    """Genera mapa HTML con Folium: raster jet sobrepuesto + leyenda + colorbar."""
    import folium
    import branca.colormap as bcm
    from rasterio.transform import array_bounds
    from rasterio.warp import transform_bounds
    from rasterio.crs import CRS
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)

    # Bounds WGS84
    h, w = prob.shape
    minx, miny, maxx, maxy = array_bounds(h, w, transform)
    if crs and crs.to_epsg() != 4326:
        wmin, smin, emin, nmin = transform_bounds(
            crs, CRS.from_epsg(4326), minx, miny, maxx, maxy
        )
    else:
        wmin, smin, emin, nmin = minx, miny, maxx, maxy

    # ── Raster a PNG con colormap jet (matplotlib) ────────────────────────────
    cmap = plt.get_cmap("jet")
    prob_norm = np.clip(prob, 0.0, 1.0)
    rgba = (cmap(prob_norm) * 255).astype(np.uint8)
    # Transparencia donde no hay datos (NaN)
    alpha = np.where(np.isfinite(prob), 200, 0).astype(np.uint8)
    rgba[..., 3] = alpha

    png_path = out_dir / "prospectividad_overlay.png"
    Image.fromarray(rgba).save(png_path)

    # ── Mapa Folium ───────────────────────────────────────────────────────────
    center_lat = (smin + nmin) / 2.0
    center_lon = (wmin + emin) / 2.0

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=9,
        tiles="CartoDB positron",
    )
    folium.TileLayer(
        "Esri.WorldImagery", name="Satélite", overlay=False, control=True,
    ).add_to(m)

    # Overlay del raster
    folium.raster_layers.ImageOverlay(
        name="Prospectividad",
        image=str(png_path),
        bounds=[[smin, wmin], [nmin, emin]],
        opacity=0.75,
        interactive=True,
        cross_origin=False,
    ).add_to(m)

    # Colorbar (jet, 0-1)
    jet_colors = [
        "#00007F", "#0000FF", "#007FFF", "#00FFFF",
        "#7FFF7F", "#FFFF00", "#FF7F00", "#FF0000", "#7F0000",
    ]
    colormap = bcm.LinearColormap(
        colors=jet_colors, vmin=0.0, vmax=1.0,
        caption="Probabilidad de mineralización (0=baja, 1=alta)",
    )
    colormap.add_to(m)

    # Título flotante
    titulo_html = (
        f'<div style="position:fixed;top:12px;left:60px;z-index:9999;'
        f'background:rgba(255,255,255,0.95);padding:10px 16px;border-radius:6px;'
        f'font-family:sans-serif;font-size:13px;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.25);max-width:340px;">'
        f'<b>Mapa de Prospectividad Mineral</b><br>'
        f'<span style="font-size:11px;color:#555;">'
        f'Método: <b>{metodo}</b> · {len(evidencias)} evidencias<br>'
        f'p&gt;0.70: <b>{estadisticas["p_alta"]*100:.1f}%</b> del área · '
        f'p&gt;0.85: <b>{estadisticas["p_muy_alta"]*100:.2f}%</b>'
        f'</span></div>'
    )
    m.get_root().html.add_child(folium.Element(titulo_html))

    # Panel de evidencias y pesos
    items = "".join(
        f'<li style="font-size:11px;margin:2px 0;">'
        f'<b>{ev}</b>: {pesos[ev]*100:.0f}%</li>'
        for ev in evidencias
    )
    panel_html = (
        f'<div style="position:fixed;top:90px;left:60px;z-index:9999;'
        f'background:rgba(255,255,255,0.95);padding:8px 14px;border-radius:6px;'
        f'font-family:sans-serif;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.25);">'
        f'<b style="font-size:11px;">Evidencias y pesos</b>'
        f'<ul style="list-style:none;padding:0;margin:4px 0 0;">{items}</ul>'
        f'</div>'
    )
    m.get_root().html.add_child(folium.Element(panel_html))

    folium.LayerControl(collapsed=False).add_to(m)

    html_path = out_dir / "mapa_prospectividad.html"
    m.save(str(html_path))
    return html_path
