"""
TerraF — Integración con datos nacionales de México.

Fuentes:
  - INEGI: Uso de Suelo y Vegetación Serie II (shapefile 769MB, todo México)
  - SGM (GeoInfoMex): Geología, Geofísica, Geoquímica, Inventario Minero (cartas 1:250,000)

Estrategia: recorte espacial al bbox de la imagen Landsat activa.
Solo se almacenan los features que intersectan el área de trabajo.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator, Optional

from terraf.db.models import DatoGeologico, FeatureGeologico, Imagen, Proyecto
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DatoNacionalResult:
    """Resultado de cargar una fuente de datos nacionales."""
    fuente: str                         # "inegi" | "sgm"
    capa: str                           # "inegi_usosue" | "sgm_geologia" | etc.
    n_features: int                     # features efectivamente insertados
    n_ya_existian: int                  # capas que ya estaban en DB (0 o 1)
    bbox_usado: Optional[tuple[float, float, float, float]]  # (minx, miny, maxx, maxy) WGS84


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def _gdal_shape_encoding(gdal_encoding: str = "CP1252") -> Generator[None, None, None]:
    """
    Context manager que fuerza la codificación de shapefiles a través de la
    opción de configuración GDAL SHAPE_ENCODING.

    Necesario para shapefiles INEGI cuyo .cpg declara incorrectamente UTF-8
    mientras los datos están en Windows-1252 / Latin-1.

    Se restaura el valor previo al salir (o se limpia si no había valor).
    """
    try:
        import pyogrio
    except ImportError:
        # Sin pyogrio, no podemos forzar encoding; dejamos pasar
        yield
        return

    prev = pyogrio.get_gdal_config_option("SHAPE_ENCODING")
    pyogrio.set_gdal_config_options({"SHAPE_ENCODING": gdal_encoding})
    try:
        yield
    finally:
        if prev is not None:
            pyogrio.set_gdal_config_options({"SHAPE_ENCODING": prev})
        else:
            pyogrio.set_gdal_config_options({"SHAPE_ENCODING": ""})


def _get_image_bbox(db_path: Path) -> Optional[tuple[float, float, float, float]]:
    """
    Obtiene el bounding box de la imagen Landsat activa en coordenadas WGS84.

    Estrategia:
    1. Consulta la tabla imagenes y toma la primera imagen del proyecto.
    2. Si tiene escena_path, usa rasterio para leer bounds y CRS.
    3. Reproyecta a WGS84 si es necesario.
    4. Retorna (minx, miny, maxx, maxy) o None si no hay imagen o falla.
    """
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.warp import transform_bounds
    except ImportError:
        return None

    with open_session(db_path) as session:
        imagen = session.query(Imagen).first()
        if imagen is None:
            return None
        escena_path = imagen.escena_path if hasattr(imagen, "escena_path") else imagen.ruta_archivo

    if not escena_path:
        return None

    ruta = Path(escena_path)
    if not ruta.exists():
        return None

    try:
        with rasterio.open(ruta) as ds:
            src_crs = ds.crs
            bounds = ds.bounds  # BoundingBox(left, bottom, right, top)

        if src_crs is None:
            return None

        wgs84 = CRS.from_epsg(4326)
        if src_crs == wgs84:
            return (bounds.left, bounds.bottom, bounds.right, bounds.top)

        minx, miny, maxx, maxy = transform_bounds(
            src_crs, wgs84,
            bounds.left, bounds.bottom, bounds.right, bounds.top,
        )
        return (minx, miny, maxx, maxy)

    except Exception:
        return None


def _get_proyecto_id(db_path: Path) -> Optional[int]:
    """Obtiene el ID del primer proyecto en la DB."""
    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        return proyecto.id if proyecto else None


def _discover_shapefiles(data_path: Path) -> list[Path]:
    """Busca todos los shapefiles en un directorio (recursivo)."""
    return sorted(data_path.rglob("*.shp"))


def _pick_shapefile_for_tipo(shapefiles: list[Path], tipo: str) -> Optional[Path]:
    """
    Selecciona el shapefile más relevante según el tipo SGM solicitado.

    Busca coincidencias de palabras clave en el nombre del archivo.
    Si no hay coincidencia, retorna el primero de la lista.
    """
    _TIPO_KEYWORDS: dict[str, list[str]] = {
        "geologia":        ["geolog", "litolog", "litho"],
        "geofisica":       ["geofis", "geoph", "magnet", "gravim"],
        "geoquimica":      ["geoqu", "geoch"],
        "inventario_minero": ["inventar", "miner", "sitio", "yacim"],
    }

    keywords = _TIPO_KEYWORDS.get(tipo, [tipo])
    lower_tipo = tipo.lower()

    # Primero: coincidencia exacta de palabras clave
    for kw in keywords:
        for shp in shapefiles:
            if kw in shp.name.lower():
                return shp

    # Segundo: nombre del tipo directamente
    for shp in shapefiles:
        if lower_tipo in shp.name.lower():
            return shp

    # Fallback: primero de la lista
    return shapefiles[0] if shapefiles else None


def _serialize_attrs(row_dict: dict) -> str:
    """Serializa los atributos de un feature a JSON, convirtiendo tipos no serializables."""
    clean: dict = {}
    for k, v in row_dict.items():
        if v is None:
            clean[k] = None
        elif isinstance(v, (int, float, bool, str)):
            clean[k] = v
        else:
            try:
                clean[k] = str(v)
            except Exception:
                clean[k] = None
    return json.dumps(clean, ensure_ascii=False)


def _insert_features_batch(
    session,
    dato_geologico_id: int,
    features: list[dict],
    chunk_size: int = 500,
) -> int:
    """
    Inserta features en la DB en lotes de chunk_size.

    Cada elemento de `features` debe tener:
      - tipo: Optional[str]
      - nombre: Optional[str]
      - atributos_json: str
      - geometria_wkt: Optional[str]

    Retorna el número de features insertados.
    """
    total = 0
    batch: list[FeatureGeologico] = []

    for feat in features:
        if feat.get("geometria_wkt") is None:
            continue  # omitir features sin geometría

        obj = FeatureGeologico(
            dato_geologico_id=dato_geologico_id,
            tipo=feat.get("tipo"),
            nombre=feat.get("nombre"),
            atributos_json=feat.get("atributos_json"),
            geometria_wkt=feat["geometria_wkt"],
            es_favorable=None,
        )
        batch.append(obj)
        total += 1

        if len(batch) >= chunk_size:
            session.add_all(batch)
            session.flush()
            batch = []

    if batch:
        session.add_all(batch)
        session.flush()

    return total


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def cargar_inegi_usosue(
    db_path: Path,
    shp_path: Path,
    on_step: Optional[Callable[[str], None]] = None,
) -> DatoNacionalResult:
    """
    Carga el shapefile de Uso de Suelo y Vegetación del INEGI (Serie II).

    Recorta al bbox de la imagen Landsat activa en el proyecto.
    Si no hay imagen activa, carga el país completo con una advertencia.

    Args:
        db_path:  Ruta al archivo terraf.db del proyecto.
        shp_path: Ruta al .shp de INEGI (769MB, todo México, LATIN-1).
        on_step:  Callback opcional para reportar progreso (on_step(mensaje)).

    Returns:
        DatoNacionalResult con estadísticas de la carga.

    Raises:
        FileNotFoundError: si shp_path no existe.
        RuntimeError:      si no hay proyecto inicializado en db_path.
    """
    import geopandas as gpd

    shp_path = Path(shp_path).resolve()
    if not shp_path.exists():
        raise FileNotFoundError(f"No se encontró el shapefile INEGI: {shp_path}")

    CAPA = "inegi_usosue"

    # ── Verificar proyecto ────────────────────────────────────────────────────
    proyecto_id = _get_proyecto_id(db_path)
    if proyecto_id is None:
        raise RuntimeError("No hay proyecto inicializado en la base de datos.")

    # ── Idempotencia: verificar si ya existe esta capa ────────────────────────
    with open_session(db_path) as session:
        existente = (
            session.query(DatoGeologico)
            .filter_by(proyecto_id=proyecto_id, capa=CAPA)
            .first()
        )
        if existente:
            return DatoNacionalResult(
                fuente="inegi",
                capa=CAPA,
                n_features=existente.num_features or 0,
                n_ya_existian=1,
                bbox_usado=None,
            )

    # ── Obtener bbox de la imagen activa ─────────────────────────────────────
    if on_step:
        on_step("Obteniendo bbox de la imagen activa...")

    bbox = _get_image_bbox(db_path)
    if bbox is None and on_step:
        on_step("ADVERTENCIA: No hay imagen activa, cargando datos nacionales completos.")

    # ── Leer shapefile con recorte espacial ───────────────────────────────────
    if on_step:
        on_step("Leyendo shapefile INEGI (esto puede tardar varios segundos)...")

    import pyogrio
    read_kwargs: dict = {}
    if bbox is not None:
        read_kwargs["bbox"] = bbox

    with _gdal_shape_encoding("CP1252"):
        gdf = gpd.read_file(shp_path, **read_kwargs)

    if on_step:
        on_step(f"Leídos {len(gdf):,} features del shapefile INEGI.")

    crs_str = gdf.crs.to_string() if gdf.crs else None

    # ── Simplificar geometrías para reducir almacenamiento ───────────────────
    if on_step:
        on_step("Simplificando geometrías...")

    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.simplify(tolerance=0.0005)

    # ── Preparar features para inserción ─────────────────────────────────────
    if on_step:
        on_step("Preparando features para inserción en DB...")

    features: list[dict] = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        attrs = {
            col: row[col]
            for col in gdf.columns
            if col != "geometry"
        }

        features.append({
            # tipod7: clasificación D7 (AGRICULTURA, BOSQUES, etc.)
            "tipo":          str(row.get("tipod7", "") or "").strip() or None,
            # tipo: detalle (Bosque de pino, etc.)
            "nombre":        str(row.get("tipo", "") or "").strip() or None,
            "atributos_json": _serialize_attrs(attrs),
            "geometria_wkt": geom.wkt,
        })

    # ── Persistir en DB ───────────────────────────────────────────────────────
    if on_step:
        on_step(f"Insertando {len(features):,} features en la base de datos...")

    with open_session(db_path) as session:
        dato = DatoGeologico(
            proyecto_id=proyecto_id,
            carta_id=None,
            capa=CAPA,
            num_features=len(features),
            crs=crs_str,
            ruta_archivo=str(shp_path),
            cargada_en=datetime.utcnow(),
        )
        session.add(dato)
        session.flush()  # obtener dato.id

        inserted = _insert_features_batch(session, dato.id, features)
        dato.num_features = inserted

    if on_step:
        on_step(f"Carga INEGI completada: {inserted:,} features almacenados.")

    return DatoNacionalResult(
        fuente="inegi",
        capa=CAPA,
        n_features=inserted,
        n_ya_existian=0,
        bbox_usado=bbox,
    )


def cargar_sgm(
    db_path: Path,
    data_path: Path,
    tipo: str = "geologia",
    on_step: Optional[Callable[[str], None]] = None,
) -> DatoNacionalResult:
    """
    Carga datos del SGM (GeoInfoMex) desde un shapefile o directorio.

    Si data_path es un directorio, descubre automáticamente los shapefiles
    y selecciona el más adecuado según `tipo`. Recorta al bbox de la imagen activa.

    Args:
        db_path:   Ruta al archivo terraf.db del proyecto.
        data_path: Ruta a un .shp o a un directorio con shapefiles SGM.
        tipo:      Tipo de datos: "geologia", "geofisica", "geoquimica",
                   "inventario_minero". Usado también como sufijo de capa.
        on_step:   Callback opcional para reportar progreso.

    Returns:
        DatoNacionalResult con estadísticas de la carga.

    Raises:
        FileNotFoundError: si data_path no existe o no hay shapefiles.
        RuntimeError:      si no hay proyecto inicializado.
    """
    import geopandas as gpd

    data_path = Path(data_path).resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"Ruta no encontrada: {data_path}")

    CAPA = f"sgm_{tipo}"

    # ── Resolver shapefile a cargar ───────────────────────────────────────────
    if data_path.is_file() and data_path.suffix.lower() == ".shp":
        shp_path = data_path
    elif data_path.is_dir():
        shapefiles = _discover_shapefiles(data_path)
        if not shapefiles:
            raise FileNotFoundError(
                f"No se encontraron shapefiles en el directorio: {data_path}"
            )
        shp_path = _pick_shapefile_for_tipo(shapefiles, tipo)
        if shp_path is None:
            raise FileNotFoundError(
                f"No se pudo seleccionar un shapefile de tipo '{tipo}' en: {data_path}"
            )
        if on_step:
            on_step(f"Shapefile seleccionado: {shp_path.name}")
    else:
        raise FileNotFoundError(
            f"data_path debe ser un .shp o un directorio: {data_path}"
        )

    # ── Verificar proyecto ────────────────────────────────────────────────────
    proyecto_id = _get_proyecto_id(db_path)
    if proyecto_id is None:
        raise RuntimeError("No hay proyecto inicializado en la base de datos.")

    # ── Idempotencia ──────────────────────────────────────────────────────────
    with open_session(db_path) as session:
        existente = (
            session.query(DatoGeologico)
            .filter_by(proyecto_id=proyecto_id, capa=CAPA)
            .first()
        )
        if existente:
            return DatoNacionalResult(
                fuente="sgm",
                capa=CAPA,
                n_features=existente.num_features or 0,
                n_ya_existian=1,
                bbox_usado=None,
            )

    # ── Obtener bbox de la imagen activa ─────────────────────────────────────
    if on_step:
        on_step("Obteniendo bbox de la imagen activa...")

    bbox = _get_image_bbox(db_path)
    if bbox is None and on_step:
        on_step("ADVERTENCIA: No hay imagen activa, cargando datos SGM completos.")

    # ── Leer shapefile ────────────────────────────────────────────────────────
    if on_step:
        on_step(f"Leyendo shapefile SGM: {shp_path.name}...")

    read_kwargs: dict = {}
    if bbox is not None:
        read_kwargs["bbox"] = bbox

    gdf = gpd.read_file(shp_path, **read_kwargs)

    if on_step:
        on_step(f"Leídos {len(gdf):,} features del shapefile SGM.")

    crs_str = gdf.crs.to_string() if gdf.crs else None

    # ── Simplificar geometrías ────────────────────────────────────────────────
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.simplify(tolerance=0.0005)

    # ── Campos tipo/nombre: intentar nombres canónicos SGM ───────────────────
    # SGM no estandariza columnas; intentamos los más comunes.
    _TIPO_CANDIDATES = [
        "DESCRIPCION", "descripcion",
        "TIPO_ROCA",   "tipo_roca",
        "LITOLOGIA",   "litologia",
        "UNIDAD",      "unidad",
        "TIPO",        "tipo",
        "SIMBOLO",     "simbolo",
        "CVE_LITOL",   "cve_litol",
    ]
    _NOMBRE_CANDIDATES = [
        "NOMBRE",      "nombre",
        "ETIQUETA",    "etiqueta",
        "LABEL",       "label",
        "DESCRIPCION", "descripcion",
    ]

    cols = set(gdf.columns)

    def _pick_field(candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in cols:
                return c
        return None

    campo_tipo   = _pick_field(_TIPO_CANDIDATES)
    campo_nombre = _pick_field(_NOMBRE_CANDIDATES)

    # ── Preparar features ─────────────────────────────────────────────────────
    if on_step:
        on_step("Preparando features para inserción en DB...")

    features: list[dict] = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        attrs = {
            col: row[col]
            for col in gdf.columns
            if col != "geometry"
        }

        tipo_val   = str(row[campo_tipo] or "").strip() or None if campo_tipo else None
        nombre_val = str(row[campo_nombre] or "").strip() or None if campo_nombre else None

        features.append({
            "tipo":           tipo_val,
            "nombre":         nombre_val,
            "atributos_json": _serialize_attrs(attrs),
            "geometria_wkt":  geom.wkt,
        })

    # ── Persistir en DB ───────────────────────────────────────────────────────
    if on_step:
        on_step(f"Insertando {len(features):,} features en la base de datos...")

    with open_session(db_path) as session:
        dato = DatoGeologico(
            proyecto_id=proyecto_id,
            carta_id=None,
            capa=CAPA,
            num_features=len(features),
            crs=crs_str,
            ruta_archivo=str(shp_path),
            cargada_en=datetime.utcnow(),
        )
        session.add(dato)
        session.flush()

        inserted = _insert_features_batch(session, dato.id, features)
        dato.num_features = inserted

    if on_step:
        on_step(f"Carga SGM completada: {inserted:,} features almacenados.")

    return DatoNacionalResult(
        fuente="sgm",
        capa=CAPA,
        n_features=inserted,
        n_ya_existian=0,
        bbox_usado=bbox,
    )


def generar_mapa_dato_nacional(
    db_path: Path,
    capa: str,
    out_dir: Optional[Path] = None,
    on_step: Optional[Callable[[str], None]] = None,
) -> Path:
    """
    Genera un mapa Folium interactivo para una capa de datos nacionales.

    Lee los features de la DB (WKT + atributos_json), reconstruye un GeoDataFrame,
    reproyecta a WGS84 y crea un mapa HTML.

    Modo de color:
      - Campos numéricos (RANGO_CODE, etc.): colormap continuo tipo jet.
      - Campos categóricos (tipod7, LITOLOGIA, etc.): colores discretos.

    Raises:
        RuntimeError: si la capa no existe o no tiene features.
    """
    import json as _json
    import geopandas as gpd
    import folium
    import branca.colormap as bcm
    from shapely import wkt as shapely_wkt

    _NOMBRES_CAPA = {
        "inegi_usosue":          "INEGI — Uso de Suelo y Vegetación",
        "sgm_geologia":          "SGM — Geología",
        "sgm_geofisica":         "SGM — Campo Magnético Total",
        "sgm_geoquimica":        "SGM — Geoquímica",
        "sgm_inventario_minero": "SGM — Inventario Minero",
    }

    # ── Leer features de la DB ─────────────────────────────────────────────────
    if on_step:
        on_step(f"Leyendo features de la DB para capa '{capa}'...")

    rows: list[dict] = []
    crs_str: Optional[str] = None
    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        if proyecto is None:
            raise RuntimeError("No hay proyecto inicializado.")

        dato = (
            session.query(DatoGeologico)
            .filter_by(proyecto_id=proyecto.id, capa=capa)
            .first()
        )
        if dato is None:
            raise RuntimeError(
                f"Capa '{capa}' no encontrada. "
                "Ejecuta 'terraf datos --lista' para ver las capas disponibles."
            )

        crs_str = dato.crs
        features = (
            session.query(FeatureGeologico)
            .filter_by(dato_geologico_id=dato.id)
            .all()
        )
        if not features:
            raise RuntimeError(f"La capa '{capa}' no tiene features almacenados.")

        for f in features:
            row: dict = {}
            if f.atributos_json:
                try:
                    row = _json.loads(f.atributos_json)
                except Exception:
                    pass
            row["_tipo"]   = f.tipo
            row["_nombre"] = f.nombre
            row["_wkt"]    = f.geometria_wkt
            rows.append(row)

    if on_step:
        on_step(f"{len(rows):,} features cargados. Reconstruyendo GeoDataFrame...")

    # ── Reconstruir GeoDataFrame ───────────────────────────────────────────────
    geometrias = []
    attrs_list = []
    for row in rows:
        wkt_str = row.pop("_wkt", None)
        if not wkt_str:
            continue
        try:
            geom = shapely_wkt.loads(wkt_str)
        except Exception:
            continue
        geometrias.append(geom)
        attrs_list.append(row)

    gdf = gpd.GeoDataFrame(attrs_list, geometry=geometrias)
    if crs_str:
        try:
            gdf = gdf.set_crs(crs_str)
        except Exception:
            pass

    # ── Reproyectar a WGS84 ───────────────────────────────────────────────────
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        if on_step:
            on_step(f"Reproyectando de {gdf.crs.to_string()} a WGS84...")
        gdf = gdf.to_crs(epsg=4326)
    elif gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)

    # ── Detectar campo de color y modo (numérico vs categórico) ──────────────
    # Campos numéricos tienen prioridad para capas geofísicas
    _NUMERIC_CANDIDATES = ["RANGO_CODE", "VALOR", "INTENSIDAD", "MAG", "GRAVITY"]
    _CATEG_CANDIDATES   = [
        "_tipo", "tipod7", "DESCRIPCION", "LITOLOGIA",
        "UNIDAD", "entidad", "SIMBOLO", "CVE_LITOL",
    ]

    color_field: Optional[str] = None
    is_numeric = False

    # Primero buscar campo numérico (para geofísica es lo correcto)
    for c in _NUMERIC_CANDIDATES:
        if c in gdf.columns and gdf[c].notna().any():
            try:
                gdf[c] = gdf[c].apply(
                    lambda v: float(v) if v not in (None, "None", "") else None
                )
                if gdf[c].notna().any():
                    color_field = c
                    is_numeric = True
                    break
            except Exception:
                pass

    # Si no hay campo numérico, buscar categórico
    if not color_field:
        for c in _CATEG_CANDIDATES:
            if c in gdf.columns and gdf[c].notna().any():
                vals = gdf[c].dropna()
                if len(vals) > 0 and str(vals.iloc[0]) not in ("None", "nan", ""):
                    color_field = c
                    is_numeric = False
                    break

    # ── Calcular centro ────────────────────────────────────────────────────────
    total_bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)
    center_lat = (total_bounds[1] + total_bounds[3]) / 2
    center_lon = (total_bounds[0] + total_bounds[2]) / 2

    if on_step:
        modo = "numérico-jet" if is_numeric else "categórico"
        campo_info = f"'{color_field}'" if color_field else "sin campo de color"
        on_step(f"Modo de color: {modo} — campo {campo_info}")
        on_step("Generando mapa Folium...")

    # ── Construir colormap numérico (jet) ─────────────────────────────────────
    branca_cm: Optional[bcm.LinearColormap] = None
    color_map_cat: dict = {}

    if is_numeric and color_field:
        # Clampar outliers extremos: usar percentiles 2-98 como rango visual
        serie = gdf[color_field].dropna()
        vmin = float(serie.quantile(0.02))
        vmax = float(serie.quantile(0.98))
        if vmin == vmax:
            vmin, vmax = float(serie.min()), float(serie.max())

        # Jet: azul oscuro → cian → verde → amarillo → rojo → rojo oscuro
        jet_colors = [
            "#00007F", "#0000FF", "#007FFF", "#00FFFF",
            "#7FFF7F", "#FFFF00", "#FF7F00", "#FF0000", "#7F0000",
        ]
        branca_cm = bcm.LinearColormap(
            colors=jet_colors,
            vmin=vmin,
            vmax=vmax,
            caption=f"{color_field}  (mín={vmin:.1f} — máx={vmax:.1f})",
        )

        def _get_color_num(val) -> str:
            if val is None or (isinstance(val, float) and val != val):
                return "#808080"
            v = max(vmin, min(vmax, float(val)))
            return branca_cm(v)

    else:
        # Paleta categórica
        _PALETA_CAT = [
            "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
            "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
            "#d37295", "#fabfd2", "#8cd17d", "#b6992d", "#499894",
        ]
        _PRESET_INEGI = {
            "BOSQUES":               "#2d6a4f",
            "MATORRAL":              "#95d5b2",
            "AGRICULTURA":           "#f9c74f",
            "AREA AGRICOLA":         "#f9c74f",
            "PASTIZAL-PRADERA-SABANA": "#b7e4c7",
            "CUERPO DE AGUA":        "#4cc9f0",
            "AREA SIN VEGETACION":   "#e5e5e5",
            "LOCALIDAD":             "#e76f51",
            "SELVA":                 "#1b4332",
        }
        preset = _PRESET_INEGI if capa == "inegi_usosue" else {}
        if color_field:
            for i, v in enumerate(sorted(gdf[color_field].dropna().unique(), key=str)):
                color_map_cat[str(v)] = preset.get(str(v), _PALETA_CAT[i % len(_PALETA_CAT)])

    # ── Mapa base ─────────────────────────────────────────────────────────────
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=10,
        tiles="CartoDB positron",
    )

    titulo = _NOMBRES_CAPA.get(capa, capa)
    m.get_root().html.add_child(folium.Element(
        f'<div style="position:fixed;top:12px;left:60px;z-index:9999;'
        f'background:rgba(255,255,255,0.92);padding:8px 16px;border-radius:6px;'
        f'font-family:sans-serif;font-size:13px;font-weight:bold;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.25);">'
        f'{titulo}<br>'
        f'<span style="font-weight:normal;font-size:11px;color:#666;">'
        f'{len(gdf):,} polígonos</span></div>'
    ))

    # ── Capa GeoJSON ──────────────────────────────────────────────────────────
    popup_cols = [
        c for c in gdf.columns
        if c not in ("geometry", "_wkt", "_nombre")
        and not str(c).startswith("Shape")
    ][:6]

    # Serializar columnas para GeoJSON
    gdf_map = gdf[popup_cols + ["geometry"]].copy()
    for col in popup_cols:
        gdf_map[col] = gdf_map[col].apply(
            lambda v: round(v, 4) if isinstance(v, float) else v
        ).astype(str)

    if is_numeric and color_field:
        def _style_num(feature):
            raw = feature["properties"].get(color_field)
            try:
                val = float(raw) if raw not in (None, "None", "nan") else None
            except (ValueError, TypeError):
                val = None
            return {
                "fillColor":   _get_color_num(val),
                "color":       "none",
                "weight":      0,
                "fillOpacity": 0.85,
            }
        style_fn = _style_num
    else:
        def _style_cat(feature):
            val = feature["properties"].get(color_field) if color_field else None
            color = color_map_cat.get(str(val), "#aaaaaa") if val else "#aaaaaa"
            return {
                "fillColor":   color,
                "color":       "#555555",
                "weight":      0.4,
                "fillOpacity": 0.70,
            }
        style_fn = _style_cat

    tooltip_fields = [c for c in popup_cols if c != "_tipo"][:4]
    folium.GeoJson(
        gdf_map.__geo_interface__,
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_fields,
            localize=True,
            sticky=False,
        ),
    ).add_to(m)

    # ── Leyenda ───────────────────────────────────────────────────────────────
    if branca_cm is not None:
        # Colorbar continua de branca
        branca_cm.add_to(m)
    elif color_map_cat and 1 < len(color_map_cat) <= 20:
        items_html = "".join(
            f'<li style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
            f'<span style="display:inline-block;width:14px;height:14px;'
            f'border-radius:2px;background:{col};flex-shrink:0;"></span>'
            f'<span style="font-size:11px;white-space:nowrap;">{val[:32]}</span></li>'
            for val, col in list(color_map_cat.items())[:20]
        )
        m.get_root().html.add_child(folium.Element(
            f'<div style="position:fixed;bottom:24px;right:12px;z-index:9999;'
            f'background:rgba(255,255,255,0.95);padding:10px 14px;border-radius:6px;'
            f'font-family:sans-serif;max-height:340px;overflow-y:auto;'
            f'box-shadow:0 2px 8px rgba(0,0,0,.25);min-width:160px;">'
            f'<b style="font-size:11px;">{color_field}</b>'
            f'<ul style="list-style:none;padding:0;margin:6px 0 0;">'
            f'{items_html}</ul></div>'
        ))

    # ── Guardar HTML ──────────────────────────────────────────────────────────
    project_dir = db_path.parent
    if out_dir is None:
        out_dir = project_dir / "resultados" / "mapas"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_capa = capa.replace("_", "-")
    html_path = out_dir / f"mapa_{safe_capa}.html"
    m.save(str(html_path))

    if on_step:
        on_step(f"Mapa guardado: {html_path.name}")

    return html_path


def listar_datos(db_path: Path) -> list[dict]:
    """
    Lista todos los datos nacionales registrados en el proyecto actual.

    Returns:
        Lista de dicts con claves: fuente, capa, n_features, ruta_archivo, cargada_en.
    """
    with open_session(db_path) as session:
        proyecto = session.query(Proyecto).first()
        if proyecto is None:
            return []

        capas = (
            session.query(DatoGeologico)
            .filter_by(proyecto_id=proyecto.id)
            .filter(
                DatoGeologico.capa.in_([
                    "inegi_usosue",
                    "sgm_geologia",
                    "sgm_geofisica",
                    "sgm_geoquimica",
                    "sgm_inventario_minero",
                ])
            )
            .order_by(DatoGeologico.cargada_en)
            .all()
        )

        result: list[dict] = []
        for c in capas:
            # Inferir fuente del nombre de capa
            fuente = "INEGI" if c.capa.startswith("inegi") else "SGM"
            result.append({
                "fuente":       fuente,
                "capa":         c.capa,
                "n_features":   c.num_features or 0,
                "ruta_archivo": c.ruta_archivo,
                "cargada_en":   c.cargada_en.strftime("%Y-%m-%d %H:%M") if c.cargada_en else "—",
            })

        return result
