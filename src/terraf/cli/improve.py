"""
terraf improve — Active learning: sugiere qué targets validar en campo.

Uso:
  terraf improve
  terraf improve --top 10
  terraf improve --modo mixto
  terraf improve --estado
"""

from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, error, success, warning
from terraf.db.session import require_db

app = typer.Typer(help="Active learning: sugiere targets a validar para mejorar el modelo.")


@app.callback(invoke_without_command=True)
def cmd(
    top: int = typer.Option(
        5, "--top", "-n",
        help="Número de sugerencias (default: 5)",
    ),
    modo: str = typer.Option(
        "incertidumbre",
        "--modo", "-m",
        help="Estrategia: incertidumbre | mixto",
    ),
    estado: bool = typer.Option(
        False, "--estado", "-e",
        help="Muestra el estado del ciclo de active learning",
    ),
    analisis_id: Optional[int] = typer.Option(
        None, "--analisis",
        help="ID de análisis específico (default: último)",
    ),
):
    """Recomienda qué targets validar en campo para maximizar la mejora del modelo."""
    from terraf.pipeline.ml.active_learning import (
        estado_active_learning,
        sugerir_validaciones,
    )

    db_path = require_db()
    console.print()

    # ── Modo estado ────────────────────────────────────────────────────────────
    if estado:
        _mostrar_estado(db_path, analisis_id)
        return

    # ── Modo sugerencias ───────────────────────────────────────────────────────
    try:
        sugerencias, resumen = sugerir_validaciones(
            db_path,
            analisis_id=analisis_id,
            top_n=top,
            modo=modo,
        )
    except RuntimeError as exc:
        error(str(exc))
        raise typer.Exit(1)

    if not sugerencias:
        success("Todos los targets del análisis ya están validados.")
        console.print(
            f"  {SYM['arrow']} Reentrenar con los datos completos:  "
            "[accent]terraf train[/accent]"
        )
        console.print()
        return

    # ── Encabezado ─────────────────────────────────────────────────────────────
    console.print(f"  [bold]Targets sugeridos para validación de campo[/bold]")
    console.print()

    ganancia_style = {
        "alta":  "bold green",
        "media": "bold yellow",
        "baja":  "dim",
    }.get(resumen.ganancia_esperada, "")
    console.print(
        f"  [muted]Ganancia esperada:[/muted]  "
        f"[{ganancia_style}]{resumen.ganancia_esperada.upper()}[/{ganancia_style}]  "
        f"[muted]·[/muted]  {resumen.n_sin_validar} targets pendientes"
    )
    console.print()

    # ── Tabla ──────────────────────────────────────────────────────────────────
    t = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    t.add_column("#",          justify="center", min_width=6)
    t.add_column("Prob. ML",   justify="right",  min_width=10)
    t.add_column("Incert.",    justify="right",  min_width=9)
    t.add_column("Score",      justify="right",  min_width=8)
    t.add_column("Prioridad",  justify="center", min_width=10)
    t.add_column("Razón",      min_width=35)

    prio_styles = {"ALTA": "bold green", "MEDIA": "bold yellow", "BAJA": "dim"}

    for sug in sugerencias:
        prob_txt = (
            f"[accent]{sug.prob_positivo:.0%}[/accent]"
            if sug.prob_positivo is not None
            else "[dim]—[/dim]"
        )
        # Incertidumbre: más rojo = más incierto
        inc = sug.incertidumbre
        if inc < 0.10:
            inc_txt = f"[bold red]{inc:.2f}[/bold red]"
        elif inc < 0.25:
            inc_txt = f"[bold yellow]{inc:.2f}[/bold yellow]"
        else:
            inc_txt = f"[dim]{inc:.2f}[/dim]"

        prio_s = prio_styles.get(sug.prioridad, "")
        prio_txt = f"[{prio_s}]{sug.prioridad}[/{prio_s}]" if prio_s else sug.prioridad

        t.add_row(
            sug.nombre,
            prob_txt,
            inc_txt,
            f"{sug.score_original:.3f}",
            prio_txt,
            f"[dim]{sug.razon}[/dim]",
        )

    console.print(t)
    console.print()

    # ── Coordenadas de campo ───────────────────────────────────────────────────
    con_coords = [s for s in sugerencias if s.centroide_lon is not None]
    if con_coords:
        divider()
        console.print()
        console.print("  [bold]Coordenadas de campo (WGS84):[/bold]")
        console.print()
        for s in con_coords:
            console.print(
                f"  [accent]{s.nombre}[/accent]  "
                f"[muted]Lat[/muted] {s.centroide_lat:.6f}  "
                f"[muted]Lon[/muted] {s.centroide_lon:.6f}"
            )
        console.print()

    # ── Flujo de trabajo sugerido ──────────────────────────────────────────────
    divider()
    console.print()
    console.print(f"  [bold]Próximo paso:[/bold]  [muted]{resumen.proxima_accion}[/muted]")
    console.print()
    console.print(
        f"  [muted]1. Valida en campo:[/muted]  "
        f"[accent]terraf validate {sugerencias[0].nombre} positivo --metodo campo[/accent]"
    )
    console.print(
        f"  [muted]2. Reentrenar:[/muted]     [accent]terraf train[/accent]"
    )
    console.print(
        f"  [muted]3. Predecir:[/muted]       [accent]terraf predict[/accent]"
    )
    console.print(
        f"  [muted]4. Repetir:[/muted]        [accent]terraf improve[/accent]"
    )
    console.print()


# ── Vista de estado ────────────────────────────────────────────────────────────

def _mostrar_estado(db_path, analisis_id: Optional[int]) -> None:
    from terraf.pipeline.ml.active_learning import estado_active_learning

    try:
        st = estado_active_learning(db_path, analisis_id=analisis_id)
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(1)

    if not st:
        error("No hay análisis registrado. Ejecuta 'terraf analyze' primero.")
        raise typer.Exit(1)

    console.print("  [bold]Estado del ciclo Active Learning[/bold]")
    console.print()

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="muted", justify="right", min_width=22)
    grid.add_column()

    grid.add_row("Targets totales:",    f"[accent]{st['n_targets']}[/accent]")
    grid.add_row("Validados:",
        f"[bold green]{st['n_validados']}[/bold green]"
        f" [dim]({st['n_positivos']} pos, {st['n_negativos']} neg)[/dim]"
    )
    grid.add_row("Sin validar:",       f"[dim]{st['n_sin_validar']}[/dim]")
    grid.add_row("Con prob. ML:",      f"[accent]{st['n_con_prob']}[/accent]")

    if st.get("prob_media") is not None:
        grid.add_row("Prob. media ML:",  f"[accent]{st['prob_media']:.2%}[/accent]")

    console.print(grid)
    console.print()
    divider()
    console.print()
    console.print(f"  [bold]Ciclo sugerido:[/bold]")
    console.print(f"  [muted]{st['ciclo_sugerido']}[/muted]")
    console.print()

    # Barra de progreso de validación
    n_val = st['n_validados']
    n_tot = st['n_targets']
    if n_tot > 0:
        llenos = round(n_val / n_tot * 20)
        barra = (
            "[accent]" + "█" * llenos + "[/accent]"
            + "[dim]" + "░" * (20 - llenos) + "[/dim]"
        )
        console.print(
            f"  [muted]Progreso:[/muted]  {barra}  "
            f"[accent]{n_val}/{n_tot}[/accent]  "
            f"[muted]({n_val/n_tot:.0%})[/muted]"
        )
        console.print()
