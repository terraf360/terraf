"""
Módulo para integración de datos geológicos del SGM (Servicio Geológico Mexicano).

Proporciona funciones para cargar, visualizar y analizar datos de:
- Litología
- Geocronología
- Geoquímica
- Campo magnético
"""
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import numpy as np

from .utils import get_default_data_path

try:
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False


def load_sgm_litologia(
    carta_id: str = 'A18022026162831O',
    data_path: Optional[Path] = None
) -> 'gpd.GeoDataFrame':
    """
    Carga el shapefile de litología del SGM.
    
    Args:
        carta_id: ID de la carta geológica (default: A18022026162831O)
        data_path: Ruta base de datos (opcional)
    
    Returns:
        GeoDataFrame con la litología
    
    Raises:
        ImportError: Si geopandas no está instalado
        FileNotFoundError: Si no se encuentra el shapefile
    
    Example:
        >>> litologia = load_sgm_litologia()
        >>> print(litologia.columns)
        >>> print(litologia['CVE_LITOLO'].unique())
    """
    if not GEOPANDAS_AVAILABLE:
        raise ImportError(
            "geopandas es requerido para cargar datos del SGM. "
            "Instala con: pip install geopandas"
        )

    # Determinar ruta
    if data_path is None:
        data_path = get_default_data_path()
    
    # Ruta al shapefile de litología
    shp_path = data_path / 'SGM' / 'Carta' / carta_id / 'Litologia_G13_5.shp'
    
    if not shp_path.exists():
        raise FileNotFoundError(
            f"No se encontró el shapefile de litología en: {shp_path}\n"
            f"Verifica que existe datos/SGM/Carta/{carta_id}/Litologia_G13_5.shp"
        )
    
    # Cargar con geopandas
    gdf = gpd.read_file(shp_path)
    
    print(f"✓ Litología cargada: {len(gdf)} polígonos")
    print(f"  CRS: {gdf.crs}")
    print(f"  Columnas: {list(gdf.columns)}")
    
    return gdf


def load_sgm_geoquimica(
    carta_id: str = 'A18022026162831O',
    data_path: Optional[Path] = None
) -> 'gpd.GeoDataFrame':
    """
    Carga el shapefile de geoquímica del SGM.
    
    Args:
        carta_id: ID de la carta geológica
        data_path: Ruta base de datos (opcional)
    
    Returns:
        GeoDataFrame con datos geoquímicos
    
    Example:
        >>> geoquimica = load_sgm_geoquimica()
    """
    if not GEOPANDAS_AVAILABLE:
        raise ImportError("geopandas es requerido. Instala con: pip install geopandas")

    if data_path is None:
        data_path = get_default_data_path()

    shp_path = data_path / 'SGM' / 'Carta' / carta_id / 'Geoquimica_G13_5.shp'
    
    if not shp_path.exists():
        raise FileNotFoundError(f"No se encontró {shp_path}")
    
    gdf = gpd.read_file(shp_path)
    print(f"✓ Geoquímica cargada: {len(gdf)} puntos")
    
    return gdf


def load_sgm_inventarios_mineros(
    carta_id: str = 'A18022026162831O',
    data_path: Optional[Path] = None
) -> 'gpd.GeoDataFrame':
    """
    Carga el shapefile de Inventarios Mineros del SGM.
    
    Este shapefile contiene ubicaciones de manifestaciones minerales,
    minas abandonadas, y otros sitios de interés minero reportados.
    Muy útil para validar zonas con potencial conocido.
    
    Args:
        carta_id: ID de la carta geológica
        data_path: Ruta base de datos (opcional)
    
    Returns:
        GeoDataFrame con inventarios mineros
    
    Example:
        >>> inventarios = load_sgm_inventarios_mineros()
        >>> print(inventarios['SUSTANCIA'].value_counts())
    """
    if not GEOPANDAS_AVAILABLE:
        raise ImportError("geopandas es requerido. Instala con: pip install geopandas")

    if data_path is None:
        data_path = get_default_data_path()

    shp_path = data_path / 'SGM' / 'Carta' / carta_id / 'InventariosMineros_G13_5.shp'
    
    if not shp_path.exists():
        raise FileNotFoundError(f"No se encontró {shp_path}")
    
    gdf = gpd.read_file(shp_path)
    print(f"✓ Inventarios Mineros cargados: {len(gdf)} sitios")
    
    return gdf


def get_lithology_summary(litologia_gdf: 'gpd.GeoDataFrame') -> Dict:
    """
    Genera un resumen de las unidades litológicas presentes.
    
    Args:
        litologia_gdf: GeoDataFrame de litología del SGM
    
    Returns:
        Diccionario con estadísticas de litología
    """
    summary = {
        'total_polygons': len(litologia_gdf),
        'unique_units': {},
        'area_by_unit': {}
    }
    
    # Identificar columna de litología (puede variar)
    litho_col = None
    for col in ['CVE_LITOLO', 'LITOLOGIA', 'CLAVE', 'NOMBRE']:
        if col in litologia_gdf.columns:
            litho_col = col
            break
    
    if litho_col:
        # Contar unidades
        unit_counts = litologia_gdf[litho_col].value_counts()
        summary['unique_units'] = unit_counts.to_dict()
        
        # Calcular áreas si está proyectado
        if litologia_gdf.crs and litologia_gdf.crs.is_projected:
            litologia_gdf['area_km2'] = litologia_gdf.geometry.area / 1e6
            area_by_unit = litologia_gdf.groupby(litho_col)['area_km2'].sum()
            summary['area_by_unit'] = area_by_unit.to_dict()
    
    return summary


def filter_lithology_favorable(
    litologia_gdf: 'gpd.GeoDataFrame',
    favorable_units: Optional[List[str]] = None
) -> 'gpd.GeoDataFrame':
    """
    Filtra unidades litológicas favorables para mineralización.
    
    Args:
        litologia_gdf: GeoDataFrame de litología
        favorable_units: Lista de códigos de unidades favorables (opcional)
    
    Returns:
        GeoDataFrame filtrado
    
    Example:
        >>> # Filtrar solo rocas ígneas y metamórficas
        >>> favorable = filter_lithology_favorable(litologia, ['Ig', 'Met', 'Qz'])
    """
    if favorable_units is None:
        # Criterios por defecto para placeres auríferos
        favorable_units = [
            'Ig',   # Ígneas (fuente de oro)
            'Met',  # Metamórficas
            'Qz',   # Vetas de cuarzo
            'Gr',   # Graníticas
            'Di',   # Dioritas
            'And',  # Andesitas
        ]
    
    # Identificar columna de litología
    litho_col = None
    for col in ['CVE_LITOLO', 'LITOLOGIA', 'CLAVE']:
        if col in litologia_gdf.columns:
            litho_col = col
            break
    
    if litho_col is None:
        print("⚠ No se pudo identificar columna de litología")
        return litologia_gdf
    
    # Filtrar (búsqueda por substring)
    mask = litologia_gdf[litho_col].apply(
        lambda x: any(unit in str(x) for unit in favorable_units) if x else False
    )
    
    filtered = litologia_gdf[mask].copy()
    
    print(f"✓ Filtrado: {len(filtered)} de {len(litologia_gdf)} polígonos son favorables")
    
    return filtered


def plot_lithology_map(
    litologia_gdf: 'gpd.GeoDataFrame',
    figsize: Tuple[int, int] = (12, 10),
    column: Optional[str] = None,
    title: str = "Mapa Litológico - SGM"
):
    """
    Visualiza el mapa de litología.
    
    Args:
        litologia_gdf: GeoDataFrame de litología
        figsize: Tamaño de la figura
        column: Columna a usar para colorear (opcional, detecta automáticamente)
        title: Título del mapa
    """
    if column is None:
        # Detectar columna de litología
        for col in ['CVE_LITOLO', 'LITOLOGIA', 'CLAVE']:
            if col in litologia_gdf.columns:
                column = col
                break
    
    fig, ax = plt.subplots(figsize=figsize)
    
    if column and column in litologia_gdf.columns:
        litologia_gdf.plot(
            column=column,
            ax=ax,
            legend=True,
            cmap='tab20',
            edgecolor='black',
            linewidth=0.5,
            alpha=0.7
        )
    else:
        litologia_gdf.plot(
            ax=ax,
            edgecolor='black',
            facecolor='skyblue',
            linewidth=0.5,
            alpha=0.7
        )
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel('Longitud')
    ax.set_ylabel('Latitud')
    
    plt.tight_layout()
    plt.show()


def overlay_satellite_and_lithology(
    satellite_image,  # SatelliteImage
    litologia_gdf: 'gpd.GeoDataFrame',
    figsize: Tuple[int, int] = (15, 12),
    alpha_litho: float = 0.4
):
    """
    Superpone la litología sobre una imagen de satélite.
    
    Args:
        satellite_image: Instancia de SatelliteImage
        litologia_gdf: GeoDataFrame de litología
        figsize: Tamaño de la figura
        alpha_litho: Transparencia de la litología
    
    Example:
        >>> image = spectraf.load_landsat9_image('scene_id')
        >>> litologia = spectraf.load_sgm_litologia()
        >>> overlay_satellite_and_lithology(image, litologia)
    """
    from .visualization import normalize_band
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Mostrar imagen de satélite como base
    r = normalize_band(satellite_image.get_band('B4'), 2.0)
    g = normalize_band(satellite_image.get_band('B3'), 2.0)
    b = normalize_band(satellite_image.get_band('B2'), 2.0)
    rgb = np.dstack([r, g, b])
    
    # Obtener extent de la imagen
    if 'bounds' in satellite_image.metadata:
        bounds = satellite_image.metadata['bounds']
        extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
        ax.imshow(rgb, extent=extent, origin='upper')
    else:
        ax.imshow(rgb)
    
    # Reproyectar litología si es necesario
    if 'crs' in satellite_image.metadata and satellite_image.metadata['crs']:
        litologia_reproj = litologia_gdf.to_crs(satellite_image.metadata['crs'])
    else:
        litologia_reproj = litologia_gdf
    
    # Superponer litología
    litologia_reproj.plot(
        ax=ax,
        edgecolor='yellow',
        facecolor='none',
        linewidth=1.5,
        alpha=alpha_litho
    )
    
    ax.set_title('Imagen Landsat 9 + Litología SGM', fontsize=14, fontweight='bold')
    ax.set_xlabel('Longitud')
    ax.set_ylabel('Latitud')
    
    plt.tight_layout()
    plt.show()
