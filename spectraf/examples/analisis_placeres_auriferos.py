"""
Análisis Integrado para Placeres Auríferos
==========================================

Flujo de 5 fases:

  Fase 1 – Armonización de Datos
      Reproyección al mismo CRS, recorte a la extensión Landsat 9 y
      rasterización de la litología SGM a 30 m/píxel.

  Fase 2 – Extracción de Firmas Espectrales
      Iron Oxide Ratio (B4/B2) y Clay Ratio (B6/B7),
      ambos normalizados 0–1 para comparabilidad.

  Fase 3 – Filtro Geológico (La Fuente)
      Máscara binaria de litología favorable (intrusivos, volcánicos,
      conglomerados), con buffer opcional de 500 m en contactos.

  Fase 4 – Integración Lógica AND (El Embudo)
      TARGET si (IOR > umbral) AND (Clay > umbral) AND (litología favorable).

  Fase 5 – Refinamiento Morfológico y Vectorización
      Limpieza de píxeles aislados, clustering, cálculo de prioridad
      y exportación a GeoJSON + Shapefile.

Uso:
    python examples/analisis_placeres_auriferos.py

Requisitos:
    conda env create -f environment.yml && conda activate spectraf
"""

import warnings
from pathlib import Path
from typing import List, Tuple

# ─── Terceros ─────────────────────────────────────────────────────────────────
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import rasterio.transform as riot
from rasterio.features import rasterize as rio_rasterize
import geopandas as gpd
from shapely.geometry import box, Point

# ─── spectraf ─────────────────────────────────────────────────────────────────
import spectraf
from spectraf.core import SatelliteImage
from spectraf.visualization import normalize_ratio, normalize_band

# Silenciar divisiones entre cero de los ratios espectrales (comportamiento esperado)
np.seterr(divide='ignore', invalid='ignore')

# scipy para limpieza morfológica y clustering (Fase 5)
try:
    from scipy import ndimage
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    warnings.warn(
        "scipy no disponible – se omitirá el filtro morfológico (Fase 5).\n"
        "Instala con: pip install scipy",
        stacklevel=2
    )

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║            ► EMPIEZA AQUÍ – CONFIGURA TUS DATOS Y PARÁMETROS ◄               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ─── 1. RUTAS ──────────────────────────────────────────────────────────────────
#  Pon aqui tus rutas. Por defecto apuntan a spectraf/datos/ y spectraf/results/
#  Si tienes los datos en otro disco o carpeta, cambia solo estas dos líneas:

DATA_PATH  = ROOT.parent / 'datos'  # <- carpeta que contiene landsat9/ y SGM/
OUTPUT_DIR = ROOT / 'results'   # <- donde se guardan PNG, GeoJSON y Shapefile

# ─── 2. IDENTIFICADORES DE TU ESCENA Y CARTA ──────────────────────────────────
#  SCENE_ID: nombre de la carpeta descargada de EarthExplorer (sin extensión)
#  CARTA_ID: nombre de la carpeta descargada del SGM

SCENE_ID = 'LC09_L2SP_031042_20260212_20260213_02_T1'
CARTA_ID = 'A18022026162831O'

# ─── 3. UMBRALES ESPECTRALES (Fase 4) ─────────────────────────────────────────
#  Valor normalizado 0–1. Subir = menos targets (más estricto).
#                         Bajar = más targets  (más permisivo).

IRON_THRESHOLD = 0.65   # Iron Oxide Ratio mínimo para ser target
CLAY_THRESHOLD = 0.55   # Clay Ratio mínimo para ser target

# ─── 4. PARÁMETROS DE PROCESAMIENTO ───────────────────────────────────────────
#  PROCESS_DOWNSAMPLE: 1 = full res (lento), 4 = aprox 16x mas rápido (recomendado)
#  APPLY_BUFFER      : True crea un área de influencia de BUFFER_DIST metros

PROCESS_DOWNSAMPLE = 4       # factor de submuestreo para el análisis
APPLY_BUFFER       = True    # buffer alrededor de unidades favorables
BUFFER_DIST        = 500.0   # metros
MORPH_CLOSING_ITER = 2       # iteraciones closing (rellena huecos en Fase 5)
MORPH_OPENING_ITER = 1       # iteraciones opening (elimina ruido en Fase 5)
MIN_CLUSTER_PX     = 3       # píxeles mínimos por cluster (a resolución reducida)

# ─── 5. LITOLOGÍA FAVORABLE ────────────────────────────────────────────────────
#  Substrings a buscar en la columna LITOLOGIA del SGM.
#  Un polígono es "favorable" si su nombre contiene alguna de estas palabras.
#  Ajusta según las unidades de tu carta geológica.

FAVORABLE_PATTERNS: List[str] = [
    'Basalto',          # Volcánico básico  – fuente Fe/Au
    'Ignimbrita',       # Piroclástico silícico – portador de Au
    'Toba',             # Piroclástica – zona de alteración
    'Riolita',          # Félsico – vetas de cuarzo
    'Andesita',         # Volcánico intermedio
    'Conglomerado',     # Placer potencial
    'Granito',          # Plutónico – fuente primaria de Au
    'Diorita',          # Plutónico intermedio
    'Brecha',           # Canal de mineralización
    'Cuarzo',           # Veta de cuarzo
    'Arenisca',         # Placer antiguo litificado
]

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║           FIN DE LA CONFIGURACIÓN – no necesitas tocar nada más              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def separator(title: str) -> None:
    print(f"\n{'═' * 78}")
    print(f"  {title}")
    print('═' * 78 + '\n')


def _pix_to_utm(y_pix: int, x_pix: int, transform) -> Tuple[float, float]:
    """Convierte coordenadas de píxel (row, col) al centro del píxel en UTM."""
    x_utm = transform.c + (x_pix + 0.5) * transform.a
    y_utm = transform.f + (y_pix + 0.5) * transform.e
    return x_utm, y_utm


def _utm_to_pix(x_utm: float, y_utm: float, transform) -> Tuple[int, int]:
    """Convierte coordenadas UTM a píxel (row, col)."""
    col = int((x_utm - transform.c) / transform.a)
    row = int((y_utm - transform.f) / transform.e)
    return row, col


def downsample_image(image, factor: int):
    """
    Devuelve un nuevo SatelliteImage con las bandas submuestreadas y el
    transform/metadata actualizados.  factor=4 → 16× menos píxeles.
    """
    if factor <= 1:
        return image
    new_bands = {k: v[::factor, ::factor].astype(np.float32)
                 for k, v in image.bands.items()}
    old_t = image.metadata['transform']
    new_t = riot.Affine(
        old_t.a * factor, old_t.b, old_t.c,
        old_t.d, old_t.e * factor, old_t.f
    )
    new_meta = image.metadata.copy()
    h, w = next(iter(new_bands.values())).shape
    new_meta['transform'] = new_t
    new_meta['height']    = h
    new_meta['width']     = w
    return SatelliteImage(new_bands, new_meta, image.sensor_type)


# ═══════════════════════════════════════════════════════════════════════════════
#  FASE 1 – ARMONIZACIÓN DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════
def fase1_armonizar(image, litologia_gdf):
    """
    Reproyecta, recorta y rasteriza la litología al grid del Landsat 9.

    Returns
    -------
    litologia_clip : GeoDataFrame recortado al extent del Landsat (CRS armonizado)
    litho_raster   : np.ndarray bool (H, W) – True donde litología es favorable
    favorable_gdf  : GeoDataFrame con solo unidades litológicas favorables
    """
    separator("FASE 1 / Armonización de Datos  (Reproyección · Recorte · Rasterización)")

    landsat_crs   = image.metadata['crs']
    bounds        = image.metadata['bounds']
    height, width = image.shape()
    transform     = image.metadata['transform']

    # ── 1-A: Reproyección ────────────────────────────────────────────────────
    if litologia_gdf.crs is None or str(litologia_gdf.crs) != landsat_crs:
        print(f"  Reproyectando litología  {litologia_gdf.crs} → {landsat_crs} ...")
        litologia_gdf = litologia_gdf.to_crs(landsat_crs)
    else:
        print(f"  ✓ CRS ya coinciden: {landsat_crs}  (sin reproyección necesaria)")

    # ── 1-B: Recorte a la extensión del Landsat ──────────────────────────────
    bbox = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
    litologia_clip = litologia_gdf[litologia_gdf.intersects(bbox)].copy()
    litologia_clip = litologia_clip.clip(bbox)
    print(f"  ✓ Recorte: {len(litologia_clip):,} polígonos conservados "
          f"(de {len(litologia_gdf):,} totales)")

    # ── 1-C: Identificar unidades favorables ─────────────────────────────────
    litho_col = next(
        (c for c in ['LITOLOGIA', 'CVE_LITOLO', 'ROCA', 'CLAVE']
         if c in litologia_clip.columns),
        None
    )
    if litho_col:
        mask_fav = litologia_clip[litho_col].apply(
            lambda x: any(p.lower() in str(x).lower() for p in FAVORABLE_PATTERNS)
        )
        favorable_gdf = litologia_clip[mask_fav].copy()
        favorable_gdf['favorable'] = 1
        print(f"  ✓ Columna litológica detectada: '{litho_col}'")
    else:
        print("  ⚠ No se encontró columna de litología – todo el área se marca favorable")
        favorable_gdf = litologia_clip.copy()
        favorable_gdf['favorable'] = 1

    print(f"  ✓ Unidades favorables: {len(favorable_gdf):,} de {len(litologia_clip):,} polígonos")
    if litho_col and len(favorable_gdf) > 0:
        tipos = favorable_gdf[litho_col].value_counts().head(8)
        print("    Tipos favorables encontrados:")
        for litho_type, cnt in tipos.items():
            print(f"      • {litho_type}: {cnt}")

    # ── 1-D: Rasterización → máscara binaria 30 m/píxel ──────────────────────
    if len(favorable_gdf) > 0:
        shapes = (
            (geom, 1)
            for geom in favorable_gdf.geometry
            if geom is not None and not geom.is_empty
        )
        litho_raster = rio_rasterize(
            shapes,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype='uint8'
        ).astype(bool)
    else:
        litho_raster = np.zeros((height, width), dtype=bool)
        print("  ⚠ Sin unidades favorables – máscara litológica vacía")

    pct = litho_raster.mean() * 100
    print(f"  ✓ Rasterización: {pct:.1f}% del área total es litología favorable")

    return litologia_clip, litho_raster, favorable_gdf


# ═══════════════════════════════════════════════════════════════════════════════
#  FASE 2 – EXTRACCIÓN DE FIRMAS ESPECTRALES
# ═══════════════════════════════════════════════════════════════════════════════
def fase2_indices_espectrales(image):
    """
    Calcula Iron Oxide Ratio (B4/B2) y Clay Ratio (B6/B7),
    ambos normalizados a [0, 1] mediante recorte por percentiles.

    Returns
    -------
    ior_norm  : np.ndarray float32 – Iron Oxide Ratio normalizado
    clay_norm : np.ndarray float32 – Clay Ratio normalizado
    """
    separator("FASE 2 / Extracción de Firmas Espectrales")
    print("  Calculando índices espectrales...")

    ior_img  = spectraf.calculate_iron_oxide_ratio(image)   # B4 / B2
    clay_img = spectraf.calculate_clay_ratio(image)         # B6 / B7

    ior_raw  = ior_img.get_band('Iron_Oxide_Ratio')
    clay_raw = clay_img.get_band('Clay_Ratio')

    # Normalizar 0–1 con recorte al 2% de outliers
    ior_norm  = normalize_ratio(ior_raw,  percentile_clip=2.0)
    clay_norm = normalize_ratio(clay_raw, percentile_clip=2.0)

    ior_valid  = ior_raw[ior_raw > 0]
    clay_valid = clay_raw[clay_raw > 0]

    print(f"  ✓ Iron Oxide Ratio  – raw: [{ior_valid.min():.3f}, {ior_valid.max():.3f}]"
          f"  →  norm: [{ior_norm.min():.3f}, {ior_norm.max():.3f}]")
    print(f"  ✓ Clay Ratio        – raw: [{clay_valid.min():.3f}, {clay_valid.max():.3f}]"
          f"  →  norm: [{clay_norm.min():.3f}, {clay_norm.max():.3f}]")
    print(f"  Umbrales de decisión: IOR > {IRON_THRESHOLD}  |  Clay > {CLAY_THRESHOLD}")

    _guardar_figura_fase2(ior_norm, clay_norm, image)

    return ior_norm, clay_norm


def _guardar_figura_fase2(ior_norm, clay_norm, image):
    ds = 2
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    im0 = axes[0].imshow(ior_norm[::ds, ::ds], cmap='YlOrRd', vmin=0, vmax=1)
    axes[0].set_title('Iron Oxide Ratio  B4/B2\n(Hematita · Magnetita · Arenas negras)',
                      fontsize=11, fontweight='bold')
    axes[0].axis('off')
    plt.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.02)
    axes[0].axhline(0, color='none')   # dummy para que límite 0 sea visible

    im1 = axes[1].imshow(clay_norm[::ds, ::ds], cmap='RdPu', vmin=0, vmax=1)
    axes[1].set_title('Clay / Hydroxyl Ratio  B6/B7\n(Alteración hidrotermal · Arcillas)',
                      fontsize=11, fontweight='bold')
    axes[1].axis('off')
    plt.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.02)

    fig.suptitle(
        f'Fase 2 – Firmas Espectrales  |  {SCENE_ID}  |  {image.metadata.get("date", "")}',
        fontsize=10, style='italic'
    )
    plt.tight_layout()
    out = OUTPUT_DIR / 'fase2_firmas_espectrales.png'
    plt.savefig(out, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figura: {out.relative_to(ROOT)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  FASE 3 – FILTRO GEOLÓGICO
# ═══════════════════════════════════════════════════════════════════════════════
def fase3_filtro_geologico(favorable_gdf, litologia_clip, image, litho_raster_base):
    """
    Genera la máscara geológica definitiva.
    Recibe `litho_raster_base` ya calculado en Fase 1 para evitar
    rasterizar los mismos polígonos dos veces.
    Opcionalmente aplica un buffer para capturar la aureola de
    influencia alrededor de los contactos geológicos favorables.

    Returns
    -------
    geo_mask : np.ndarray bool (H, W)
    """
    separator("FASE 3 / Filtro Geológico  (Roca Madre Favorable + Buffer de Contactos)")

    height, width = image.shape()
    transform     = image.metadata['transform']

    if len(favorable_gdf) == 0:
        print("  ⚠ Sin unidades favorables – geo_mask vacía")
        return np.zeros((height, width), dtype=bool)

    # Máscara base reutilizada desde Fase 1 (sin doble rasterización)
    geo_mask = litho_raster_base.copy()
    print(f"  ✓ Máscara base litología: {geo_mask.sum():,} píxeles favorables  (reutilizada de Fase 1)")

    # Buffer opcional
    if APPLY_BUFFER:
        print(f"  Calculando buffer de {BUFFER_DIST:.0f} m en contactos geológicos...")
        buffered_geoms = favorable_gdf.copy()
        buffered_geoms['geometry'] = favorable_gdf.geometry.buffer(BUFFER_DIST)
        shapes_buf = [
            (geom, 1) for geom in buffered_geoms.geometry
            if geom is not None and not geom.is_empty
        ]
        buf_mask = rio_rasterize(
            shapes_buf,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype='uint8'
        ).astype(bool)
        # Agregar el buffer a la máscara (conserva la base + zona de influencia)
        geo_mask = geo_mask | buf_mask
        print(f"  ✓ Con buffer {BUFFER_DIST:.0f} m: {geo_mask.sum():,} píxeles en zona de influencia"
              f"  ({geo_mask.mean()*100:.1f}% del área)")

    _guardar_figura_fase3(geo_mask, favorable_gdf, litologia_clip, image)

    return geo_mask


def _guardar_figura_fase3(geo_mask, favorable_gdf, litologia_clip, image):
    ds = 2
    # Construir imagen RGB base (color natural) para el fondo
    try:
        r = normalize_band(image.get_band('B4')[::ds, ::ds], 2.0)
        g = normalize_band(image.get_band('B3')[::ds, ::ds], 2.0)
        b = normalize_band(image.get_band('B2')[::ds, ::ds], 2.0)
        rgb_base = np.dstack([r, g, b])
    except Exception:
        rgb_base = None

    bounds = image.metadata['bounds']
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]

    fig, ax = plt.subplots(figsize=(13, 10))

    if rgb_base is not None:
        ax.imshow(rgb_base, extent=extent, origin='upper', aspect='auto')

    # Litología total (contornos grises)
    litologia_clip.plot(ax=ax, edgecolor='#888888', facecolor='none', linewidth=0.4)

    # Unidades favorables (amarillo)
    if len(favorable_gdf) > 0:
        favorable_gdf.plot(ax=ax, edgecolor='#FFD700', facecolor='#FFD700',
                           linewidth=0.6, alpha=0.35)

    # Contorno de la máscara (buffer)
    geo_display = geo_mask[::ds, ::ds].astype(np.uint8)
    ax.contour(geo_display, levels=[0.5], colors='cyan', linewidths=1.0,
               extent=extent, origin='upper')

    patch_fav = mpatches.Patch(color='#FFD700', alpha=0.6, label='Litología favorable')
    patch_buf = mpatches.Patch(edgecolor='cyan', facecolor='none', label=f'Buffer {BUFFER_DIST:.0f} m')
    patch_all = mpatches.Patch(edgecolor='#888888', facecolor='none', label='Litología total')
    ax.legend(handles=[patch_fav, patch_buf, patch_all], fontsize=9, framealpha=0.8)

    ax.set_title('Fase 3 – Filtro Geológico\n'
                 'Litología favorable + Zona de influencia (buffer)',
                 fontsize=12, fontweight='bold')
    ax.set_xlabel('UTM Este (m)')
    ax.set_ylabel('UTM Norte (m)')

    out = OUTPUT_DIR / 'fase3_filtro_geologico.png'
    plt.tight_layout()
    plt.savefig(out, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figura: {out.relative_to(ROOT)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  FASE 4 – INTEGRACIÓN LÓGICA AND
# ═══════════════════════════════════════════════════════════════════════════════
def fase4_integracion_logica(ior_norm, clay_norm, geo_mask):
    """
    Combina los tres criterios con operación booleana AND:

        TARGET = (IOR > IRON_THRESHOLD)
               AND (Clay > CLAY_THRESHOLD)
               AND (litología = favorable)

    Returns
    -------
    target_mask : np.ndarray bool  – mapa binario de targets potenciales
    composite   : np.ndarray float – índice de favorabilidad compuesto (0–1)
    """
    separator("FASE 4 / Integración Lógica AND  (El Embudo de Selección)")

    iron_mask = ior_norm  > IRON_THRESHOLD
    clay_mask = clay_norm > CLAY_THRESHOLD

    target_mask = iron_mask & clay_mask & geo_mask

    total = target_mask.size
    for label, mask in [
        (f'IOR     > {IRON_THRESHOLD:.2f}', iron_mask),
        (f'Clay    > {CLAY_THRESHOLD:.2f}', clay_mask),
        ('Litología favorable',              geo_mask),
        ('TARGET  (AND de 3)',               target_mask),
    ]:
        n = mask.sum()
        print(f"  {label:>30s} :  {n:>10,d} px  ({n/total*100:.2f}%)")

    if target_mask.sum() == 0:
        print("\n  ⚠  Sin targets con estos umbrales.")
        print(f"     Prueba bajar IRON_THRESHOLD ({IRON_THRESHOLD}) o CLAY_THRESHOLD ({CLAY_THRESHOLD}).")

    # Índice compuesto = promedio de los tres scores ponderados
    # Solo se conserva donde los 3 criterios se cumplen
    composite = (ior_norm + clay_norm + geo_mask.astype(np.float32)) / 3.0
    composite = np.where(target_mask, composite, 0.0).astype(np.float32)

    _guardar_figura_fase4(iron_mask, clay_mask, geo_mask, target_mask)

    return target_mask, composite


def _guardar_figura_fase4(iron_mask, clay_mask, geo_mask, target_mask):
    ds = 2
    masks  = [iron_mask, clay_mask, geo_mask, target_mask]
    titles = [
        f'Criterio 1 · Iron Oxide\n> {IRON_THRESHOLD:.2f}',
        f'Criterio 2 · Clay Ratio\n> {CLAY_THRESHOLD:.2f}',
        'Criterio 3 · Litología\nFavorable',
        'TARGET FINAL\nAND de 3 criterios',
    ]
    cmaps  = ['YlOrRd', 'RdPu', 'Greens', 'hot']

    fig, axes = plt.subplots(1, 4, figsize=(22, 6))
    for ax, title, mask, cmap in zip(axes, titles, masks, cmaps):
        ax.imshow(mask[::ds, ::ds].astype(np.float32), cmap=cmap, vmin=0, vmax=1)
        pct = mask.mean() * 100
        ax.set_title(title, fontsize=10, fontweight='bold')
        ax.set_xlabel(f'{pct:.2f}% del área', fontsize=9)
        ax.axis('off')

    fig.suptitle(
        'Fase 4 – Integración Lógica AND  · Reducción progresiva del área objetivo',
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout()
    out = OUTPUT_DIR / 'fase4_integracion_logica.png'
    plt.savefig(out, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figura: {out.relative_to(ROOT)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  FASE 5 – REFINAMIENTO MORFOLÓGICO Y VECTORIZACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
def fase5_refinamiento_vectorizacion(target_mask, composite, ior_norm, image):
    """
    Pipeline completo de refinamiento:
        5-A  Limpieza morfológica (closing / opening)
        5-B  Clustering de píxeles conectados
        5-C  Cálculo de score de prioridad por cluster
        5-D  Conversión a GeoDataFrame georreferenciado
        5-E  Visualización final
        5-F  Exportación a GeoJSON y Shapefile

    Returns
    -------
    targets_gdf : GeoDataFrame con targets de exploración priorizados
    """
    separator("FASE 5 / Refinamiento Morfológico + Vectorización de Targets")

    transform = image.metadata['transform']
    crs       = image.metadata['crs']

    # Estructura de conectividad 8 (se reutiliza en closing, opening y label)
    struct = ndimage.generate_binary_structure(2, 2)

    # ── 5-A: Limpieza morfológica ─────────────────────────────────────────────
    print("  [5-A] Limpieza morfológica ...")
    if SCIPY_AVAILABLE:
        clean = ndimage.binary_closing(
            target_mask, structure=struct, iterations=MORPH_CLOSING_ITER
        )
        clean = ndimage.binary_opening(
            clean,       structure=struct, iterations=MORPH_OPENING_ITER
        )
        print(f"       closing x{MORPH_CLOSING_ITER} + opening x{MORPH_OPENING_ITER}")
    else:
        clean = target_mask.copy()
        print("       (scipy no disponible – sin filtro morfológico)")

    n_antes   = target_mask.sum()
    n_despues = clean.sum()
    print(f"  ✓ Antes: {n_antes:,} px → Después: {n_despues:,} px  "
          f"(eliminados: {n_antes - n_despues:,})")

    # ── 5-B: Clustering con scipy (rápido, C nativo) ────────────────────────
    print("\n  [5-B] Agrupando píxeles en clusters (scipy.ndimage.label) ...")

    if not SCIPY_AVAILABLE:
        print("       ⚠ scipy no disponible – sin clustering")
        return gpd.GeoDataFrame(crs=crs)

    labeled, n_labels = ndimage.label(clean, structure=struct)
    print(f"  ✓ Componentes encontradas: {n_labels:,}")

    anomaly_map = clean  # para reutilizar en visualización

    # ── 5-C: Enriquecer con score del composite y tamaño de cluster ──────────
    print("\n  [5-C] Calculando scores y áreas de cluster ...")

    label_ids    = np.arange(1, n_labels + 1)
    # bincount es ~10× más rápido que ndimage.sum para contar píxeles
    sizes        = np.bincount(labeled.ravel())[1:]
    ior_means    = ndimage.mean(ior_norm,  labeled, label_ids)
    comp_means   = ndimage.mean(composite, labeled, label_ids)
    centroids_yx = ndimage.center_of_mass(clean, labeled, label_ids)

    enriched = []
    for i, lbl in enumerate(label_ids):
        sz = int(sizes[i])
        if sz < MIN_CLUSTER_PX:
            continue
        y_pix = int(round(centroids_yx[i][0]))
        x_pix = int(round(centroids_yx[i][1]))
        enriched.append((y_pix, x_pix, float(ior_means[i]),
                         float(comp_means[i]), sz))

    print(f"  ✓ Clusters significativos (≥ {MIN_CLUSTER_PX} px): {len(enriched)}")

    # Ordenar por score compuesto descendente
    enriched.sort(key=lambda t: t[3], reverse=True)

    # ── 5-D: Convertir a GeoDataFrame ────────────────────────────────────────
    print("\n  [5-D] Georreferenciando targets ...")

    # Tamaño real del píxel en metros (ya lleva aplicado PROCESS_DOWNSAMPLE)
    _px_m = abs(transform.a)

    rows = []
    for rank, (y_pix, x_pix, ior_intensity, comp_score, cluster_sz) in enumerate(enriched):
        x_utm, y_utm = _pix_to_utm(y_pix, x_pix, transform)
        area_m2 = cluster_sz * _px_m * _px_m   # área real en m²

        if comp_score >= 0.75:
            prioridad = 'ALTA'
        elif comp_score >= 0.60:
            prioridad = 'MEDIA'
        else:
            prioridad = 'BAJA'

        rows.append({
            'target_id'     : f'T{rank + 1:03d}',
            'rank'          : rank + 1,
            'easting_utm'   : round(x_utm, 1),
            'northing_utm'  : round(y_utm, 1),
            'score'         : round(comp_score, 4),
            'ior_intensity' : round(ior_intensity, 4),
            'cluster_px'    : cluster_sz,
            'area_m2'       : area_m2,
            'area_ha'       : round(area_m2 / 1e4, 2),
            'prioridad'     : prioridad,
            'geometry'      : Point(x_utm, y_utm),
        })

    if rows:
        targets_gdf = gpd.GeoDataFrame(rows, crs=crs)
        print(f"  ✓ {len(targets_gdf)} targets georreferenciados en CRS: {crs}")
        # Resumen por prioridad
        for prio in ['ALTA', 'MEDIA', 'BAJA']:
            n = (targets_gdf['prioridad'] == prio).sum()
            if n:
                print(f"     Prioridad {prio}: {n} targets")
    else:
        targets_gdf = gpd.GeoDataFrame(columns=[
            'target_id', 'rank', 'easting_utm', 'northing_utm',
            'score', 'ior_intensity', 'cluster_px', 'area_m2', 'area_ha',
            'prioridad', 'geometry'
        ], crs=crs)
        print("  ⚠ Sin targets para vectorizar")

    # ── 5-E: Visualización final ──────────────────────────────────────────────
    _guardar_figura_fase5(ior_norm, anomaly_map, targets_gdf, image)

    # ── 5-F: Exportar GeoJSON y Shapefile ────────────────────────────────────
    if len(targets_gdf) > 0:
        geojson_path = OUTPUT_DIR / 'targets_exploracion.geojson'
        targets_gdf.to_file(str(geojson_path), driver='GeoJSON')
        print(f"\n  ✓ GeoJSON exportado :  {geojson_path.relative_to(ROOT)}")

        shp_path = OUTPUT_DIR / 'targets_exploracion.shp'
        spectraf.export_targets_to_shapefile(targets_gdf, shp_path, overwrite=True)
    else:
        print("\n  ⚠ Sin targets para exportar")

    return targets_gdf


def _guardar_figura_fase5(ior_norm, anomaly_map, targets_gdf, image):
    """Mapa final de targets sobre Iron Oxide Ratio (espacio de píxeles)."""
    ds     = 2
    height, width = image.shape()
    transform     = image.metadata['transform']

    fig, ax = plt.subplots(figsize=(14, 12))

    # Fondo: IOR normalizado
    im = ax.imshow(ior_norm[::ds, ::ds], cmap='YlOrRd',
                   origin='upper', aspect='equal')
    plt.colorbar(im, ax=ax, fraction=0.035, pad=0.02,
                 label='Iron Oxide Ratio (normalizado)')

    # Contorno de la zona AND final
    if anomaly_map.any():
        ax.contour(anomaly_map[::ds, ::ds].astype(float),
                   levels=[0.5], colors='cyan', linewidths=1.2)

    # Targets sobre el raster (convertir UTM → píxel)
    colors_prio = {'ALTA': '#00FF44', 'MEDIA': '#FFE000', 'BAJA': '#FF8C00'}
    if len(targets_gdf) > 0:
        for _, row in targets_gdf.iterrows():
            r_pix, c_pix = _utm_to_pix(row['easting_utm'], row['northing_utm'], transform)
            r_ds = r_pix // ds
            c_ds = c_pix // ds
            col  = colors_prio.get(row['prioridad'], 'white')
            ax.plot(c_ds, r_ds, 'o', color=col,
                    markersize=10, markeredgecolor='black', markeredgewidth=1, zorder=10)
            ax.annotate(
                f"{row['target_id']} [{row['prioridad'][0]}]\n"
                f"score={row['score']:.3f} | {row['area_ha']:.1f} ha",
                xy=(c_ds, r_ds),
                xytext=(c_ds + 15, r_ds - 10),
                fontsize=6.5, fontweight='bold', color=col, zorder=11,
                arrowprops=dict(arrowstyle='-', color=col, lw=0.8)
            )

    patches = [
        mpatches.Patch(color=v, label=f'Prioridad {k}')
        for k, v in colors_prio.items()
    ]
    patches.append(
        mpatches.Patch(edgecolor='cyan', facecolor='none', label='Anomalía AND')
    )
    ax.legend(handles=patches, fontsize=8, loc='lower right', framealpha=0.75)

    ax.set_title(
        'Fase 5 – Targets de Exploración para Placeres Auríferos\n'
        'Iron Oxide Ratio | Contornos = zona AND | Puntos = targets priorizados',
        fontsize=12, fontweight='bold'
    )
    ax.axis('off')

    out = OUTPUT_DIR / 'fase5_targets_finales.png'
    plt.tight_layout()
    plt.savefig(out, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Figura: {out.relative_to(ROOT)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORTE FINAL
# ═══════════════════════════════════════════════════════════════════════════════
def reporte_final(targets_gdf, image) -> None:
    separator("RESULTADO FINAL – Reporte de Targets de Exploración")

    meta = image.metadata
    print(f"  Escena  : {meta.get('scene_id', 'N/A')}")
    print(f"  Fecha   : {meta.get('date', 'N/A')}")
    print(f"  CRS     : {meta.get('crs', 'N/A')}")
    print(f"  Umbrales: Iron Oxide > {IRON_THRESHOLD}  |  Clay > {CLAY_THRESHOLD}")
    print()

    if len(targets_gdf) == 0:
        print("  ⚠ No se identificaron targets.")
        print(f"  → Prueba bajar los umbrales "
              f"(IRON_THRESHOLD={IRON_THRESHOLD}, CLAY_THRESHOLD={CLAY_THRESHOLD})")
        return

    total_ha = targets_gdf['area_ha'].sum()
    print(f"  Total targets : {len(targets_gdf)}  |  "
          f"Área total anomalías: {total_ha:.1f} ha\n")

    for prio in ['ALTA', 'MEDIA', 'BAJA']:
        sub = targets_gdf[targets_gdf['prioridad'] == prio]
        if len(sub) == 0:
            continue
        print(f"  ── Prioridad {prio}  ({len(sub)} targets) ────────────────────────")
        for _, row in sub.iterrows():
            print(f"     {row['target_id']}:  "
                  f"UTM ({row['easting_utm']:.0f} E, {row['northing_utm']:.0f} N)  |  "
                  f"Score: {row['score']:.3f}  |  "
                  f"IOR: {row['ior_intensity']:.3f}  |  "
                  f"Área: {row['area_ha']:.1f} ha")
        print()

    print("  Archivos exportados en  spectraf/results/ :")
    for f in sorted(OUTPUT_DIR.glob('*')):
        print(f"    • {f.name}")

    print()
    print("  ─── PRÓXIMOS PASOS RECOMENDADOS ────────────────────────────────────────")
    print("    1. Abrir 'targets_exploracion.geojson' en QGIS / Google Earth")
    print("    2. Validar targets ALTA prioridad en campo (reconocimiento geomorfológico)")
    print("    3. Levantamiento magnetométrico terrestre en targets confirmados")
    print("    4. Muestreo geoquímico de sedimentos activos (bateo exploratorio)")
    print("    5. Geofísica de detalle (GPR / resistividad) en mejores anomalías")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    print('═' * 78)
    print('  ANÁLISIS INTEGRADO DE FAVORABILIDAD – PLACERES AURÍFEROS')
    print('  5 Fases: Armonización → Espectral → Geológico → AND → Targets')
    print('═' * 78)

    # ── Carga de datos base ──────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n  Cargando Landsat 9: {SCENE_ID} ...")
    _img_full = spectraf.load_landsat9_image(
        SCENE_ID, DATA_PATH, bands=['B2', 'B3', 'B4', 'B6', 'B7']
    )
    h0, w0 = _img_full.shape()
    print(f"  ✓ Imagen original: {h0}×{w0} px  |  bandas: {_img_full.list_bands()}")
    print(f"  ✓ CRS: {_img_full.metadata['crs']}  |  fecha: {_img_full.metadata.get('date')}")

    if PROCESS_DOWNSAMPLE > 1:
        print(f"  Submuestreando ×{PROCESS_DOWNSAMPLE} para el análisis "
              f"({h0//PROCESS_DOWNSAMPLE}×{w0//PROCESS_DOWNSAMPLE} px) ...")
        image = downsample_image(_img_full, PROCESS_DOWNSAMPLE)
        h, w  = image.shape()
        print(f"  ✓ Resolución de análisis: {h}×{w} px  "
              f"(~{PROCESS_DOWNSAMPLE*30} m/píxel)")
        del _img_full
    else:
        image = _img_full
        h, w  = image.shape()

    print(f"\n  Cargando litología SGM: {CARTA_ID} ...")
    litologia_gdf = spectraf.load_sgm_litologia(CARTA_ID, DATA_PATH)

    # ── Ejecutar las 5 fases ─────────────────────────────────────────────────
    litologia_clip, litho_raster, favorable_gdf = fase1_armonizar(
        image, litologia_gdf
    )
    ior_norm, clay_norm = fase2_indices_espectrales(image)

    geo_mask = fase3_filtro_geologico(
        favorable_gdf, litologia_clip, image, litho_raster
    )

    target_mask, composite = fase4_integracion_logica(
        ior_norm, clay_norm, geo_mask
    )

    targets_gdf = fase5_refinamiento_vectorizacion(
        target_mask, composite, ior_norm, image
    )

    reporte_final(targets_gdf, image)

    print(f"\n{'═' * 78}")
    print("  ✓ ANÁLISIS COMPLETADO EXITOSAMENTE")
    print(f"{'═' * 78}\n")


if __name__ == '__main__':
    main()
