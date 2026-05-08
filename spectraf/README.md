# spectraf

**spectraf** es una herramienta de Python para el procesamiento y analisis de imagenes de satelite orientada a exploracion mineral. Permite cargar imagenes Landsat 9, calcular indices espectrales geologicos e integrar datos vectoriales del SGM (Servicio Geologico Mexicano) para identificar automaticamente zonas de interes para exploracion de placeres auriferos.

## Caracteristicas

- **Carga automatica** de imagenes Landsat 9 (Level 2 Surface Reflectance)
- **Indices espectrales geologicos**: Iron Oxide Ratio, Clay Ratio, Ferrous Minerals Ratio
- **Indices de vegetacion**: NDVI, NDWI, EVI, SAVI
- **Integracion con datos SGM**: litologia, geoquimica, inventarios mineros
- **Analisis automatico de targets** en 5 fases (armonizacion -> espectral -> filtro geologico -> AND logico -> vectorizacion)
- **Exportacion a GeoJSON y Shapefile** para su uso en QGIS / ArcGIS / Google Earth

---

## Instalacion

### Opcion 1 - conda (recomendado)

```bash
git clone https://github.com/terraf360/spectraf.git
cd spectraf
conda env create -f environment.yml
conda activate spectraf
```
### Opcion 2 - pip

```bash
git clone https://github.com/terraf360/spectraf.git
cd spectraf
pip install -r requirements.txt
```
---

## Estructura de datos requerida

Los datos **no estan incluidos en el repositorio** por su tamano. Deben colocarse en la carpeta datos/ dentro del raiz del repo:

```text
spectraf/
|-- datos/
    |-- landsat9/
    |   |-- LC09_L2SP_XXXXX.../      <- carpeta de la escena descargada de EarthExplorer
    |       |-- *_SR_B2.TIF
    |       |-- *_SR_B3.TIF
    |       |-- *_SR_B4.TIF
    |       |-- *_SR_B5.TIF
    |       |-- *_SR_B6.TIF
    |       |-- *_SR_B7.TIF
    |       |-- *_MTL.txt
    |-- SGM/
        |-- Carta/
            |-- <carta_id>/          <- ID de descarga del SGM
                |-- Litologia_G13_5.shp
                |-- Geoquimica_G13_5.shp
                |-- InventariosMineros_G13_5.shp
```
| Fuente | URL |
|--------|-----|
| Landsat 9 (Level 2 SR) | https://earthexplorer.usgs.gov |
| Cartas geologicas SGM  | https://www.sgm.gob.mx/GeoInfoMexGobMx |

---

## Analisis de placeres auriferos (5 fases)

```text
Fase 1 - Armonizacion      -> Reproyeccion, recorte, rasterizacion de litologia
Fase 2 - Firmas espectrales -> Iron Oxide Ratio + Clay Ratio normalizados 0-1
Fase 3 - Filtro geologico   -> Mascara litologia favorable + buffer 500 m
Fase 4 - Integracion AND    -> TARGET si (IOR > umbral) AND (Clay > umbral) AND (favorable)
Fase 5 - Vectorizacion      -> Morfologia, clustering, GeoJSON + Shapefile
```
### Configuracion

Edita la seccion CONFIGURACION GLOBAL al inicio de examples/analisis_placeres_auriferos.py:

```python
SCENE_ID  = 'LC09_L2SP_031042_20260212_20260213_02_T1'   # <- tu escena
CARTA_ID  = 'A18022026162831O'                            # <- tu carta SGM

IRON_THRESHOLD     = 0.65   # umbral Iron Oxide Ratio (0-1)
CLAY_THRESHOLD     = 0.55   # umbral Clay Ratio (0-1)
PROCESS_DOWNSAMPLE = 4      # 1=full res (lento), 4=aprox 16x mas rapido
APPLY_BUFFER       = True   # buffer de 500 m en contactos geologicos
```
### Ejecucion

```bash
conda activate spectraf
python examples/analisis_placeres_auriferos.py
```
### Salidas en results/

| Archivo | Descripcion |
|---------|-------------|
| fase2_firmas_espectrales.png | Iron Oxide Ratio y Clay Ratio normalizados |
| fase3_filtro_geologico.png   | Litologia favorable + buffer |
| fase4_integracion_logica.png | Los 4 criterios y el resultado AND |
| fase5_targets_finales.png    | Mapa final con targets priorizados |
| targets_exploracion.geojson  | Targets para QGIS / Google Earth |
| targets_exploracion.shp      | Shapefile para ArcGIS / QGIS |

---

## Uso como libreria

```python
import sys
from pathlib import Path
# Si no lo instalaste como paquete, agrega el directorio padre al path:
sys.path.insert(0, str(Path('spectraf').resolve().parent))

import spectraf.src as spectraf

# Cargar imagen Landsat 9
image = spectraf.load_landsat9_image(
    'LC09_L2SP_031042_20260212_20260213_02_T1',
    data_path=Path('datos')
)

# Indices geologicos
ior  = spectraf.calculate_iron_oxide_ratio(image)
clay = spectraf.calculate_clay_ratio(image)

# Visualizacion
image.show(natural_color=True)
ior.show(cmap='YlOrRd')

# Datos SGM
litologia = spectraf.load_sgm_litologia('A18022026162831O', data_path=Path('datos'))
spectraf.overlay_satellite_and_lithology(image, litologia)
```
---

## Indices espectrales

### Geologicos

| Indice | Bandas Landsat 9 | Aplicacion |
|--------|-----------------|------------|
| Iron Oxide Ratio      | B4 / B2       | Hematita, magnetita, arenas negras |
| Clay / Hydroxyl Ratio | B6 / B7       | Alteracion hidrotermal, arcillas |
| Ferrous Minerals Ratio| B6 / B5       | Diferenciacion litologica |
| Geological Composite  | RGB: B6/B7, B6/B5, B4/B2 | Visualizacion de anomalias |

### Vegetacion y agua

| Indice | Formula | Uso |
|--------|---------|-----|
| NDVI | (B5-B4)/(B5+B4) | Densidad de vegetacion |
| NDWI | (B3-B5)/(B3+B5) | Cuerpos de agua |
| EVI  | 2.5*(B5-B4)/(B5+6B4-7.5B2+1) | Vegetacion densa |
| SAVI | ((B5-B4)/(B5+B4+L))*(1+L) | Suelo visible |

---

## Estructura del proyecto

```text
spectraf/
|-- environment.yml         # Entorno conda
|-- requirements.txt        # Dependencias pip
|-- README.md
|-- src/
|   |-- core.py             # Clase SatelliteImage
|   |-- loaders.py          # Carga de imagenes (Landsat 9)
|   |-- indices.py          # Indices espectrales y geologicos
|   |-- geology.py          # Integracion con datos SGM
|   |-- target_analysis.py  # Identificacion automatica de targets
|   |-- visualization.py    # Normalizacion y visualizacion
|   |-- utils.py            # Utilidades auxiliares
|-- examples/
|   |-- analisis_placeres_auriferos.py   # Analisis completo 5 fases
|   |-- ejemplo_uso.py                   # Uso basico
|-- results/                # Salidas generadas (no versionadas)
|-- datos/                  # Datos de entrada (no versionados, ver arriba)
```
## Roadmap

- [ ] Soporte para Sentinel-2
- [ ] Indices adicionales: NDBI, NBR, MNDWI
- [ ] Exportacion a GeoTIFF
- [ ] Analisis de series temporales
- [ ] Instalacion como paquete pip

## Licencia

Proyecto [terraf360](https://github.com/terraf360) - Herramientas de procesamiento geoespacial para exploracion mineral.
