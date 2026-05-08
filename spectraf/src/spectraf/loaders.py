"""
Cargadores de imágenes de satélite desde diferentes sensores.
"""
from pathlib import Path
from typing import Optional, List
import numpy as np
import rasterio

from .core import SatelliteImage
from .utils import find_landsat9_scene, find_sentinel2_scene


def load_landsat9_image(
    scene_id: str,
    data_path: Optional[Path] = None,
    bands: Optional[List[str]] = None
) -> SatelliteImage:
    """
    Carga una escena de Landsat 9 (Level 2 Surface Reflectance).
    
    Args:
        scene_id: ID de la escena (ej: 'LC09_L2SP_024048_20260110_20260111_02_T1')
        data_path: Ruta base de datos (opcional, usa 'datos/' por defecto)
        bands: Lista de bandas a cargar (opcional, carga todas por defecto)
    
    Returns:
        SatelliteImage con las bandas cargadas
    
    Raises:
        FileNotFoundError: Si no se encuentra la escena
        ValueError: Si no se encuentran archivos de bandas
    
    Example:
        >>> image = load_landsat9_image('LC09_L2SP_024048_20260110_20260111_02_T1')
        >>> print(image.list_bands())
        ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7']
    """
    # Buscar la escena
    scene_path = find_landsat9_scene(scene_id, data_path)
    
    if scene_path is None:
        raise FileNotFoundError(
            f"No se encontró la escena '{scene_id}' en el directorio de datos. "
            f"Verifica que existe en datos/landsat9/"
        )
    
    # Definir bandas a cargar (Surface Reflectance)
    if bands is None:
        bands = ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7']
    
    # Cargar bandas
    loaded_bands = {}
    metadata = {}
    
    for band_name in bands:
        # Buscar archivo de banda
        band_file = scene_path / f"{scene_path.name}_SR_{band_name}.TIF"
        
        if not band_file.exists():
            # Intentar sin SR_ para bandas térmicas
            band_file = scene_path / f"{scene_path.name}_ST_{band_name}.TIF"
        
        if band_file.exists():
            with rasterio.open(band_file) as src:
                # Leer banda y convertir a float
                band_data = src.read(1).astype(float)
                loaded_bands[band_name] = band_data
                
                # Guardar metadatos de la primera banda
                if not metadata:
                    metadata = {
                        'crs': str(src.crs),
                        'transform': src.transform,
                        'bounds': src.bounds,
                        'resolution': src.res,
                        'width': src.width,
                        'height': src.height,
                        'nodata': src.nodata
                    }
    
    if not loaded_bands:
        raise ValueError(
            f"No se pudieron cargar bandas de la escena '{scene_id}'. "
            f"Verifica que existen archivos *_SR_B*.TIF en {scene_path}"
        )
    
    # Extraer fecha de adquisición del nombre de escena
    # Formato: LC09_L2SP_024048_20260110_...
    try:
        parts = scene_id.split('_')
        date_str = parts[3]  # '20260110'
        metadata['date'] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        metadata['path_row'] = parts[2]  # '024048'
    except (IndexError, ValueError):
        pass
    
    metadata['scene_id'] = scene_id
    metadata['scene_path'] = str(scene_path)
    
    return SatelliteImage(
        bands=loaded_bands,
        metadata=metadata,
        sensor_type='landsat9'
    )


def load_sentinel2_image(
    scene_id: str,
    data_path: Optional[Path] = None,
    bands: Optional[List[str]] = None,
    resolution: str = '10m'
) -> SatelliteImage:
    """
    Carga una escena de Sentinel-2.
    
    Args:
        scene_id: ID de la escena
        data_path: Ruta base de datos (opcional)
        bands: Lista de bandas a cargar (opcional)
        resolution: Resolución espacial ('10m', '20m', '60m')
    
    Returns:
        SatelliteImage con las bandas cargadas
    
    Raises:
        NotImplementedError: Función no implementada aún
    
    Example:
        >>> image = load_sentinel2_image('S2A_MSIL2A_20230615...')
    """
    raise NotImplementedError(
        "El cargador de Sentinel-2 aún no está implementado. "
        "Por ahora solo está disponible load_landsat9_image()."
    )


def load_image(
    scene_id: str,
    sensor_type: Optional[str] = None,
    **kwargs
) -> SatelliteImage:
    """
    Cargador genérico que detecta automáticamente el tipo de sensor.
    
    Args:
        scene_id: ID de la escena
        sensor_type: Tipo de sensor (opcional, se detecta automáticamente)
        **kwargs: Argumentos adicionales para el cargador específico
    
    Returns:
        SatelliteImage
    
    Example:
        >>> image = load_image('LC09_L2SP_024048_20260110_20260111_02_T1')
    """
    # Detectar tipo de sensor del ID
    if sensor_type is None:
        if scene_id.startswith('LC09') or scene_id.startswith('LC08'):
            sensor_type = 'landsat9'
        elif scene_id.startswith('S2'):
            sensor_type = 'sentinel2'
        else:
            raise ValueError(
                f"No se pudo detectar el tipo de sensor de '{scene_id}'. "
                f"Especifica sensor_type='landsat9' o 'sentinel2'"
            )
    
    # Cargar según tipo
    if sensor_type == 'landsat9':
        return load_landsat9_image(scene_id, **kwargs)
    elif sensor_type == 'sentinel2':
        return load_sentinel2_image(scene_id, **kwargs)
    else:
        raise ValueError(f"Tipo de sensor no soportado: '{sensor_type}'")
