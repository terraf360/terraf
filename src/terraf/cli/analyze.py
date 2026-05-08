"""
terraf analyze — Detección de targets de exploración.
"""

from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, next_step, success, error
from terraf.db.session import require_db

app = typer.Typer(help="Detecta targets de exploracion minera.")

_METODOS = ["logico", "estadistico", "ambos"]

_PRIORIDAD_STYLE = {
    "ALTA":  "bold green",
    "MEDIA": "bold yellow",
    "BAJA":  "dim",
}


@app.callback(invoke_without_command=True)
def cmd(
    metodo: str = typer.Option(
        "logico",
        "--metodo", "-m",
        help="Metodo de deteccion: logico, estadistico, ambos",
    ),
    umbral_ior: Optional[float] = typer.Option(
        None, "--umbral-ior",
        help="Umbral IOR (usa el guardado en DB si no se indica)",
    ),
    umbral_clay: Optional[float] = typer.Option(
        None, "--umbral-clay",
        help="Umbral Clay (usa el guardado en DB si no se indica)",
    ),
    min_area: int = typer.Option(
        10, "--min-area",
        help="Area minima de cluster en pixeles (default: 10)",
    ),
    mapa: bool = typer.Option(
        False, "--mapa",
        help="Genera un mapa HTML interactivo y lo abre en el navegador",
    ),
):
    """Analiza indices espectrales para detectar zonas de interes minero."""
    from terraf.pipeline.analyze import ejecutar_analisis

    db_path = require_db()

    if metodo not in _METODOS:
        error(
            f"Metodo '{metodo}' no reconocido.\n"
            f"  Opciones: {', '.join(_METODOS)}"
        )
        raise typer.Exit(1)

    console.print()

    # ── Pasos de análisis con feedback ───────────────────────────────────────
    pasos = [
        "Cargando indices espectrales desde DB",
        "Aplicando filtro espectral",
        "Aplicando filtro geologico",
        "Identificando y clasificando targets",
    ]
    paso_actual = {"n": 0}

    def _on_step(desc: str) -> None:
        n = paso_actual["n"] + 1
        paso_actual["n"] = n
        console.print(f"  [muted][{n}/{len(pasos)}][/muted] {desc}...")

    try:
        resultado = ejecutar_analisis(
            db_path=db_path,
            metodo=metodo,
            umbral_ior=umbral_ior,
            umbral_clay=umbral_clay,
            min_area_px=min_area,
            on_step=_on_step,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        error(str(exc))
        raise typer.Exit(1)

    console.print()

    # ── Sin targets ───────────────────────────────────────────────────────────
    if resultado.num_targets == 0:
        console.print(
            f"  {SYM['warn']}  No se encontraron targets con los parametros actuales.\n"
            "  Prueba reduciendo [accent]--umbral-ior[/accent] o "
            "[accent]--min-area[/accent]."
        )
        console.print()
        raise typer.Exit(0)

    # ── Encabezado ─────────────────────────────────────────────────────────────
    success(
        f"{resultado.num_targets} target(s) identificados  "
        f"[muted]({resultado.duracion_seg:.1f} s)[/muted]"
    )
    console.print()
    divider()
    console.print()

    # ── Tabla de targets ──────────────────────────────────────────────────────
    tabla = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    tabla.add_column("#",          justify="center", min_width=5)
    tabla.add_column("Ubicacion",  justify="right",  min_width=26)
    tabla.add_column("Area (ha)",  justify="right",  min_width=10)
    tabla.add_column("Score",      justify="right",  min_width=7)
    tabla.add_column("IOR med.",   justify="right",  min_width=9)
    tabla.add_column("Prioridad",  justify="center", min_width=10)

    # Mostrar hasta 20 targets; el resto se resume
    mostrar = resultado.targets[:20]
    for t in mostrar:
        ubi = _fmt_ubicacion(t)
        prio_style = _PRIORIDAD_STYLE.get(t.prioridad, "")
        tabla.add_row(
            t.nombre,
            ubi,
            f"{t.area_ha:.2f}",
            f"{t.score:.3f}",
            f"{t.ior_media:.3f}" if t.ior_media else "—",
            f"[{prio_style}]{t.prioridad}[/{prio_style}]",
        )

    if len(resultado.targets) > 20:
        omitidos = len(resultado.targets) - 20
        tabla.add_row(
            "...", f"[muted]({omitidos} mas)[/muted]", "...", "...", "...", "..."
        )

    console.print(tabla)

    # ── Resumen de prioridades ────────────────────────────────────────────────
    console.print()
    alta  = sum(1 for t in resultado.targets if t.prioridad == "ALTA")
    media = sum(1 for t in resultado.targets if t.prioridad == "MEDIA")
    baja  = sum(1 for t in resultado.targets if t.prioridad == "BAJA")

    console.print(
        f"  [muted]Prioridad:[/muted]  "
        f"[bold green]ALTA {alta}[/bold green]  "
        f"[bold yellow]MEDIA {media}[/bold yellow]  "
        f"[dim]BAJA {baja}[/dim]"
    )
    console.print()
    divider()
    next_step("terraf report", extra="o: terraf export  para exportar a GeoJSON/Shapefile")

    # ── Mapa opcional ─────────────────────────────────────────────────────────
    if mapa:
        _generar_mapa(db_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generar_mapa(db_path) -> None:
    from terraf.pipeline.mapper import mapa_analisis
    try:
        ruta = mapa_analisis(db_path, abrir=True)
        console.print(
            f"\n  [muted]Mapa generado:[/muted]  [accent]{ruta}[/accent]\n"
        )
    except ImportError as exc:
        console.print(f"\n  [yellow]Mapa omitido:[/yellow] {exc}\n")
    except Exception as exc:
        console.print(f"\n  [yellow]No se pudo generar el mapa:[/yellow] {exc}\n")


def _fmt_ubicacion(t) -> str:
    """Formatea la ubicacion: lon/lat si disponible, coordenadas proyectadas si no."""
    if t.centroide_lon is not None and t.centroide_lat is not None:
        return f"{t.centroide_lon:.4f}, {t.centroide_lat:.4f}"
    return f"{t.centroide_x:.0f}, {t.centroide_y:.0f}"
