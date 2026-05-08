"""
Análisis de Favorabilidad para Placeres Auríferos
==================================================

Script simplificado que se ejecuta desde la raíz del proyecto terraf.
Ejecutar con: python analisis_placeres.py
"""

import sys
from pathlib import Path

# Agregar spectraf/src al path
sys.path.insert(0, str(Path(__file__).parent / 'spectraf' / 'src'))

# Ahora podemos importar
import numpy as np
import matplotlib.pyplot as plt

# Imports de spectraf (ahora funcionarán con imports relativos)
import core
import loaders  
import indices
import visualization

# Opcional: geology
try:
    import geology
    GEOLOGY_AVAILABLE = True
except ImportError:
    GEOLOGY_AVAILABLE = False
    print("⚠ Módulo geology no disponible (requiere geopandas)")


def main():
    print("=" * 80)
    print("ANÁLISIS DE FAVORABILIDAD PARA PLACERES AURÍFEROS")
    print("=" * 80)
    print()
    
    # =========================================================================
    # PASO 1: CARGAR IMAGEN LANDSAT 9
    # =========================================================================
    print("\n" + "─" * 80)
    print("PASO 1: Procesamiento de Imágenes Landsat 9")
    print("─" * 80)
    
    scene_id = 'LC09_L2SP_031042_20260212_20260213_02_T1'
    data_path = Path(__file__).parent / 'datos'
    
    print(f"\nCargando imagen Landsat 9: {scene_id}...")
    print(f"Buscando en: {data_path / 'landsat9' / scene_id}")
    
    image = loaders.load_landsat9_image(scene_id, data_path=data_path)
    
    print(f"✓ Imagen cargada exitosamente")
    print(f"  - Sensor: {image.sensor_type}")
    print(f"  - Dimensiones: {image.shape()}")
    print(f"  - Bandas: {image.list_bands()}")
    print(f"  - Fecha: {image.metadata.get('date', 'N/A')}")
    print(f"  - CRS: {image.metadata.get('crs', 'N/A')}")
    
    # =========================================================================
    # PASO 2: CALCULAR ÍNDICES GEOLÓGICOS
    # =========================================================================
    print("\n" + "─" * 80)
    print("PASO 2: Cálculo de Índices Espectrales Geológicos")
    print("─" * 80)
    
    # Iron Oxide Ratio (B4/B2)
    print("\n[1] Calculando Iron Oxide Ratio (B4/B2)...")
    print("    Objetivo: Detectar óxidos de hierro (magnetita, hematita, ilmenita)")
    print("    Aplicación: Localizar 'arenas negras' asociadas a placeres auríferos")
    iron_oxide = indices.calculate_iron_oxide_ratio(image)
    print(f"    ✓ {iron_oxide.metadata['index']} calculado")
    
    # Clay Ratio (B6/B7)
    print("\n[2] Calculando Clay/Hydroxyl Ratio (B6/B7)...")
    print("    Objetivo: Identificar alteración hidrotermal")
    print("    Aplicación: Localizar zona fuente río arriba")
    clay = indices.calculate_clay_ratio(image)
    print(f"    ✓ {clay.metadata['index']} calculado")
    
    # Ferrous Minerals Ratio (B6/B5)
    print("\n[3] Calculando Ferrous Minerals Ratio (B6/B5)...")
    print("    Objetivo: Diferenciar materiales litológicos en el cauce")
    print("    Aplicación: Identificar cambios en composición del sustrato")
    ferrous = indices.calculate_ferrous_minerals_ratio(image)
    print(f"    ✓ {ferrous.metadata['index']} calculado")
    
    # Geological Composite
    print("\n[4] Generando Composición Geológica RGB...")
    print("    R: B6/B7 (Arcillas)")
    print("    G: B6/B5 (Minerales ferrosos)")
    print("    B: B4/B2 (Óxidos de hierro)")
    print("    Aplicación: Visualización integrada de anomalías")
    composite = indices.calculate_geological_composite(image)
    print(f"    ✓ {composite.metadata['index']} generado")
    
    # NDVI
    print("\n[5] Calculando NDVI...")
    print("    Objetivo: Discriminar zonas de vegetación vs suelo desnudo")
    print("    Aplicación: Enmascarar áreas con vegetación densa")
    ndvi = indices.calculate_ndvi(image)
    print(f"    ✓ {ndvi.metadata['index']} calculado")
    
    # =========================================================================
    # PASO 3: VISUALIZACIÓN DE ÍNDICES GEOLÓGICOS
    # =========================================================================
    print("\n" + "─" * 80)
    print("PASO 3: Visualización de Ratios Geológicos")
    print("─" * 80)
    
    print("\nGenerando panel de ratios geológicos...")
    print("(Mostrará 4 visualizaciones: IOR, Clay, Ferrous, Composite)")
    visualization.plot_geological_ratios(image)
    
    # =========================================================================
    # PASO 4: ANÁLISIS DE EXPLORACIÓN MINERAL COMPLETO
    # =========================================================================
    print("\n" + "─" * 80)
    print("PASO 4: Panel de Análisis de Exploración Mineral")
    print("─" * 80)
    
    print("\nGenerando panel completo de análisis...")
    print("(Color natural + Composite + Iron Oxide + NDVI)")
    visualization.plot_mineral_exploration_analysis(image)
    
    # =========================================================================
    # PASO 5: INTEGRACIÓN CON LITOLOGÍA DEL SGM
    # =========================================================================
    print("\n" + "─" * 80)
    print("PASO 5: Integración con Litología del SGM")
    print("─" * 80)
    
    if not GEOLOGY_AVAILABLE:
        print("\n⚠ Módulo geology no disponible.")
        print("Para usar datos del SGM, instala geopandas:")
        print("  pip install geopandas")
    else:
        try:
            print("\nCargando litología del SGM...")
            litologia = geology.load_sgm_litologia()
            
            # Resumen
            print("\n📊 Resumen Litológico:")
            summary = geology.get_lithology_summary(litologia)
            print(f"  - Total de polígonos: {summary['total_polygons']}")
            
            if summary['unique_units']:
                print("\n  Unidades litológicas presentes:")
                for unit, count in list(summary['unique_units'].items())[:10]:
                    print(f"    • {unit}: {count} polígonos")
            
            # Visualizar
            print("\nVisualizando mapa de litología...")
            geology.plot_lithology_map(litologia)
            
            # Filtrar favorables
            print("\n🎯 Filtrando unidades litológicas favorables...")
            favorable_keywords = [
                'Ig', 'Igneo', 'Intrusiv', 'Granit', 'Diorit', 'Tonalita',
                'Met', 'Metamorf', 'Esquist', 'Gneis',
                'Qz', 'Cuarzo', 'Veta',
                'Andesit', 'Riolit', 'Dacit', 'Volcan'
            ]
            
            favorable = geology.filter_lithology_favorable(litologia, favorable_keywords)
            
            if len(favorable) > 0:
                print(f"   ✓ Identificadas {len(favorable)} unidades favorables")
                geology.plot_lithology_map(
                    favorable,
                    title="Unidades Litológicas Favorables para Mineralización"
                )
            
            # Overlay
            print("\n🗺️  Superponiendo imagen satelital y litología...")
            try:
                geology.overlay_satellite_and_lithology(image, litologia)
            except Exception as e:
                print(f"   ⚠ Error al superponer: {e}")
        
        except FileNotFoundError as e:
            print(f"\n⚠ {e}")
        except Exception as e:
            print(f"\n⚠ Error: {e}")
    
    # =========================================================================
    # INTERPRETACIÓN
    # =========================================================================
    print("\n" + "=" * 80)
    print("CRITERIOS DE INTERPRETACIÓN")
    print("=" * 80)
    
    print("""
📍 TARGETS PRIORITARIOS - Zonas donde coincidan:

1. FIRMA ESPECTRAL (Landsat 9):
   ✓ Alto Iron Oxide Ratio (colores cálidos en visualización)
   ✓ Anomalías en Clay Ratio → Alteración río arriba
   ✓ Bajo NDVI → Suelo desnudo/acceso

2. GEOMORFOLOGÍA (analizar visualmente):
   ✓ Paleocauces, abanicos aluviales, terrazas
   ✓ Meandros abandonados (trampas naturales)
   ✓ Confluencias de cauces

3. LITOLOGÍA FAVORABLE (SGM):
   ✓ Intrusivos, vetas de cuarzo, metamórficas río arriba
   ✓ Cruces con fallas/fracturas

🔜 SIGUIENTE PASO: Geofísica y muestreo en targets seleccionados
""")
    
    print("=" * 80)
    print("✓ ANÁLISIS COMPLETADO")
    print("=" * 80)


if __name__ == "__main__":
    main()
