"""
spectraf - Módulo de terraf para procesamiento de imágenes de satélite.

spectraf proporciona herramientas para cargar, visualizar y analizar imágenes
de satélite de diferentes sensores (Landsat 9, Sentinel-2, etc.), así como
calcular índices espectrales comunes para análisis de vegetación, agua y más.

Ejemplo de uso básico:
    >>> import spectraf
    >>> 
    >>> # Cargar una imagen de satélite
    >>> image = spectraf.load_landsat9_image('LC09_L2SP_024048_20260110_20260111_02_T1')
    >>> 
    >>> # Visualizar en color natural
    >>> image.show(natural_color=True)
    >>> 
    >>> # Calcular índice de vegetación
    >>> ndvi = spectraf.calculate_ndvi(image)
    >>> ndvi.show()

Componentes principales:
    - SatelliteImage: Clase contenedora para imágenes multiespectrales
    - Loaders: Funciones para cargar imágenes de diferentes sensores
    - Índices: Funciones para calcular índices espectrales (NDVI, NDWI, EVI, etc.)
    - Visualización: Herramientas para visualizar imágenes e índices
"""

__version__ = '0.1.0'
__author__ = 'terraf'

# Importar clase principal
from .core import SatelliteImage

# Importar cargadores
from .loaders import (
    load_landsat9_image,
    load_sentinel2_image,
    load_image
)

# Importar funciones de índices espectrales
from .indices import (
    calculate_ndvi,
    calculate_ndwi,
    calculate_evi,
    calculate_savi,
    # Índices geológicos
    calculate_iron_oxide_ratio,
    calculate_clay_ratio,
    calculate_ferrous_minerals_ratio,
    calculate_geological_composite
)

# Importar utilidades de visualización
from .visualization import (
    plot_image,
    plot_comparison,
    normalize_band,
    normalize_ratio,
    downsample_data,
    plot_geological_ratios,
    plot_mineral_exploration_analysis
)

# Importar módulo de geología (SGM)
from .geology import (
    load_sgm_litologia,
    load_sgm_geoquimica,
    load_sgm_inventarios_mineros,
    get_lithology_summary,
    filter_lithology_favorable,
    plot_lithology_map,
    overlay_satellite_and_lithology
)

# Importar módulo de análisis de targets
from .target_analysis import (
    identify_anomaly_zones,
    create_target_geodataframe,
    plot_targets_on_anomaly_map,
    export_targets_to_shapefile,
    generate_target_report
)

# Definir API pública
__all__ = [
    # Version
    '__version__',
    
    # Core
    'SatelliteImage',
    
    # Loaders
    'load_landsat9_image',
    'load_sentinel2_image',
    'load_image',
    
    # Indices
    'calculate_ndvi',
    'calculate_ndwi',
    'calculate_evi',
    'calculate_savi',
    'calculate_iron_oxide_ratio',
    'calculate_clay_ratio',
    'calculate_ferrous_minerals_ratio',
    'calculate_geological_composite',
    
    # Visualization
    'plot_image',
    'plot_comparison',
    'normalize_band',
    'normalize_ratio',
    'downsample_data',
    'plot_geological_ratios',
    'plot_mineral_exploration_analysis',
    
    # Geology (SGM)
    'load_sgm_litologia',
    'load_sgm_geoquimica',
    'load_sgm_inventarios_mineros',
    'get_lithology_summary',
    'filter_lithology_favorable',
    'plot_lithology_map',
    'overlay_satellite_and_lithology',
    
    # Target Analysis
    'identify_anomaly_zones',
    'create_target_geodataframe',
    'plot_targets_on_anomaly_map',
    'export_targets_to_shapefile',
    'generate_target_report',
]


# Información para help()
def info():
    """Muestra información sobre el módulo spectraf."""
    print(f"""
spectraf v{__version__}
=======================

Módulo de terraf para procesamiento de imágenes de satélite.

Sensores soportados:
  - Landsat 9 (Level 2 Surface Reflectance)
  - Sentinel-2 (próximamente)

Índices espectrales disponibles:
  - NDVI (Normalized Difference Vegetation Index)
  - NDWI (Normalized Difference Water Index)
  - EVI (Enhanced Vegetation Index)
  - SAVI (Soil Adjusted Vegetation Index)

Índices geológicos:
  - Iron Oxide Ratio (B4/B2) - Detección de óxidos de hierro
  - Clay Ratio (B6/B7) - Alteración arcillosa e hidrotermal
  - Ferrous Minerals Ratio (B6/B5) - Diferenciación litológica
  - Geological Composite (RGB: B6/B7, B6/B5, B4/B2) - Exploración mineral

Uso rápido:
  >>> import spectraf
  >>> image = spectraf.load_landsat9_image('SCENE_ID')
  >>> image.show(natural_color=True)
  >>> ndvi = spectraf.calculate_ndvi(image)
  >>> ndvi.show()

Para más información:
  >>> help(spectraf.SatelliteImage)
  >>> help(spectraf.load_landsat9_image)
  >>> help(spectraf.calculate_ndvi)
    """)
