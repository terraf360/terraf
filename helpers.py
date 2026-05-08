import numpy as np
import pandas as pd

from rasterio import Affine
from spectraf.src.core import SatelliteImage

class helpers:
    def __init__(self):
        pass
    
    def separator(title:str) -> None:
        print(f"\n{'═' * 78}")
        print(f"  {title}")
        print('═' * 78 + '\n')
        
    def _pix_to_utm(y_pix:int, x_pix:int, transform) -> tuple:
        """Convierte coordenadas de píxel (row, col) al centro del píxel en UTM."""
        x_utm = transform.c + (x_pix + 0.5) * transform.a
        y_utm = transform.f + (y_pix + 0.5) * transform.e
        return x_utm, y_utm
    
    def _utm_to_pix(x_utm:float, y_utm:float, transform) -> tuple:
        """Convierte coordenadas UTM al centro del píxel en coordenadas de píxel (row, col)."""
        x_pix = int((x_utm - transform.c) / transform.a)
        y_pix = int((y_utm - transform.f) / transform.e)
        return y_pix, x_pix
    
    def downsample_image(image, factor:int):
        """
        Devuelve un nueo SatelliteImage con la imagen reducida por el factor dado.
        
        """
        if factor <=1:
            return image
        new_bands = {k: v[::factor, ::factor] for k, v in image.bands.items()}
        old_t = image.metadata['transform']
        new_t = Affine(old_t.a * factor, old_t.b, old_t.c, old_t.d, old_t.e * factor, old_t.f)
        new_metadata = image.metadata.copy()
        h, w = next(iter(new_bands.values())).shape
        new_metadata.update({'transform': new_t, 'width': w, 'height': h})
        return SatelliteImage(new_bands, new_metadata, image.sensor_type)