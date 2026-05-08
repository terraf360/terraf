"""
Utilidades auxiliares para spectraf.
"""
from pathlib import Path
from typing import Optional


def get_default_data_path() -> Path:
    """Obtiene la ruta por defecto a los datos de satélite."""
    # Ruta: spectraf/src/ → spectraf/ → terraf/ → datos/
    return Path(__file__).parent.parent.parent / 'datos'


def find_landsat9_scene(scene_id: str, data_path: Optional[Path] = None) -> Optional[Path]:
    """
    Busca una escena de Landsat 9 en el directorio de datos.
    
    Args:
        scene_id: ID de la escena (ej: 'LC09_L2SP_024048_20260110_20260111_02_T1')
        data_path: Ruta base de datos (opcional)
    
    Returns:
        Path completo a la escena o None si no se encuentra
    """
    if data_path is None:
        data_path = get_default_data_path()
    
    landsat_path = data_path / 'landsat9'
    
    # Buscar la escena exacta
    scene_path = landsat_path / scene_id
    if scene_path.exists():
        return scene_path
    
    # Buscar por patrón si no se encuentra exacta
    if landsat_path.exists():
        for item in landsat_path.iterdir():
            if item.is_dir() and scene_id in item.name:
                return item
    
    return None


def find_sentinel2_scene(scene_id: str, data_path: Optional[Path] = None) -> Optional[Path]:
    """
    Busca una escena de Sentinel-2 en el directorio de datos.
    
    Args:
        scene_id: ID de la escena
        data_path: Ruta base de datos (opcional)
    
    Returns:
        Path completo a la escena o None si no se encuentra
    """
    if data_path is None:
        data_path = get_default_data_path()
    
    sentinel_path = data_path / 'sentinel-2'
    
    if not sentinel_path.exists():
        return None
    
    # Buscar la escena
    for item in sentinel_path.iterdir():
        if item.is_dir() and scene_id in item.name:
            return item
    
    return None
