"""
terraf report — Genera un reporte del análisis en terminal o Markdown.
"""

from typing import Optional

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from terraf.cli.art import console, divider, success, error
from terraf.db.session import require_db

app = typer.Typer(help="Genera un reporte del analisis.")

_FORMATOS = ["terminal", "md"]

_PRIORIDAD_STYLE = {
    "ALTA":  "bold green",
    "MEDIA": "bold yellow",
    "BAJA":  "dim",
}


@app.callback(invoke_without_command=True)
def cmd(
    formato: str = typer.Option(
        "terminal", "--formato", "-f",
        help="Formato de salida: terminal, md",
    ),
    analisis_id: Optional[int] = typer.Option(
        None, "--analisis",
        help="ID de analisis especifico (default: ultimo)",
    ),
    top: int = typer.Option(
        5, "--top",
        help="Numero de top targets a mostrar (default: 5)",
    ),
):
    """Muestra un reporte completo del analisis en terminal o lo guarda como Markdown."""
    from terraf.pipeline.reporter import cargar_reporte, generar_markdown, guardar_markdown

    db_path = require_db()

    if formato not in _FORMATOS:
        error(
            f"Formato '{formato}' no valido.\n"
            f"  Opciones: {', '.join(_FORMATOS)}"
        )
        raise typer.Exit(1)

    try:
        data = cargar_reporte(db_path, analisis_id=analisis_id)
    except RuntimeError as exc:
        error(str(exc))
        raise typer.Exit(1)

    # ── Markdown ──────────────────────────────────────────────────────────────
    if formato == "md":
        out_path = guardar_markdown(data, db_path)
        success(f"Reporte guardado: [bold]{out_path}[/bold]")
        console.print()
        raise typer.Exit(0)

    # ── Terminal ──────────────────────────────────────────────────────────────
    console.print()

    # Encabezado tipo panel
    header = Text(justify="center")
    header.append(f"REPORTE DE EXPLORACIÓN — {data.proyecto_nombre.upper()}\n", style="bold green")
    header.append(
        f"Imagen: {data.scene_id}  ·  Fecha: {data.fecha_analisis}  ·  Método: {data.metodo}",
        style="dim",
    )
    console.print(Panel(header, border_style="green", padding=(0, 2)))
    console.print()

    # ── Resumen ────────────────────────────────────────────────────────────────
    console.print("  [bold]Resumen[/bold]")
    console.print()
    resumen = Table.grid(padding=(0, 4))
    resumen.add_column(style="muted", justify="right")
    resumen.add_column()
    resumen.add_row("Targets identificados:", f"[accent]{len(data.targets)}[/accent]")
    resumen.add_row(
        "Prioridad:",
        f"[bold green]ALTA {data.n_alta}[/bold green]  "
        f"[bold yellow]MEDIA {data.n_media}[/bold yellow]  "
        f"[dim]BAJA {data.n_baja}[/dim]",
    )
    resumen.add_row("Área total de interés:", f"[accent]{data.area_total_ha:.2f} ha[/accent]")
    if data.crs:
        resumen.add_row("CRS:", f"[muted]{data.crs}[/muted]")
    if data.duracion_seg is not None:
        resumen.add_row("Tiempo de análisis:", f"[muted]{data.duracion_seg:.1f} s[/muted]")
    console.print(resumen)
    console.print()
    divider()
    console.print()

    # ── Índices espectrales ────────────────────────────────────────────────────
    if data.indices:
        console.print("  [bold]Índices Espectrales[/bold]")
        console.print()
        t_idx = Table(
            show_header=True, header_style="bold",
            border_style="dim", box=box.SIMPLE_HEAD,
        )
        t_idx.add_column("Índice",         style="accent", min_width=20)
        t_idx.add_column("Media",          justify="right", min_width=7)
        t_idx.add_column("Std",            justify="right", min_width=7)
        t_idx.add_column("% > umbral",     justify="right", min_width=10)
        t_idx.add_column("Umbral",         justify="right", min_width=8)

        for idx in data.indices:
            t_idx.add_row(
                idx.nombre,
                _f(idx.media),
                _f(idx.desv_std),
                _fp(idx.pct_sobre_umbral),
                _f(idx.umbral),
            )
        console.print(t_idx)
        console.print()
        divider()
        console.print()

    # ── Top targets ────────────────────────────────────────────────────────────
    if data.targets:
        n_show = min(top, len(data.targets))
        console.print(f"  [bold]Top {n_show} Targets[/bold]")
        console.print()

        t_tgt = Table(
            show_header=True, header_style="bold",
            border_style="dim", box=box.SIMPLE_HEAD,
        )
        t_tgt.add_column("#",          justify="center", min_width=5)
        t_tgt.add_column("Ubicacion",  justify="right",  min_width=26)
        t_tgt.add_column("Area (ha)",  justify="right",  min_width=10)
        t_tgt.add_column("Score",      justify="right",  min_width=7)
        t_tgt.add_column("IOR med.",   justify="right",  min_width=9)
        t_tgt.add_column("Prioridad",  justify="center", min_width=10)

        for t in data.targets[:n_show]:
            ubi = (
                f"{t.lon:.4f}, {t.lat:.4f}"
                if t.lon is not None else f"{t.coord_x:.0f}, {t.coord_y:.0f}"
            )
            pstyle = _PRIORIDAD_STYLE.get(t.prioridad, "")
            t_tgt.add_row(
                t.nombre, ubi,
                f"{t.area_ha:.2f}", f"{t.score:.3f}",
                _f(t.ior_media),
                f"[{pstyle}]{t.prioridad}[/{pstyle}]",
            )

        if len(data.targets) > n_show:
            omitidos = len(data.targets) - n_show
            t_tgt.add_row("...", f"[muted]({omitidos} mas)[/muted]", "...", "...", "...", "...")

        console.print(t_tgt)
        console.print()
        divider()
        console.print()

    # ── Datos geológicos ───────────────────────────────────────────────────────
    if data.n_capas_geo:
        console.print("  [bold]Datos Geológicos[/bold]")
        console.print()
        geo = Table.grid(padding=(0, 4))
        geo.add_column(style="muted", justify="right")
        geo.add_column()
        geo.add_row("Capas cargadas:", f"[accent]{data.n_capas_geo}[/accent]")
        if data.capas_geo:
            geo.add_row("Tipos:", f"[muted]{', '.join(data.capas_geo)}[/muted]")
        console.print(geo)
        console.print()
        divider()
        console.print()

    # ── Hint exportación ───────────────────────────────────────────────────────
    console.print(
        "  [muted]Para exportar a GeoJSON/Shapefile:[/muted]  "
        "[accent]terraf export[/accent]\n"
        "  [muted]Para guardar este reporte:[/muted]  "
        "[accent]terraf report --formato md[/accent]"
    )
    console.print()


# ── Helpers de formato ────────────────────────────────────────────────────────

def _f(val) -> str:
    return f"{val:.3f}" if val is not None else "—"

def _fp(val) -> str:
    return f"{val:.1f}%" if val is not None else "—"
