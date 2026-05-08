"""
Clases principales de spectraf.
"""
from typing import Dict, Optional, Tuple, List
import numpy as np


class SatelliteImage:
    """
    Contenedor para imágenes de satélite con múltiples bandas espectrales.
    
    Attributes:
        bands: Diccionario de bandas espectrales {nombre: array numpy}
        metadata: Información de la escena (CRS, resolución, bounds, etc.)
        sensor_type: Tipo de sensor ('landsat9', 'sentinel2', etc.)
    """
    
    def __init__(
        self, 
        bands: Dict[str, np.ndarray],
        metadata: Dict,
        sensor_type: str
    ):
        """
        Inicializa una imagen de satélite.
        
        Args:
            bands: Diccionario con las bandas espectrales
            metadata: Metadatos de la imagen (CRS, resolución, etc.)
            sensor_type: Tipo de sensor
        """
        self.bands = bands
        self.metadata = metadata
        self.sensor_type = sensor_type
        
    def get_band(self, band_name: str) -> np.ndarray:
        """
        Obtiene una banda específica.
        
        Args:
            band_name: Nombre de la banda (ej: 'B4', 'NDVI')
        
        Returns:
            Array numpy con los valores de la banda
        
        Raises:
            KeyError: Si la banda no existe
        """
        if band_name not in self.bands:
            available = ', '.join(self.bands.keys())
            raise KeyError(f"Banda '{band_name}' no encontrada. Disponibles: {available}")
        return self.bands[band_name]
    
    def list_bands(self) -> List[str]:
        """Retorna la lista de bandas disponibles."""
        return list(self.bands.keys())
    
    def shape(self) -> Tuple[int, int]:
        """Retorna las dimensiones (height, width) de la imagen."""
        first_band = next(iter(self.bands.values()))
        return first_band.shape
    
    def show(
        self,
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
        Visualiza la imagen de satélite.
        
        Args:
            natural_color: Si True, muestra composición RGB en color natural
            bands: Tupla con 3 nombres de bandas para composición RGB personalizada
            cmap: Mapa de colores para imágenes de una sola banda
            title: Título del gráfico
            figsize: Tamaño de la figura
            percentile_clip: Percentil para recorte en normalización
            vmin: Valor mínimo para escala de colores
            vmax: Valor máximo para escala de colores
        """
        from .visualization import plot_image
        
        plot_image(
            self,
            natural_color=natural_color,
            bands=bands,
            cmap=cmap,
            title=title,
            figsize=figsize,
            percentile_clip=percentile_clip,
            vmin=vmin,
            vmax=vmax
        )
    
    def __repr__(self) -> str:
        """Representación en string de la imagen."""
        height, width = self.shape()
        n_bands = len(self.bands)
        bands_str = ', '.join(self.bands.keys())
        return (
            f"SatelliteImage(sensor='{self.sensor_type}', "
            f"shape=({height}, {width}), "
            f"bands={n_bands}: [{bands_str}])"
        )
