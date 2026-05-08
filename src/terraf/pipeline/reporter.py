"""
Pipeline — Fase 4b: Generación de reporte de resultados.

Reúne datos de la DB (proyecto, imagen, índices, targets, geología) y
los expone como `ReporteData` para que la CLI los renderice en terminal
o los guarde como Markdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from terraf.db.models import Analisis, DatoGeologico, Imagen, IndiceEspectral, Proyecto, Target
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IndiceResumen:
    clave: str
    nombre: str
    media: Optional[float]
    desv_std: Optional[float]
    pct_sobre_umbral: Optional[float]
    umbral: Optional[float]


@dataclass
class TargetResumen:
    nombre: str
    coord_x: float
    coord_y: float
    lon: Optional[float]
    lat: Optional[float]
    area_ha: float
    score: float
    prioridad: str
    ior_media: Optional[float]
    clay_media: Optional[float]


@dataclass
class ReporteData:
    # Encabezado
    proyecto_nombre: str
    scene_id: str
    fecha_analisis: str
    metodo: str
    crs: Optional[str]
    duracion_seg: Optional[float]

    # Índices
    indices: list[IndiceResumen] = field(default_factory=list)

    # Targets
    targets: list[TargetResumen] = field(default_factory=list)
    n_alta: int = 0
    n_media: int = 0
    n_baja: int = 0
    area_total_ha: float = 0.0

    # Geología
    n_capas_geo: int = 0
    capas_geo: list[str] = field(default_factory=list)


# Nombres legibles de índices
_NOMBRES_INDICE = {
    "ior":     "Iron Oxide Ratio",
    "clay":    "Clay Ratio",
    "ferrous": "Ferrous Minerals",
    "ndvi":    "NDVI",
    "ndwi":    "NDWI",
    "evi":     "EVI",
    "savi":    "SAVI",
}


# ──────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ──────────────────────────────────────────────────────────────────────────────

def cargar_reporte(
    db_path: Path,
    analisis_id: Optional[int] = None,
) -> ReporteData:
    """
    Reúne todos los datos necesarios para el reporte desde la DB.

    Args:
        db_path:     Ruta al archivo terraf.db.
        analisis_id: ID de análisis específico (default: último).

    Raises:
        RuntimeError: Si no hay análisis en la DB.
    """
    with open_session(db_path) as session:
        # Análisis
        query = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            query = query.filter_by(id=analisis_id)
        analisis = query.first()

        if analisis is None:
            raise RuntimeError(
                "No hay análisis registrado.\nEjecuta 'terraf analyze' primero."
            )

        imagen   = session.query(Imagen).filter_by(id=analisis.imagen_id).first()
        proyecto = session.query(Proyecto).first()

        # Índices
        indices_db = (
            session.query(IndiceEspectral)
            .filter_by(imagen_id=analisis.imagen_id)
            .all()
        )

        # Targets
        targets_db = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .order_by(Target.score.desc())
            .all()
        )

        # Geología
        capas_db = (
            session.query(DatoGeologico)
            .filter_by(proyecto_id=proyecto.id if proyecto else 0)
            .all()
        )

    fecha = (
        analisis.ejecutado_en.strftime("%Y-%m-%d %H:%M")
        if analisis.ejecutado_en else datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    indices = [
        IndiceResumen(
            clave=idx.nombre_indice,
            nombre=_NOMBRES_INDICE.get(idx.nombre_indice, idx.nombre_indice),
            media=idx.media,
            desv_std=idx.desv_std,
            pct_sobre_umbral=idx.pct_sobre_umbral,
            umbral=idx.umbral,
        )
        for idx in indices_db
    ]

    targets = [
        TargetResumen(
            nombre=t.nombre,
            coord_x=t.centroide_x or 0.0,
            coord_y=t.centroide_y or 0.0,
            lon=t.centroide_lon,
            lat=t.centroide_lat,
            area_ha=t.area_ha or 0.0,
            score=t.score or 0.0,
            prioridad=t.prioridad or "—",
            ior_media=t.ior_media,
            clay_media=t.clay_media,
        )
        for t in targets_db
    ]

    return ReporteData(
        proyecto_nombre=proyecto.nombre if proyecto else "—",
        scene_id=imagen.scene_id if imagen else "—",
        fecha_analisis=fecha,
        metodo=analisis.metodo or "—",
        crs=imagen.crs if imagen else None,
        duracion_seg=analisis.duracion_seg,
        indices=indices,
        targets=targets,
        n_alta=sum(1 for t in targets if t.prioridad == "ALTA"),
        n_media=sum(1 for t in targets if t.prioridad == "MEDIA"),
        n_baja=sum(1 for t in targets if t.prioridad == "BAJA"),
        area_total_ha=round(sum(t.area_ha for t in targets), 2),
        n_capas_geo=len(capas_db),
        capas_geo=[c.capa for c in capas_db],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Generador Markdown
# ──────────────────────────────────────────────────────────────────────────────

def generar_markdown(data: ReporteData) -> str:
    """Genera el texto del reporte en formato Markdown."""
    lines: list[str] = []

    lines += [
        f"# Reporte de Exploración — {data.proyecto_nombre}",
        "",
        f"**Fecha:** {data.fecha_analisis}  ",
        f"**Imagen:** `{data.scene_id}`  ",
        f"**Método:** {data.metodo}  ",
        f"**CRS:** {data.crs or 'desconocido'}  ",
        "",
        "---",
        "",
        "## Resumen",
        "",
        f"| Targets totales | Prioridad ALTA | MEDIA | BAJA | Área total |",
        f"|----------------|---------------|-------|------|------------|",
        f"| {len(data.targets)} | {data.n_alta} | {data.n_media} | {data.n_baja} | {data.area_total_ha:.2f} ha |",
        "",
    ]

    # Índices
    if data.indices:
        lines += [
            "## Índices Espectrales",
            "",
            "| Índice | Media | Std | % > Umbral | Umbral |",
            "|--------|-------|-----|------------|--------|",
        ]
        for idx in data.indices:
            media = f"{idx.media:.3f}" if idx.media is not None else "—"
            std   = f"{idx.desv_std:.3f}" if idx.desv_std is not None else "—"
            pct   = f"{idx.pct_sobre_umbral:.1f}%" if idx.pct_sobre_umbral is not None else "—"
            umb   = f"{idx.umbral:.2f}" if idx.umbral is not None else "—"
            lines.append(f"| {idx.nombre} | {media} | {std} | {pct} | {umb} |")
        lines.append("")

    # Targets
    if data.targets:
        lines += [
            "## Targets Identificados",
            "",
            "| # | Ubicación | Área (ha) | Score | IOR med. | Prioridad |",
            "|---|-----------|-----------|-------|----------|-----------|",
        ]
        for t in data.targets:
            ubi = (
                f"{t.lon:.4f}°, {t.lat:.4f}°"
                if t.lon is not None else f"{t.coord_x:.0f}, {t.coord_y:.0f}"
            )
            ior = f"{t.ior_media:.3f}" if t.ior_media is not None else "—"
            lines.append(
                f"| {t.nombre} | {ubi} | {t.area_ha:.2f} | {t.score:.3f} | {ior} | **{t.prioridad}** |"
            )
        lines.append("")

    # Geología
    if data.n_capas_geo:
        lines += [
            "## Datos Geológicos",
            "",
            f"- **Capas cargadas:** {data.n_capas_geo}",
        ]
        for c in data.capas_geo:
            lines.append(f"  - {c}")
        lines.append("")

    lines += [
        "---",
        "",
        "_Generado por TerraF — Exploración minera desde la terminal_",
    ]

    return "\n".join(lines)


def guardar_markdown(data: ReporteData, db_path: Path) -> Path:
    """Guarda el reporte Markdown en resultados/reportes/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = db_path.parent / "resultados" / "reportes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"reporte_{ts}.md"
    out_path.write_text(generar_markdown(data), encoding="utf-8")
    return out_path
