"""
Ejemplo de uso del módulo spectraf para procesamiento de imágenes de satélite.
"""
import spectraf


def main():
    print("=" * 60)
    print("Ejemplo de uso de spectraf")
    print("=" * 60)
    
    # 1. Cargar una imagen de satélite Landsat 9
    print("\n1. Cargando imagen de satélite...")
    scene_id = 'LC09_L2SP_024048_20260110_20260111_02_T1'
    image = spectraf.load_landsat9_image(scene_id)
    print(f"   ✓ Imagen cargada: {image}")
    
    # 2. Visualizar en color natural (RGB)
    print("\n2. Mostrando composición en color natural...")
    image.show(natural_color=True)
    
    # 2.1 Visualizar falso color (SWIR, NIR, Red)
    print("\n2.1 Mostrando composición en falso color (SWIR, NIR, Red)...")
    image.show(bands=['B6', 'B5', 'B4'])  # SWIR, NIR, Red para falso color
    
    # 3. Calcular el índice de vegetación NDVI
    print("\n3. Calculando NDVI (Índice de Vegetación)...")
    ndvi = spectraf.calculate_ndvi(image)
    print(f"   ✓ NDVI calculado: {ndvi}")
    ndvi.show()
    
    # 4. Calcular el índice de agua NDWI
    print("\n4. Calculando índice de agua NDWI...")
    ndwi = spectraf.calculate_ndwi(image)
    print(f"   ✓ NDWI calculado: {ndwi}")
    ndwi.show(cmap='Blues')
    
    print("\n" + "=" * 60)
    print("Ejemplo completado exitosamente")
    print("=" * 60)


if __name__ == "__main__":
    main()