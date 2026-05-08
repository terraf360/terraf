"""
Utilidades de visualización para imágenes de satélite.
"""
from typing import Optional, Tuple
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt


def normalize_band(
    band: np.ndarray,
    percentile_clip: float = 2.0,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None
) -> np.ndarray:
    """
    Normaliza una banda espectral para mejor visualización.
    
    Args:
        band: Array numpy con los valores de la banda
        percentile_clip: Percentil para recorte (clipea valores extremos)
        vmin: Valor mínimo forzado (opcional)
        vmax: Valor máximo forzado (opcional)
    
    Returns:
        Array normalizado entre 0 y 1
    """
    # Convertir a float32 para ahorrar memoria
    band = band.astype(np.float32)

    # Filtrar valores válidos (finitos; incluye negativos como NDVI < 0)
    valid_mask = np.isfinite(band)

    if not valid_mask.any():
        return band
    
    # Determinar límites
    if vmin is None or vmax is None:
        p_low, p_high = np.percentile(band[valid_mask], [percentile_clip, 100 - percentile_clip])
        if vmin is None:
            vmin = p_low
        if vmax is None:
            vmax = p_high
    
    # Normalizar y clipear (usar dtype para especificar salida)
    normalized = np.clip((band - vmin) / (vmax - vmin), 0, 1, dtype=np.float32)
    return normalized


def get_default_rgb_bands(sensor_type: str) -> Tuple[str, str, str]:
    """
    Obtiene las bandas RGB por defecto según el tipo de sensor.
    
    Args:
        sensor_type: Tipo de sensor ('landsat9', 'sentinel2', etc.)
    
    Returns:
        Tupla con nombres de bandas (red, green, blue)
    """
    if sensor_type == 'landsat9':
        return ('B4', 'B3', 'B2')  # Rojo, Verde, Azul
    elif sensor_type == 'sentinel2':
        return ('B4', 'B3', 'B2')  # Similar en Sentinel-2
    else:
        # Por defecto, intentar con nomenclatura común
        return ('B4', 'B3', 'B2')


def plot_image(
    image,  # SatelliteImage
    natural_color: bool = True,
    bands: Optional[Tuple[str, str, str]] = None,
    cmap: Optional[str] = None,
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (12, 10),
    percentile_clip: float = 2.0,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None
):
    """
    Visualiza una imagen de satélite.

    Args:
        image: Instancia de SatelliteImage
        natural_color: Si True, muestra composición RGB en color natural
        bands: Tupla con 3 nombres de bandas para composición RGB personalizada
        cmap: Mapa de colores para imágenes de una sola banda
        title: Título del gráfico
        figsize: Tamaño de la figura
        percentile_clip: Percentil para recorte en normalización
        vmin: Valor mínimo para escala de colores
        vmax: Valor máximo para escala de colores
    """
    fig, ax = plt.subplots(figsize=figsize)
    _render_on_ax(
        image, ax,
        natural_color=natural_color, bands=bands, cmap=cmap, title=title,
        percentile_clip=percentile_clip, vmin=vmin, vmax=vmax
    )
    plt.tight_layout()
    plt.show()


def plot_comparison(
    images: list,  # List[SatelliteImage]
    titles: Optional[list] = None,
    figsize: Tuple[int, int] = (16, 6),
    **kwargs
):
    """
    Muestra múltiples imágenes lado a lado para comparación.

    Args:
        images: Lista de SatelliteImage a comparar
        titles: Títulos para cada imagen (opcional)
        figsize: Tamaño de la figura
        **kwargs: Argumentos adicionales pasados a _render_on_ax
    """
    n_images = len(images)
    fig, axes = plt.subplots(1, n_images, figsize=figsize)

    if n_images == 1:
        axes = [axes]

    for idx, (ax, img) in enumerate(zip(axes, images)):
        title = titles[idx] if titles and idx < len(titles) else None
        _render_on_ax(img, ax, title=title, **kwargs)

    plt.tight_layout()
    plt.show()


def normalize_ratio(
    ratio: np.ndarray,
    percentile_clip: float = 2.0
) -> np.ndarray:
    """
    Normaliza un ratio de bandas para mejor visualización.
    
    Los ratios suelen tener valores atípicos extremos, por lo que
    esta función usa normalización por percentiles robusta.
    
    Args:
        ratio: Array con valores de ratio
        percentile_clip: Percentil para recorte
    
    Returns:
        Array normalizado entre 0 y 1
    """
    # Convertir a float32 para ahorrar memoria (suficiente precisión)
    ratio = ratio.astype(np.float32)
    
    # Filtrar valores válidos (positivos y finitos)
    valid_mask = np.isfinite(ratio) & (ratio > 0)
    
    if not valid_mask.any():
        return ratio
    
    # Usar percentiles para robustez contra outliers
    p_low, p_high = np.percentile(ratio[valid_mask], [percentile_clip, 100 - percentile_clip])
    
    # Normalizar y clipear (in-place para ahorrar memoria)
    normalized = np.clip((ratio - p_low) / (p_high - p_low), 0, 1, dtype=np.float32)
    return normalized


def downsample_data(band_data: np.ndarray, factor: Optional[int]) -> np.ndarray:
    """
    Devuelve un subconjunto de la banda aplicando un factor de submuestreo.

    Args:
        band_data: Array 2-D con los datos de la banda
        factor: Factor de submuestreo (None o ≤1 = sin cambios)

    Returns:
        Array submuestreado (vista, no copia)
    """
    if factor and factor > 1:
        return band_data[::factor, ::factor]
    return band_data


def _render_on_ax(
    image,
    ax,
    natural_color: bool = True,
    bands: Optional[Tuple[str, str, str]] = None,
    cmap: Optional[str] = None,
    title: Optional[str] = None,
    percentile_clip: float = 2.0,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None
):
    """
    Renderiza una SatelliteImage en un Axes de matplotlib ya existente.
    Lógica central compartida por plot_image() y plot_comparison().
    """
    n_bands = len(image.bands)

    if n_bands == 1:
        band_name = list(image.bands.keys())[0]
        band_data = image.get_band(band_name)

        if band_name.upper() in ['NDVI', 'NDWI', 'EVI']:
            if vmin is None:
                vmin = -1
            if vmax is None:
                vmax = 1
            if cmap is None:
                cmap = 'RdYlGn'

        if vmin is not None and vmax is not None:
            display_data = band_data
        else:
            display_data = normalize_band(band_data, percentile_clip, vmin, vmax)

        img = ax.imshow(display_data, cmap=cmap or 'viridis', vmin=vmin, vmax=vmax)
        plt.colorbar(img, ax=ax, fraction=0.046, pad=0.04)

        if title is None:
            title = band_name

    elif n_bands >= 3:
        if bands is None:
            if natural_color:
                bands = get_default_rgb_bands(image.sensor_type)
            else:
                bands = tuple(list(image.bands.keys())[:3])

        try:
            red   = normalize_band(image.get_band(bands[0]), percentile_clip)
            green = normalize_band(image.get_band(bands[1]), percentile_clip)
            blue  = normalize_band(image.get_band(bands[2]), percentile_clip)
            ax.imshow(np.dstack([red, green, blue]))
        except KeyError as e:
            raise ValueError(f"Error al crear composición RGB: {e}")

        if title is None:
            title = f'Composición RGB ({bands[0]}-{bands[1]}-{bands[2]})'

    else:
        raise ValueError(f"No se puede visualizar imagen con {n_bands} banda(s)")

    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.axis('off')

    if 'crs' in image.metadata:
        info = f"Sensor: {image.sensor_type} | CRS: {image.metadata['crs']}"
        if 'date' in image.metadata:
            info += f" | Fecha: {image.metadata['date']}"
        ax.figure.text(0.5, 0.01, info, ha='center', fontsize=9, style='italic')


def plot_geological_ratios(
    image,  # SatelliteImage
    figsize: Tuple[int, int] = (10, 8),
    percentile_clip: float = 2.0,
    downsample: Optional[int] = None,
    save_dir: Optional[str] = None
):
    """
    Visualiza los tres ratios geológicos principales.
    
    Muestra:
    1. Iron Oxide Ratio (B4/B2) - Óxidos de hierro
    2. Clay Ratio (B6/B7) - Alteración arcillosa
    3. Ferrous Minerals Ratio (B6/B5) - Minerales ferrosos
    4. Geological Composite RGB
    
    Args:
        image: Instancia de SatelliteImage con las bandas necesarias
        figsize: Tamaño de la figura
        percentile_clip: Percentil para normalización
        downsample: Factor de submuestreo (ej: 2 = mitad de resolución)
        save_dir: Directorio para guardar figuras (None = no guardar)
    """
    from .indices import (
        calculate_iron_oxide_ratio,
        calculate_clay_ratio,
        calculate_ferrous_minerals_ratio,
        calculate_geological_composite
    )
    
    # Crear directorio si es necesario
    if save_dir:
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)
    
    # Calcular índices
    print("Calculando ratios geológicos...")
    
    # Auto-downsample para imágenes grandes (>5000 píxeles)
    height, width = image.shape()
    if downsample is None and max(height, width) > 5000:
        downsample = 2
        print(f"  (Aplicando downsample x{downsample} para visualización)")
    
    iron_oxide = calculate_iron_oxide_ratio(image)
    clay = calculate_clay_ratio(image)
    ferrous = calculate_ferrous_minerals_ratio(image)
    composite = calculate_geological_composite(image)

    # 1. Iron Oxide Ratio
    fig, ax = plt.subplots(figsize=figsize)
    ior_data = downsample_data(iron_oxide.get_band('Iron_Oxide_Ratio'), downsample)
    ior_norm = normalize_ratio(ior_data, percentile_clip)
    im1 = ax.imshow(ior_norm, cmap='YlOrRd')
    ax.set_title('Iron Oxide Ratio (B4/B2)\nÓxidos de Fe, Arenas Negras',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.colorbar(im1, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'ratios_01_iron_oxide.png', dpi=100, bbox_inches='tight')
    plt.close()
    del ior_data, ior_norm, fig, ax

    # 2. Clay Ratio
    fig, ax = plt.subplots(figsize=figsize)
    clay_data = downsample_data(clay.get_band('Clay_Ratio'), downsample)
    clay_norm = normalize_ratio(clay_data, percentile_clip)
    im2 = ax.imshow(clay_norm, cmap='RdPu')
    ax.set_title('Clay Ratio (B6/B7)\nAlteración Hidrotermal, Arcillas',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.colorbar(im2, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'ratios_02_clay.png', dpi=100, bbox_inches='tight')
    plt.close()
    del clay_data, clay_norm, fig, ax

    # 3. Ferrous Minerals Ratio
    fig, ax = plt.subplots(figsize=figsize)
    fmr_data = downsample_data(ferrous.get_band('Ferrous_Minerals_Ratio'), downsample)
    fmr_norm = normalize_ratio(fmr_data, percentile_clip)
    im3 = ax.imshow(fmr_norm, cmap='copper')
    ax.set_title('Ferrous Minerals Ratio (B6/B5)\nDiferenciación Litológica',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.colorbar(im3, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'ratios_03_ferrous.png', dpi=100, bbox_inches='tight')
    plt.close()
    del fmr_data, fmr_norm, fig, ax

    # 4. Geological Composite
    fig, ax = plt.subplots(figsize=figsize)
    r_data = downsample_data(composite.get_band('R'), downsample)
    g_data = downsample_data(composite.get_band('G'), downsample)
    b_data = downsample_data(composite.get_band('B'), downsample)

    r = normalize_ratio(r_data, percentile_clip)
    g = normalize_ratio(g_data, percentile_clip)
    b = normalize_ratio(b_data, percentile_clip)
    rgb = np.dstack([r, g, b])
    ax.imshow(rgb)
    ax.set_title('Composición Geológica RGB\nR:B6/B7  G:B6/B5  B:B4/B2',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'ratios_04_composite.png', dpi=100, bbox_inches='tight')
    plt.close()
    del r_data, g_data, b_data, r, g, b, rgb, fig, ax

    print("✓ Ratios geológicos calculados y guardados")


def plot_mineral_exploration_analysis(
    image,  # SatelliteImage
    figsize: Tuple[int, int] = (10, 8),
    downsample: Optional[int] = None,
    save_dir: Optional[str] = None
):
    """
    Panel completo de análisis para exploración mineral (placeres auríferos).
    
    Combina:
    - Color natural
    - Geological Composite
    - Iron Oxide Ratio
    - NDVI (para enmascarar vegetación)
    
    Args:
        image: Instancia de SatelliteImage
        figsize: Tamaño de la figura
        downsample: Factor de submuestreo (None = automático)
        save_dir: Directorio para guardar figuras
    """
    from .indices import (
        calculate_ndvi,
        calculate_iron_oxide_ratio,
        calculate_geological_composite
    )
    
    # Crear directorio si es necesario
    if save_dir:
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)
    
    # Auto-downsample para imágenes grandes
    height, width = image.shape()
    if downsample is None and max(height, width) > 5000:
        downsample = 2
        print(f"  (Aplicando downsample x{downsample} para visualización)")

    # 1. Color Natural (RGB)
    fig, ax = plt.subplots(figsize=figsize)
    r_data = downsample_data(image.get_band('B4'), downsample)
    g_data = downsample_data(image.get_band('B3'), downsample)
    b_data = downsample_data(image.get_band('B2'), downsample)

    r = normalize_band(r_data, 2.0)
    g = normalize_band(g_data, 2.0)
    b = normalize_band(b_data, 2.0)
    rgb = np.dstack([r, g, b])
    ax.imshow(rgb)
    ax.set_title('Color Natural (RGB: 4-3-2)', fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'analysis_01_natural.png', dpi=100, bbox_inches='tight')
    plt.close()
    del r_data, g_data, b_data, r, g, b, rgb, fig, ax

    # 2. Geological Composite
    fig, ax = plt.subplots(figsize=figsize)
    composite = calculate_geological_composite(image)
    r_data = downsample_data(composite.get_band('R'), downsample)
    g_data = downsample_data(composite.get_band('G'), downsample)
    b_data = downsample_data(composite.get_band('B'), downsample)

    r = normalize_ratio(r_data, 2.0)
    g = normalize_ratio(g_data, 2.0)
    b = normalize_ratio(b_data, 2.0)
    rgb_comp = np.dstack([r, g, b])
    ax.imshow(rgb_comp)
    ax.set_title('Composición Geológica\n(Anomalías Minerales)',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'analysis_02_composite.png', dpi=100, bbox_inches='tight')
    plt.close()
    del r_data, g_data, b_data, r, g, b, rgb_comp, composite, fig, ax

    # 3. Iron Oxide Ratio (alta prioridad para placeres)
    fig, ax = plt.subplots(figsize=figsize)
    iron_oxide = calculate_iron_oxide_ratio(image)
    ior_raw = downsample_data(iron_oxide.get_band('Iron_Oxide_Ratio'), downsample)
    ior_data = normalize_ratio(ior_raw, 2.0)
    im3 = ax.imshow(ior_data, cmap='YlOrRd')
    ax.set_title('Iron Oxide Ratio\n(Arenas Negras - Placeres)',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.colorbar(im3, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'analysis_03_iron_oxide.png', dpi=100, bbox_inches='tight')
    plt.close()
    del iron_oxide, ior_raw, ior_data, fig, ax

    # 4. NDVI (para discriminar vegetación)
    fig, ax = plt.subplots(figsize=figsize)
    ndvi = calculate_ndvi(image)
    ndvi_data = downsample_data(ndvi.get_band('NDVI'), downsample)
    im4 = ax.imshow(ndvi_data, cmap='RdYlGn', vmin=-1, vmax=1)
    ax.set_title('NDVI\n(Vegetación vs Suelo Desnudo)',
                 fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.colorbar(im4, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    if save_dir:
        plt.savefig(Path(save_dir) / 'analysis_04_ndvi.png', dpi=100, bbox_inches='tight')
    plt.close()
    del ndvi, ndvi_data, fig, ax
    
    print("✓ Análisis mineral calculado y guardado")

