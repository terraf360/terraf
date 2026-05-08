"""
terraf indices — Calcula índices espectrales sobre la imagen cargada.
"""

from typing import Optional

import typer
from rich import box
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from terraf.cli.art import SYM, console, divider, next_step, success, warning, error
from terraf.db.session import require_db
from terraf.pipeline.indices import INDICES_DISPONIBLES

app = typer.Typer(help="Calcula indices espectrales sobre la imagen cargada.")


@app.callback(invoke_without_command=True)
def cmd(
    indice: Optional[str] = typer.Option(
        None,
        "--indice", "-i",
        help=(
            "Índice específico a calcular: "
            "ior, clay, ferrous, ndvi, ndwi, evi, savi. "
            "Se pueden separar por coma. Default: todos."
        ),
    ),
    umbral_ior: Optional[float] = typer.Option(
        None, "--umbral-ior",  help="Umbral para IOR  (default: 0.65)"
    ),
    umbral_clay: Optional[float] = typer.Option(
        None, "--umbral-clay", help="Umbral para Clay (default: 0.55)"
    ),
    sin_rasters: bool = typer.Option(
        False, "--sin-rasters", help="No guardar GeoTIFF de cada índice"
    ),
    forzar: bool = typer.Option(
        False, "--force", "-f", help="Recalcular aunque ya existan en DB"
    ),
):
    """Calcula indices espectrales y almacena estadisticas en la base de datos."""
    from terraf.pipeline.indices import calcular_indices

    db_path = require_db()

    # ── Parsear lista de índices ──────────────────────────────────────────────
    claves: Optional[list[str]] = None
    if indice:
        claves = [i.strip().lower() for i in indice.split(",")]
        invalidos = [c for c in claves if c not in INDICES_DISPONIBLES]
        if invalidos:
            error(
                f"Índices no reconocidos: {', '.join(invalidos)}\n"
                f"  Disponibles: {', '.join(INDICES_DISPONIBLES)}"
            )
            raise typer.Exit(1)

    # ── Umbrales personalizados ───────────────────────────────────────────────
    umbrales: dict[str, float] = {}
    if umbral_ior  is not None:
        umbrales["ior"]  = umbral_ior
    if umbral_clay is not None:
        umbrales["clay"] = umbral_clay

    claves_plan = claves or INDICES_DISPONIBLES
    n_total = len(claves_plan)

    console.print()

    # ── Barra de progreso ─────────────────────────────────────────────────────
    progreso: list[str] = []

    def _on_index(clave: str) -> None:
        progreso.append(clave)
        progress.advance(task)
        progress.update(task, description=f"  [muted]Calculando[/muted] [accent]{clave}[/accent]…")

    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("{task.description}"),
        BarColumn(bar_width=30, style="accent", complete_style="ok"),
        TextColumn("[muted]{task.completed}/{task.total}[/muted]"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            f"  [muted]Iniciando cálculo…[/muted]",
            total=n_total,
        )

        try:
            resultado = calcular_indices(
                db_path=db_path,
                claves=claves,
                umbrales=umbrales,
                guardar_rasters=not sin_rasters,
                forzar=forzar,
                on_index=_on_index,
            )
        except (RuntimeError, FileNotFoundError) as exc:
            progress.stop()
            error(str(exc))
            raise typer.Exit(1)

        # Avanzar los que ya existían (on_index no se llama para ellos)
        ya_existian = sum(1 for i in resultado.indices if i.already_existed)
        progress.advance(task, ya_existian)
        progress.update(task, description="  [ok]Completado[/ok]")

    console.print()

    # ── Advertir si todo ya existía ───────────────────────────────────────────
    if all(i.already_existed for i in resultado.indices):
        warning("Todos los índices ya estaban calculados para esta imagen.")
        console.print(
            f"    {SYM['arrow']} Usa [accent]--force[/accent] para recalcular, "
            "o [accent]terraf analyze[/accent] para continuar."
        )
        console.print()
        raise typer.Exit(0)

    # ── Encabezado de éxito ───────────────────────────────────────────────────
    n_ok = len(resultado.ok)
    success(
        f"{n_ok} índice(s) calculado(s) para [bold]{resultado.scene_id}[/bold]"
    )
    console.print()
    divider()
    console.print()

    # ── Tabla de estadísticas ─────────────────────────────────────────────────
    tabla = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    tabla.add_column("Índice",    style="accent", min_width=20)
    tabla.add_column("Mín",       justify="right", min_width=7)
    tabla.add_column("Máx",       justify="right", min_width=7)
    tabla.add_column("Media",     justify="right", min_width=7)
    tabla.add_column("Std",       justify="right", min_width=7)
    tabla.add_column("% > umbral", justify="right", min_width=10)
    tabla.add_column("Estado",    justify="center", min_width=10)

    for idx in resultado.indices:
        if idx.error:
            tabla.add_row(
                idx.nombre, "—", "—", "—", "—", "—",
                f"{SYM['err']} Error",
            )
        elif idx.already_existed:
            tabla.add_row(
                idx.nombre,
                _fmt(idx.min_val), _fmt(idx.max_val),
                _fmt(idx.media),   _fmt(idx.desv_std),
                _fmt_pct(idx.pct_sobre_umbral),
                f"{SYM['warn']} Ya existía",
            )
        else:
            tabla.add_row(
                idx.nombre,
                _fmt(idx.min_val), _fmt(idx.max_val),
                _fmt(idx.media),   _fmt(idx.desv_std),
                _fmt_pct(idx.pct_sobre_umbral),
                f"{SYM['ok']}",
            )

    console.print(tabla)

    # ── Errores detallados ────────────────────────────────────────────────────
    if resultado.errores:
        console.print()
        for idx in resultado.errores:
            error(f"[bold]{idx.nombre}[/bold]: {idx.error}")

    console.print()
    divider()
    next_step("terraf analyze")


# ── Helpers de formato ────────────────────────────────────────────────────────

def _fmt(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{val:.3f}"


def _fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{val:.1f}%"
