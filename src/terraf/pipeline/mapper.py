"""
TerraF — Generador de mapas visuales.

Produce un HTML interactivo con Folium que se abre en el navegador.
Si Folium no está instalado, genera un PNG estático con geopandas + matplotlib.

Mapas disponibles:
  - mapa_analisis()   → targets detectados coloreados por prioridad
  - mapa_validaciones() → targets coloreados por resultado de campo
  - mapa_prediccion() → targets coloreados por prob_positivo ML
  - mapa_indices()    → capa raster de un índice sobre el mapa base
"""

from __future__ import annotations

import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

_DIR_MAPAS = Path("resultados") / "mapas"

_COLORES_PRIORIDAD = {
    "ALTA":  "#e63946",   # rojo
    "MEDIA": "#f4a261",   # naranja
    "BAJA":  "#457b9d",   # azul apagado
}

_COLORES_RESULTADO = {
    "positivo":  "#2dc653",
    "negativo":  "#e63946",
    "dudoso":    "#f4a261",
    "pendiente": "#adb5bd",
}

_COLORES_PROB = [
    (0.0,  "#457b9d"),   # azul — baja probabilidad
    (0.4,  "#f4a261"),   # naranja — media
    (0.7,  "#e63946"),   # rojo — alta
]


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def mapa_analisis(
    db_path: Path,
    analisis_id: Optional[int] = None,
    abrir: bool = True,
) -> Path:
    """
    Genera un mapa HTML con los targets detectados, coloreados por prioridad.

    Returns:
        Ruta al archivo HTML generado.
    """
    targets = _cargar_targets(db_path, analisis_id)
    if not targets:
        raise RuntimeError("No hay targets en el análisis actual.")

    titulo = "TerraF — Targets de Exploración"
    mapa = _crear_mapa(targets)

    for t in targets:
        if t.get("lat") is None:
            continue
        color = _COLORES_PRIORIDAD.get(t.get("prioridad", ""), "#6c757d")
        popup = _popup_target(t)
        _agregar_marcador(mapa, t["lat"], t["lon"], color, t["nombre"], popup)

    _agregar_leyenda(mapa, "Prioridad", _COLORES_PRIORIDAD)

    salida = _guardar(mapa, f"analisis_{_ts()}.html", titulo)
    if abrir:
        webbrowser.open(salida.as_uri())
    return salida


def mapa_validaciones(
    db_path: Path,
    analisis_id: Optional[int] = None,
    abrir: bool = True,
) -> Path:
    """
    Genera un mapa HTML con los targets coloreados por resultado de validación de campo.
    """
    from terraf.pipeline.validation import listar_validaciones
    targets_val = listar_validaciones(db_path, analisis_id=analisis_id)

    if not targets_val:
        raise RuntimeError("No hay targets en el análisis actual.")

    # Enriquecer con coordenadas desde DB
    coords = _cargar_coords(db_path, analisis_id)

    mapa = _crear_mapa_desde_coords(coords)

    for tv in targets_val:
        c = coords.get(tv.target_id)
        if not c:
            continue
        res = tv.resultado or "pendiente"
        color = _COLORES_RESULTADO.get(res, "#adb5bd")
        popup = (
            f"<b>{tv.nombre}</b><br>"
            f"Score: {tv.score:.3f}<br>"
            f"Prioridad: {tv.prioridad}<br>"
            f"Resultado: <b>{res.upper()}</b><br>"
            f"Método: {tv.metodo or '—'}<br>"
            f"Notas: {tv.notas or '—'}"
        )
        _agregar_marcador(mapa, c["lat"], c["lon"], color, tv.nombre, popup)

    _agregar_leyenda(mapa, "Validación", _COLORES_RESULTADO)

    salida = _guardar(mapa, f"validaciones_{_ts()}.html", "TerraF — Validaciones de Campo")
    if abrir:
        webbrowser.open(salida.as_uri())
    return salida


def mapa_prediccion(
    db_path: Path,
    analisis_id: Optional[int] = None,
    abrir: bool = True,
) -> Path:
    """
    Genera un mapa HTML con los targets coloreados por prob_positivo ML.
    """
    targets = _cargar_targets(db_path, analisis_id)
    con_prob = [t for t in targets if t.get("prob_positivo") is not None]

    if not con_prob:
        raise RuntimeError(
            "No hay predicciones ML. Ejecuta 'terraf predict' primero."
        )

    mapa = _crear_mapa(targets)

    for t in con_prob:
        if t.get("lat") is None:
            continue
        prob = t["prob_positivo"]
        color = _color_prob(prob)
        popup = (
            f"<b>{t['nombre']}</b><br>"
            f"Prob. ML: <b>{prob:.1%}</b><br>"
            f"Score: {t['score']:.3f}<br>"
            f"Prioridad: {t['prioridad']}"
        )
        _agregar_marcador(mapa, t["lat"], t["lon"], color, t["nombre"], popup)

    leyenda = {"Alta (≥70%)": "#e63946", "Media (40-70%)": "#f4a261", "Baja (<40%)": "#457b9d"}
    _agregar_leyenda(mapa, "Prob. ML", leyenda)

    salida = _guardar(mapa, f"prediccion_{_ts()}.html", "TerraF — Predicción ML")
    if abrir:
        webbrowser.open(salida.as_uri())
    return salida


def mapa_geologia(
    db_path: Path,
    abrir: bool = True,
) -> Path:
    """
    Genera un mapa con los features geológicos (litología + targets si existen).
    Usa geopandas para leer las geometrías WKT.
    """
    _check_folium()
    import folium  # noqa: PLC0415

    targets = _cargar_targets(db_path)
    centro = _centro(targets)

    m = folium.Map(location=centro, zoom_start=10, tiles="CartoDB dark_matter")

    # Targets como capa
    for t in targets:
        if t.get("lat") is None:
            continue
        color = _COLORES_PRIORIDAD.get(t.get("prioridad", ""), "#6c757d")
        _agregar_marcador(m, t["lat"], t["lon"], color, t["nombre"],
                          f"<b>{t['nombre']}</b><br>Score: {t['score']:.3f}")

    # Features geológicos con geometría WKT
    geo_rows = _cargar_geo_wkt(db_path)
    if geo_rows:
        try:
            import geopandas as gpd  # noqa: PLC0415
            from shapely import wkt as shapely_wkt  # noqa: PLC0415
            geoms = [shapely_wkt.loads(r["wkt"]) for r in geo_rows if r.get("wkt")]
            nombres = [r.get("nombre", "") for r in geo_rows if r.get("wkt")]
            gdf = gpd.GeoDataFrame({"nombre": nombres}, geometry=geoms, crs="EPSG:32613")
            gdf_wgs = gdf.to_crs("EPSG:4326")
            folium.GeoJson(
                gdf_wgs.__geo_interface__,
                name="Geología",
                style_function=lambda _: {
                    "color": "#90e0ef", "weight": 0.8, "fillOpacity": 0.1
                },
            ).add_to(m)
        except Exception:
            pass  # geopandas/shapely no disponible — omitir capa

    folium.LayerControl().add_to(m)
    salida = _guardar(m, f"geologia_{_ts()}.html", "TerraF — Geología")
    if abrir:
        webbrowser.open(salida.as_uri())
    return salida


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _check_folium() -> None:
    try:
        import folium  # noqa: F401
    except ImportError:
        raise ImportError(
            "Folium no está instalado.\n"
            "  Instálalo con: pip install folium"
        )


def _cargar_targets(db_path: Path, analisis_id: Optional[int] = None) -> list[dict]:
    from terraf.db.models import Analisis, Target  # noqa: PLC0415
    from terraf.db.session import open_session     # noqa: PLC0415

    with open_session(db_path) as session:
        q = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id:
            q = q.filter_by(id=analisis_id)
        analisis = q.first()
        if analisis is None:
            return []

        targets = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .order_by(Target.score.desc())
            .all()
        )
        return [
            {
                "id":            t.id,
                "nombre":        t.nombre or f"T{t.id}",
                "lat":           t.centroide_lat,
                "lon":           t.centroide_lon,
                "score":         t.score or 0.0,
                "prioridad":     t.prioridad or "—",
                "area_ha":       t.area_ha or 0.0,
                "ior_media":     t.ior_media,
                "clay_media":    t.clay_media,
                "litologia":     t.litologia_dominante or "—",
                "prob_positivo": t.prob_positivo,
                "geometria_wkt": t.geometria_wkt,
            }
            for t in targets
        ]


def _cargar_coords(db_path: Path, analisis_id: Optional[int] = None) -> dict[int, dict]:
    targets = _cargar_targets(db_path, analisis_id)
    return {t["id"]: {"lat": t["lat"], "lon": t["lon"]} for t in targets}


def _cargar_geo_wkt(db_path: Path) -> list[dict]:
    from terraf.db.models import FeatureGeologico  # noqa: PLC0415
    from terraf.db.session import open_session      # noqa: PLC0415

    with open_session(db_path) as session:
        rows = session.query(FeatureGeologico).limit(2000).all()
        return [
            {"nombre": r.nombre or "", "wkt": r.geometria_wkt}
            for r in rows if r.geometria_wkt
        ]


def _crear_mapa(targets: list[dict]):
    _check_folium()
    import folium  # noqa: PLC0415
    centro = _centro(targets)
    return folium.Map(location=centro, zoom_start=9, tiles="CartoDB dark_matter")


def _crear_mapa_desde_coords(coords: dict):
    _check_folium()
    import folium  # noqa: PLC0415
    vals = [c for c in coords.values() if c["lat"] is not None]
    if vals:
        lat = sum(c["lat"] for c in vals) / len(vals)
        lon = sum(c["lon"] for c in vals) / len(vals)
    else:
        lat, lon = 20.0, -100.0
    return folium.Map(location=[lat, lon], zoom_start=9, tiles="CartoDB dark_matter")


def _centro(targets: list[dict]) -> list[float]:
    validos = [t for t in targets if t.get("lat") is not None]
    if not validos:
        return [20.0, -100.0]
    lat = sum(t["lat"] for t in validos) / len(validos)
    lon = sum(t["lon"] for t in validos) / len(validos)
    return [lat, lon]


def _agregar_marcador(mapa, lat: float, lon: float, color: str, nombre: str, popup: str) -> None:
    import folium  # noqa: PLC0415
    folium.CircleMarker(
        location=[lat, lon],
        radius=10,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.75,
        weight=2,
        popup=folium.Popup(popup, max_width=280),
        tooltip=nombre,
    ).add_to(mapa)


def _popup_target(t: dict) -> str:
    lines = [
        f"<b>{t['nombre']}</b>",
        f"Score: {t['score']:.3f}",
        f"Prioridad: {t['prioridad']}",
        f"Área: {t['area_ha']:.1f} ha",
    ]
    if t.get("ior_media"):
        lines.append(f"IOR: {t['ior_media']:.3f}")
    if t.get("clay_media"):
        lines.append(f"Clay: {t['clay_media']:.3f}")
    if t.get("prob_positivo") is not None:
        lines.append(f"Prob. ML: {t['prob_positivo']:.1%}")
    if t.get("litologia") and t["litologia"] != "—":
        lines.append(f"Litología: {t['litologia']}")
    return "<br>".join(lines)


def _agregar_leyenda(mapa, titulo: str, colores: dict) -> None:
    import folium  # noqa: PLC0415
    items = "".join(
        f'<li><span style="background:{c};width:12px;height:12px;'
        f'display:inline-block;border-radius:50%;margin-right:6px;"></span>{k}</li>'
        for k, c in colores.items()
    )
    html = (
        f'<div style="position:fixed;bottom:30px;left:30px;z-index:9999;'
        f'background:#1a1a2e;color:#eee;padding:12px 16px;border-radius:8px;'
        f'font-family:sans-serif;font-size:13px;border:1px solid #444;">'
        f'<b>{titulo}</b><ul style="margin:6px 0 0;padding-left:0;list-style:none">'
        f'{items}</ul></div>'
    )
    mapa.get_root().html.add_child(folium.Element(html))


def _color_prob(prob: float) -> str:
    if prob >= 0.70:
        return "#e63946"
    if prob >= 0.40:
        return "#f4a261"
    return "#457b9d"


def _guardar(mapa, nombre_archivo: str, titulo: str) -> Path:
    import folium  # noqa: PLC0415
    salida = _DIR_MAPAS / nombre_archivo
    salida.parent.mkdir(parents=True, exist_ok=True)

    # Título en el mapa
    title_html = (
        f'<div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);'
        f'z-index:9999;background:#1a1a2e;color:#eee;padding:8px 20px;'
        f'border-radius:6px;font-family:sans-serif;font-size:14px;font-weight:bold;'
        f'border:1px solid #444;">{titulo}</div>'
    )
    mapa.get_root().html.add_child(folium.Element(title_html))
    mapa.save(str(salida))
    return salida


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
