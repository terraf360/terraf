"""
Cálculo de índices espectrales para análisis de imágenes de satélite.
"""
import numpy as np
from typing import Dict, Tuple

from .core import SatelliteImage


# ---------------------------------------------------------------------------
# Configuración centralizada de bandas por sensor
# Clave: (sensor_type, rol_de_banda) → nombre de banda
# ---------------------------------------------------------------------------
_SENSOR_BANDS: Dict[str, Dict[str, str]] = {
    'landsat9': {
        'blue':  'B2',
        'green': 'B3',
        'red':   'B4',
        'nir':   'B5',
        'swir1': 'B6',
        'swir2': 'B7',
    },
    'sentinel2': {
        'blue':  'B2',
        'green': 'B3',
        'red':   'B4',
        'nir':   'B8',
        'swir1': 'B11',
        'swir2': 'B12',
    },
}
# Sensor desconocido → asumir nomenclatura Landsat
_DEFAULT_SENSOR = 'landsat9'


def _get_band(image: SatelliteImage, role: str) -> Tuple[np.ndarray, str]:
    """
    Obtiene una banda de la imagen según su rol semántico (ej: 'nir', 'red').

    Args:
        image: Imagen de satélite
        role: Rol de banda ('blue', 'green', 'red', 'nir', 'swir1', 'swir2')

    Returns:
        Tuple (array, nombre_de_banda)

    Raises:
        KeyError: Si la banda no existe en la imagen
    """
    sensor = image.sensor_type if image.sensor_type in _SENSOR_BANDS else _DEFAULT_SENSOR
    band_name = _SENSOR_BANDS[sensor][role]
    return image.get_band(band_name), band_name


def _calculate_normalized_difference(
    band1: np.ndarray,
    band2: np.ndarray
) -> np.ndarray:
    """
    Calcula un índice de diferencia normalizada: (band1 - band2) / (band1 + band2).

    Los píxeles donde el denominador es 0 o no finito se devuelven como NaN.

    Args:
        band1: Primera banda (numerador positivo)
        band2: Segunda banda (numerador negativo)

    Returns:
        Array float64 con el índice calculado
    """
    denominator = band1 + band2
    valid = np.isfinite(denominator) & (denominator != 0)
    result = np.where(valid, (band1 - band2) / np.where(valid, denominator, 1), np.nan)
    return result


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """
    Calcula un ratio band/band evitando división por cero y valores no finitos.

    Devuelve NaN donde el denominador es 0 o no finito.
    """
    valid = np.isfinite(denominator) & (denominator != 0)
    return np.where(valid, numerator / np.where(valid, denominator, 1), np.nan)


def calculate_ndvi(image: SatelliteImage) -> SatelliteImage:
    """
    Calcula el Índice de Vegetación de Diferencia Normalizada (NDVI).

    NDVI = (NIR - Red) / (NIR + Red)

    Valores:
        - NDVI < 0: Agua, nubes, nieve
        - NDVI ≈ 0-0.2: Suelo desnudo, roca
        - NDVI > 0.2-0.4: Vegetación dispersa
        - NDVI > 0.4: Vegetación densa

    Args:
        image: Imagen de satélite con bandas NIR y Red

    Returns:
        SatelliteImage con una banda 'NDVI'

    Raises:
        KeyError: Si no se encuentran las bandas necesarias

    Example:
        >>> ndvi = calculate_ndvi(image)
        >>> ndvi.show()
    """
    try:
        nir, nir_band = _get_band(image, 'nir')
        red, red_band = _get_band(image, 'red')
    except KeyError as e:
        raise KeyError(f"No se puede calcular NDVI: {e}. Se requieren bandas NIR y Red.")

    ndvi = _calculate_normalized_difference(nir, red)

    metadata = image.metadata.copy()
    metadata['index'] = 'NDVI'
    metadata['formula'] = f'({nir_band} - {red_band}) / ({nir_band} + {red_band})'

    return SatelliteImage(bands={'NDVI': ndvi}, metadata=metadata, sensor_type=image.sensor_type)


def calculate_ndwi(image: SatelliteImage) -> SatelliteImage:
    """
    Calcula el Índice de Agua de Diferencia Normalizada (NDWI).

    NDWI = (Green - NIR) / (Green + NIR)

    Valores:
        - NDWI > 0: Cuerpos de agua
        - NDWI ≈ 0: Transición
        - NDWI < 0: No agua

    Args:
        image: Imagen de satélite con bandas Green y NIR

    Returns:
        SatelliteImage con una banda 'NDWI'

    Example:
        >>> ndwi = calculate_ndwi(image)
        >>> ndwi.show(cmap='Blues')
    """
    try:
        green, green_band = _get_band(image, 'green')
        nir, nir_band   = _get_band(image, 'nir')
    except KeyError as e:
        raise KeyError(f"No se puede calcular NDWI: {e}. Se requieren bandas Green y NIR.")

    ndwi = _calculate_normalized_difference(green, nir)

    metadata = image.metadata.copy()
    metadata['index'] = 'NDWI'
    metadata['formula'] = f'({green_band} - {nir_band}) / ({green_band} + {nir_band})'

    return SatelliteImage(bands={'NDWI': ndwi}, metadata=metadata, sensor_type=image.sensor_type)


def calculate_evi(image: SatelliteImage, G: float = 2.5, C1: float = 6.0,
                  C2: float = 7.5, L: float = 1.0) -> SatelliteImage:
    """
    Calcula el Índice de Vegetación Mejorado (EVI).

    EVI = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L)

    El EVI es menos sensible a la saturación en áreas de vegetación densa
    y corrige mejor las influencias atmosféricas.

    Args:
        image: Imagen de satélite con bandas NIR, Red y Blue
        G: Factor de ganancia (default: 2.5)
        C1: Coeficiente de corrección aerosol rojo (default: 6.0)
        C2: Coeficiente de corrección aerosol azul (default: 7.5)
        L: Factor de ajuste de fondo (default: 1.0)

    Returns:
        SatelliteImage con una banda 'EVI'

    Example:
        >>> evi = calculate_evi(image)
        >>> evi.show()
    """
    try:
        nir,  nir_band  = _get_band(image, 'nir')
        red,  red_band  = _get_band(image, 'red')
        blue, blue_band = _get_band(image, 'blue')
    except KeyError as e:
        raise KeyError(f"No se puede calcular EVI: {e}. Se requieren bandas NIR, Red y Blue.")

    denominator = nir + C1 * red - C2 * blue + L
    evi = _safe_ratio(G * (nir - red), denominator)

    metadata = image.metadata.copy()
    metadata['index'] = 'EVI'
    metadata['formula'] = (
        f'{G} * ({nir_band} - {red_band}) / '
        f'({nir_band} + {C1}*{red_band} - {C2}*{blue_band} + {L})'
    )

    return SatelliteImage(bands={'EVI': evi}, metadata=metadata, sensor_type=image.sensor_type)


def calculate_savi(image: SatelliteImage, L: float = 0.5) -> SatelliteImage:
    """
    Calcula el Índice de Vegetación Ajustado al Suelo (SAVI).

    SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)

    Útil en áreas con baja cobertura vegetal donde el suelo es visible.

    Args:
        image: Imagen de satélite con bandas NIR y Red
        L: Factor de ajuste de suelo (0=vegetación densa, 1=suelo desnudo, default=0.5)

    Returns:
        SatelliteImage con una banda 'SAVI'

    Example:
        >>> savi = calculate_savi(image, L=0.5)
        >>> savi.show()
    """
    try:
        nir, nir_band = _get_band(image, 'nir')
        red, red_band = _get_band(image, 'red')
    except KeyError as e:
        raise KeyError(f"No se puede calcular SAVI: {e}. Se requieren bandas NIR y Red.")

    denominator = nir + red + L
    savi = _safe_ratio((nir - red) * (1 + L), denominator)

    metadata = image.metadata.copy()
    metadata['index'] = 'SAVI'
    metadata['formula'] = f'(({nir_band} - {red_band}) / ({nir_band} + {red_band} + {L})) * (1 + {L})'

    return SatelliteImage(bands={'SAVI': savi}, metadata=metadata, sensor_type=image.sensor_type)


# ============================================================================
# ÍNDICES GEOLÓGICOS Y MINERALÓGICOS
# Útiles para exploración mineral, detección de alteraciones y placeres
# ============================================================================

def calculate_iron_oxide_ratio(image: SatelliteImage) -> SatelliteImage:
    """
    Calcula el Índice de Óxidos de Hierro (Iron Oxide Ratio).

    Iron Oxide Ratio = Red / Blue

    Resalta zonas con alta concentración de hierro oxidado (hematita,
    magnetita, limonita). Útil para:
    - Detectar "arenas negras" en placeres auríferos
    - Identificar zonas de alteración hidrotermal
    - Mapear óxidos de hierro en sedimentos aluviales

    Args:
        image: Imagen de satélite con bandas Red y Blue

    Returns:
        SatelliteImage con una banda 'Iron_Oxide_Ratio'

    Example:
        >>> ior = calculate_iron_oxide_ratio(image)
        >>> ior.show(cmap='YlOrRd')
    """
    try:
        red,  red_band  = _get_band(image, 'red')
        blue, blue_band = _get_band(image, 'blue')
    except KeyError as e:
        raise KeyError(f"No se puede calcular Iron Oxide Ratio: {e}. Se requieren bandas Red y Blue.")

    iron_oxide_ratio = _safe_ratio(red, blue)

    metadata = image.metadata.copy()
    metadata['index'] = 'Iron_Oxide_Ratio'
    metadata['formula'] = f'{red_band} / {blue_band}'
    metadata['application'] = 'Detección de óxidos de hierro, arenas negras, alteración'

    return SatelliteImage(
        bands={'Iron_Oxide_Ratio': iron_oxide_ratio},
        metadata=metadata,
        sensor_type=image.sensor_type
    )


def calculate_clay_ratio(image: SatelliteImage) -> SatelliteImage:
    """
    Calcula el Índice de Arcillas/Hidroxilos (Clay/Hydroxyl Ratio).

    Clay Ratio = SWIR1 / SWIR2

    Resalta zonas con minerales arcillosos y grupos hidroxilo (OH):
    - Alteración hidrotermal (sericita, caolinita, alunita)
    - Acumulaciones de arcillas en llanuras de inundación
    - Identificación de zonas de alteración en roca madre río arriba

    Args:
        image: Imagen de satélite con bandas SWIR1 y SWIR2

    Returns:
        SatelliteImage con una banda 'Clay_Ratio'

    Example:
        >>> clay = calculate_clay_ratio(image)
        >>> clay.show(cmap='RdPu')
    """
    try:
        swir1, swir1_band = _get_band(image, 'swir1')
        swir2, swir2_band = _get_band(image, 'swir2')
    except KeyError as e:
        raise KeyError(f"No se puede calcular Clay Ratio: {e}. Se requieren bandas SWIR1 y SWIR2.")

    clay_ratio = _safe_ratio(swir1, swir2)

    metadata = image.metadata.copy()
    metadata['index'] = 'Clay_Ratio'
    metadata['formula'] = f'{swir1_band} / {swir2_band}'
    metadata['application'] = 'Detección de alteración arcillosa e hidrotermal'

    return SatelliteImage(
        bands={'Clay_Ratio': clay_ratio},
        metadata=metadata,
        sensor_type=image.sensor_type
    )


def calculate_ferrous_minerals_ratio(image: SatelliteImage) -> SatelliteImage:
    """
    Calcula el Índice de Minerales Ferrosos (Ferrous Minerals Ratio).

    Ferrous Minerals Ratio = SWIR1 / NIR

    Ayuda a diferenciar materiales litológicos en el cauce:
    - Minerales ferrosos (silicatos con Fe2+)
    - Discriminación litológica en cauces y sedimentos
    - Identificación de cambios en composición del sustrato

    Args:
        image: Imagen de satélite con bandas SWIR1 y NIR

    Returns:
        SatelliteImage con una banda 'Ferrous_Minerals_Ratio'

    Example:
        >>> fmr = calculate_ferrous_minerals_ratio(image)
        >>> fmr.show(cmap='copper')
    """
    try:
        swir1, swir1_band = _get_band(image, 'swir1')
        nir,   nir_band   = _get_band(image, 'nir')
    except KeyError as e:
        raise KeyError(f"No se puede calcular Ferrous Minerals Ratio: {e}. Se requieren bandas SWIR1 y NIR.")

    ferrous_ratio = _safe_ratio(swir1, nir)

    metadata = image.metadata.copy()
    metadata['index'] = 'Ferrous_Minerals_Ratio'
    metadata['formula'] = f'{swir1_band} / {nir_band}'
    metadata['application'] = 'Diferenciación litológica, minerales ferrosos'

    return SatelliteImage(
        bands={'Ferrous_Minerals_Ratio': ferrous_ratio},
        metadata=metadata,
        sensor_type=image.sensor_type
    )


def calculate_geological_composite(image: SatelliteImage) -> SatelliteImage:
    """
    Crea una composición RGB de ratios geológicos para exploración mineral.
    
    Composición RGB:
    - R: Band6/Band7 (Clay Ratio - Alteración arcillosa)
    - G: Band6/Band5 (Ferrous Minerals - Litología)
    - B: Band4/Band2 (Iron Oxide - Óxidos de hierro)
    
    Esta composición resalta anomalías minerales respecto a la vegetación
    y es especialmente útil para exploración de placeres auríferos.
    
    Args:
        image: Imagen de satélite con las bandas necesarias
    
    Returns:
        SatelliteImage con tres bandas de ratios (R, G, B)
    
    Example:
        >>> composite = calculate_geological_composite(image)
        >>> composite.show(natural_color=False, bands=('R', 'G', 'B'))
    """
    # Calcular cada ratio individualmente
    clay = calculate_clay_ratio(image)
    ferrous = calculate_ferrous_minerals_ratio(image)
    iron_oxide = calculate_iron_oxide_ratio(image)
    
    # Crear una nueva imagen con las tres bandas como RGB
    metadata = image.metadata.copy()
    metadata['index'] = 'Geological_Composite'
    metadata['formula'] = 'RGB: B6/B7, B6/B5, B4/B2'
    metadata['application'] = 'Exploración mineral, detección de anomalías geológicas'
    
    return SatelliteImage(
        bands={
            'R': clay.get_band('Clay_Ratio'),
            'G': ferrous.get_band('Ferrous_Minerals_Ratio'),
            'B': iron_oxide.get_band('Iron_Oxide_Ratio')
        },
        metadata=metadata,
        sensor_type=image.sensor_type
    )
