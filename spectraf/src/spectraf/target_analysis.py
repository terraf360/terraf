"""
Análisis automático de targets para exploración de placeres auríferos.

Identifica zonas de interés basándose en:
1. Anomalías espectrales (Iron Oxide Ratio)
2. Litología favorable (rocas ígneas, metamórficas)
3. Clustering espacial (aglomeración de anomalías)
4. Criterios geomorfológicos
"""

import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, List
import matplotlib.pyplot as plt

try:
    import geopandas as gpd
    from shapely.geometry import Point, box
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False

try:
    from scipy.ndimage import label as scipy_label
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def _label_clusters(binary_map: np.ndarray) -> Tuple[np.ndarray, int]:
    """
    Etiqueta componentes conectadas en un mapa binario.

    Usa scipy.ndimage.label cuando está disponible (vectorizado, mucho más
    rápido en imágenes grandes); cae en una implementación BFS pura de
    Python como respaldo.

    Args:
        binary_map: Array booleano 2-D

    Returns:
        (labeled_array, num_labels)
    """
    if SCIPY_AVAILABLE:
        structure = np.ones((3, 3), dtype=int)   # 8-conectividad
        labeled, num_features = scipy_label(binary_map, structure=structure)
        return labeled, num_features

    # --- Fallback BFS (Python puro) ---
    labeled = np.zeros_like(binary_map, dtype=np.int32)
    label = 0

    if not binary_map.any():
        return labeled, 0

    rows, cols = binary_map.shape
    for y in range(rows):
        for x in range(cols):
            if binary_map[y, x] and labeled[y, x] == 0:
                label += 1
                stack = [(y, x)]
                while stack:
                    cy, cx = stack.pop()
                    if 0 <= cy < rows and 0 <= cx < cols:
                        if binary_map[cy, cx] and labeled[cy, cx] == 0:
                            labeled[cy, cx] = label
                            stack.extend([(cy+1, cx), (cy-1, cx),
                                          (cy, cx+1), (cy, cx-1)])
    return labeled, label


def identify_anomaly_zones(
    iron_oxide_ratio: np.ndarray,
    percentile_threshold: float = 75.0,
    min_cluster_size: int = 10
) -> Tuple[np.ndarray, List[Tuple[float, float, float]]]:
    """
    Identifica zonas de anomalía en Iron Oxide Ratio.
    
    Args:
        iron_oxide_ratio: Array con ratio de óxidos de hierro
        percentile_threshold: Percentil para considerar anomalía (75=cuartil superior)
        min_cluster_size: Tamaño mínimo de cluster en píxeles
    
    Returns:
        Tuple de (mapa_anomalías, lista_centroides)
        - mapa_anomalías: Array binario con píxeles anómalos
        - lista_centroides: [(y, x, intensidad), ...] centros de clusters
    """
    # Validar data
    valid_mask = np.isfinite(iron_oxide_ratio) & (iron_oxide_ratio > 0)
    
    if not valid_mask.any():
        return np.zeros_like(iron_oxide_ratio, dtype=bool), []
    
    # Calcular threshold
    valid_data = iron_oxide_ratio[valid_mask]
    threshold = np.percentile(valid_data, percentile_threshold)
    
    # Crear mapa binario de anomalías
    anomaly_map = iron_oxide_ratio > threshold
    
    # Encontrar clusters conectados
    labeled_array, num_features = _label_clusters(anomaly_map)
    
    # Extraer centroides de clusters significativos
    centroides = []
    for i in range(1, num_features + 1):
        cluster = np.where(labeled_array == i)
        
        if len(cluster[0]) >= min_cluster_size:
            # Centro del cluster
            y_center = int(np.mean(cluster[0]))
            x_center = int(np.mean(cluster[1]))
            
            # Intensidad promedio en el cluster
            intensity = np.mean(iron_oxide_ratio[cluster])
            
            centroides.append((y_center, x_center, intensity))
    
    return anomaly_map, centroides


def create_target_geodataframe(
    centroides: List[Tuple[float, float, float]],
    image,  # SatelliteImage
    litologia_gdf: Optional['gpd.GeoDataFrame'] = None,
    pixel_size: float = 30.0  # metros (tamaño de píxel Landsat 9)
) -> 'gpd.GeoDataFrame':
    """
    Convierte centroides de anomalías en GeoDataFrame de targets.
    
    Args:
        centroides: Lista de (y, x, intensidad) en coordenadas de píxel
        image: Instancia de SatelliteImage con metadatos geoespaciales
        litologia_gdf: GeoDataFrame de litología para enriquecer targets
        pixel_size: Tamaño del píxel en metros
    
    Returns:
        GeoDataFrame con targets georreferenciados
    """
    if not GEOPANDAS_AVAILABLE:
        raise ImportError("geopandas es requerido")
    
    if not centroides:
        print("⚠ No hay anomalías significativas para generar targets")
        return gpd.GeoDataFrame()
    
    targets_data = []

    # Obtener información geoespacial
    bounds = image.metadata.get('bounds')
    transform = image.metadata.get('transform')
    crs = image.metadata.get('crs')

    for target_idx, (y_pix, x_pix, intensity) in enumerate(centroides):
        # Convertir píxel a coordenadas geográficas
        if transform:
            x_coord = transform.c + (x_pix * transform.a)
            y_coord = transform.f + (y_pix * transform.e)
        elif bounds:
            height, width = image.shape()
            x_coord = bounds.left + (x_pix / width) * (bounds.right - bounds.left)
            y_coord = bounds.top + (y_pix / height) * (bounds.bottom - bounds.top)
        else:
            x_coord, y_coord = x_pix, y_pix

        targets_data.append({
            'target_id': f'T{target_idx+1:03d}',
            'longitude': x_coord,
            'latitude': y_coord,
            'anomaly_intensity': intensity,
            'pixel_y': int(y_pix),
            'pixel_x': int(x_pix),
            'geometry': Point(x_coord, y_coord)
        })

    targets_gdf = gpd.GeoDataFrame(targets_data, crs=crs)

    # Enriquecer con litología usando sjoin (evita iterrows sobre el GDF completo)
    if litologia_gdf is not None and len(litologia_gdf) > 0 and len(targets_gdf) > 0:
        try:
            # Reproyectar si es necesario
            litologia_crs = litologia_gdf.to_crs(crs) if crs else litologia_gdf

            # Detectar columna de litología
            litho_col = next(
                (c for c in ['CVE_LITOLO', 'LITOLOGIA', 'CLAVE'] if c in litologia_crs.columns),
                None
            )

            if litho_col:
                joined = gpd.sjoin(
                    targets_gdf, litologia_crs[[litho_col, 'geometry']],
                    how='left', predicate='within'
                )
                # sjoin puede duplicar filas si un punto cae en >1 polígono;
                # mantenemos solo el primer match por target
                joined = joined[~joined.index.duplicated(keep='first')]
                targets_gdf['lithology'] = joined[litho_col].values
        except Exception as exc:
            print(f"⚠ No se pudo agregar litología a los targets: {exc}")

    return targets_gdf


def plot_targets_on_anomaly_map(
    iron_oxide_ratio: np.ndarray,
    targets_gdf: 'gpd.GeoDataFrame',
    image,  # SatelliteImage
    anomaly_map: Optional[np.ndarray] = None,
    figsize: Tuple[int, int] = (14, 12),
    downsample: int = 2
):
    """
    Visualiza targets sobre el mapa de anomalías de Iron Oxide Ratio.
    
    Args:
        iron_oxide_ratio: Array con ratio de óxidos de hierro
        targets_gdf: GeoDataFrame con targets identificados
        image: SatelliteImage con metadatos
        anomaly_map: Array binario de anomalías (opcional)
        figsize: Tamaño de la figura
        downsample: Factor de submuestreo para visualización
    """
    fig, ax = plt.subplots(figsize=figsize)
    
    # Normalizar y mostrar Iron Oxide Ratio
    from .visualization import normalize_ratio
    
    ior_display = iron_oxide_ratio[::downsample, ::downsample]
    ior_norm = normalize_ratio(ior_display, percentile_clip=2.0)
    
    im = ax.imshow(ior_norm, cmap='YlOrRd', interpolation='bilinear')
    
    # Superponer anomalías (contorno)
    if anomaly_map is not None:
        anomaly_display = anomaly_map[::downsample, ::downsample].astype(float)
        contours = plt.contour(anomaly_display, levels=[0.5], colors='cyan', linewidths=2)
        ax.clabel(contours, inline=True, fontsize=8)
    
    # Plotear targets
    if len(targets_gdf) > 0:
        # Convertir a píxeles para plotear
        bounds = image.metadata.get('bounds')
        height, width = image.shape()
        
        if bounds:
            for idx, row in targets_gdf.iterrows():
                x_coord = row.geometry.x
                y_coord = row.geometry.y
                
                # Convertir coordenadas a píxeles
                x_pix = int((x_coord - bounds.left) / (bounds.right - bounds.left) * width) // downsample
                y_pix = int((bounds.top - y_coord) / (bounds.top - bounds.bottom) * height) // downsample
                
                # Graficar target
                circle = plt.Circle((x_pix, y_pix), radius=20, color='lime', 
                                  fill=False, linewidth=2, zorder=10)
                ax.add_patch(circle)
                
                # Label
                ax.text(x_pix + 25, y_pix, row.get('target_id', f'T{idx}'), 
                       color='lime', fontsize=9, fontweight='bold', zorder=11)
    
    ax.set_title('Targets de Exploración sobre Iron Oxide Ratio\n(Círculos = Zonas de Interés para Geofísica)', 
                fontsize=12, fontweight='bold')
    ax.axis('off')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label='Iron Oxide Intensity')
    plt.tight_layout()
    plt.show()
    
    print(f"✓ Visualizados {len(targets_gdf)} targets de exploración")


def export_targets_to_shapefile(
    targets_gdf: 'gpd.GeoDataFrame',
    output_path: Path,
    overwrite: bool = True
) -> Path:
    """
    Exporta targets a shapefile para usar en SIG (ArcGIS, QGIS, etc).
    
    Args:
        targets_gdf: GeoDataFrame con targets
        output_path: Ruta del shapefile de salida
        overwrite: Sobreescribir si existe
    
    Returns:
        Path del archivo generado
    """
    if not GEOPANDAS_AVAILABLE:
        raise ImportError("geopandas es requerido")
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Guardar como shapefile
    targets_gdf.to_file(str(output_path), driver='ESRI Shapefile')
    
    print(f"✓ Targets exportados a: {output_path}")
    
    return output_path


def generate_target_report(
    targets_gdf: 'gpd.GeoDataFrame',
    image
) -> str:
    """
    Genera un reporte de los targets identificados.
    
    Args:
        targets_gdf: GeoDataFrame con targets
        image: SatelliteImage original
    
    Returns:
        String con el reporte formateado
    """
    report = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    REPORTE DE TARGETS IDENTIFICADOS                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

Escena: {image.metadata.get('scene_id', 'N/A')}
Fecha: {image.metadata.get('date', 'N/A')}
CRS: {image.metadata.get('crs', 'N/A')}

📊 ESTADÍSTICAS:
  • Total de targets: {len(targets_gdf)}
  • Intensidad promedio: {targets_gdf['anomaly_intensity'].mean():.3f}
  • Intensidad máxima: {targets_gdf['anomaly_intensity'].max():.3f}
  • Intensidad mínima: {targets_gdf['anomaly_intensity'].min():.3f}

📍 TARGETS IDENTIFICADOS:
"""
    
    for idx, row in targets_gdf.iterrows():
        lithology = row.get('lithology', 'Sin datos')
        report += f"\n  {row['target_id']}: Lat {row.geometry.y:.4f}°, Lon {row.geometry.x:.4f}°"
        report += f"\n       Intensidad: {row['anomaly_intensity']:.3f} | Litología: {lithology}"
    
    report += f"""

🎯 PRÓXIMOS PASOS:
  1. Validar targets en campo (observación geomorfológica)
  2. Realizar levantamiento magnetométrico en targets prioritarios
  3. Muestreo geoquímico de sedimentos
  4. Bateo exploratorio en zonas de acceso
  5. Geofísica de detalle (GPR, resistividad) en targets confirmados

✓ Reporte generado: {len(targets_gdf)} targets listos para exploración

"""
    
    return report
