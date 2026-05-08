"""
terraf validate — Registra validaciones de campo sobre targets.

Uso:
  terraf validate T001 positivo --metodo campo --notas "bateo positivo"
  terraf validate --lista
  terraf validate --pendientes
"""

from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, error, success, warning
from terraf.db.session import require_db
from terraf.pipeline.validation import METODOS_VALIDOS, RESULTADOS_VALIDOS

app = typer.Typer(help="Registra validaciones de campo sobre targets.")

# ── Estilos por resultado ──────────────────────────────────────────────────────
_RESULTADO_STYLE = {
    "positivo":  "bold green",
    "negativo":  "bold red",
    "dudoso":    "bold yellow",
    "pendiente": "dim",
}

_RESULTADO_SYM = {
    "positivo":  "✓",
    "negativo":  "✗",
    "dudoso":    "?",
    "pendiente": "○",
}


@app.callback(invoke_without_command=True)
def cmd(
    identificador: Optional[str] = typer.Argument(
        None,
        help='Nombre del target a validar (ej: T001) o su ID numérico',
    ),
    resultado: Optional[str] = typer.Argument(
        None,
        help=f"Resultado: {', '.join(RESULTADOS_VALIDOS)}",
    ),
    metodo: Optional[str] = typer.Option(
        None, "--metodo", "-m",
        help=f"Método de validación: {', '.join(METODOS_VALIDOS)}",
    ),
    notas: Optional[str] = typer.Option(
        None, "--notas", "-n",
        help="Notas de campo (texto libre)",
    ),
    lista: bool = typer.Option(
        False, "--lista", "-l",
        help="Muestra todos los targets con su estado de validación",
    ),
    pendientes: bool = typer.Option(
        False, "--pendientes", "-p",
        help="Muestra solo los targets sin validar",
    ),
    analisis_id: Optional[int] = typer.Option(
        None, "--analisis",
        help="ID de análisis específico (default: último)",
    ),
    mapa: bool = typer.Option(
        False, "--mapa",
        help="Genera un mapa HTML con el estado de validaciones y lo abre en el navegador",
    ),
):
    """Registra o consulta validaciones de campo sobre targets."""
    from terraf.pipeline.validation import (
        listar_validaciones,
        resumen_validaciones,
        validar_target,
    )

    db_path = require_db()

    # ── Modo lista / pendientes ────────────────────────────────────────────────
    if lista or pendientes or identificador is None:
        _mostrar_lista(
            db_path,
            analisis_id=analisis_id,
            solo_pendientes=pendientes,
        )
        if mapa:
            _generar_mapa_validaciones(db_path, analisis_id)
        return

    # ── Modo validación ────────────────────────────────────────────────────────
    if resultado is None:
        error(
            "Debes indicar el resultado.\n"
            f"  Uso: terraf validate <target> <resultado>\n"
            f"  Opciones: {', '.join(RESULTADOS_VALIDOS)}"
        )
        raise typer.Exit(1)

    console.print()

    try:
        info = validar_target(
            db_path=db_path,
            identificador=identificador,
            resultado=resultado,
            metodo=metodo,
            notas=notas,
            analisis_id=analisis_id,
        )
    except ValueError as exc:
        error(str(exc))
        raise typer.Exit(1)
    except LookupError as exc:
        error(str(exc))
        raise typer.Exit(1)
    except RuntimeError as exc:
        error(str(exc))
        raise typer.Exit(1)

    # ── Confirmación ──────────────────────────────────────────────────────────
    accion = "actualizado" if info.actualizado else "registrado"
    estilo = _RESULTADO_STYLE.get(info.resultado, "")
    simbolo = _RESULTADO_SYM.get(info.resultado, "○")

    success(
        f"[bold]{info.target_nombre}[/bold]  {accion}  "
        f"[{estilo}]{simbolo} {info.resultado.upper()}[/{estilo}]"
    )

    if info.metodo:
        console.print(f"    [muted]Método:[/muted]  [accent]{info.metodo}[/accent]")
    if info.notas:
        console.print(f"    [muted]Notas:[/muted]   {info.notas}")

    console.print()

    # ── Resumen rápido tras validar ────────────────────────────────────────────
    try:
        resumen = resumen_validaciones(db_path, analisis_id=analisis_id)
        barra = _barra_progreso(resumen.validados, resumen.total_targets)
        console.print(
            f"  [muted]Progreso:[/muted]  {barra}  "
            f"[accent]{resumen.validados}/{resumen.total_targets}[/accent]  "
            f"[muted]({resumen.pct_completado:.0f}%)[/muted]"
        )
        console.print(
            f"  [muted]          [/muted]  "
            f"[bold green]✓ {resumen.positivos}[/bold green]  "
            f"[bold red]✗ {resumen.negativos}[/bold red]  "
            f"[bold yellow]? {resumen.dudosos}[/bold yellow]  "
            f"[dim]○ {resumen.pendientes}[/dim]"
        )
    except Exception:
        pass

    console.print()

    if mapa:
        _generar_mapa_validaciones(db_path, analisis_id)


# ── Vista de lista ─────────────────────────────────────────────────────────────

def _mostrar_lista(
    db_path,
    analisis_id: Optional[int],
    solo_pendientes: bool,
) -> None:
    from terraf.pipeline.validation import listar_validaciones, resumen_validaciones

    console.print()

    try:
        targets = listar_validaciones(
            db_path,
            analisis_id=analisis_id,
            solo_pendientes=solo_pendientes,
        )
        resumen = resumen_validaciones(db_path, analisis_id=analisis_id)
    except RuntimeError as exc:
        error(str(exc))
        raise typer.Exit(1)

    if not targets:
        console.print(
            "  [muted]No hay targets " +
            ("sin validar " if solo_pendientes else "") +
            "en el análisis actual.[/muted]"
        )
        console.print()
        return

    # ── Encabezado ─────────────────────────────────────────────────────────────
    titulo = "Targets pendientes" if solo_pendientes else "Estado de validaciones"
    console.print(f"  [bold]{titulo}[/bold]")
    console.print()

    # ── Tabla ──────────────────────────────────────────────────────────────────
    t = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    t.add_column("#",          justify="center", min_width=5)
    t.add_column("Score",      justify="right",  min_width=7)
    t.add_column("Prioridad",  justify="center", min_width=10)
    t.add_column("Prob. ML",   justify="right",  min_width=9)
    t.add_column("Resultado",  justify="center", min_width=12)
    t.add_column("Método",     min_width=10)
    t.add_column("Notas",      min_width=20)

    for tgt in targets:
        estilo  = _RESULTADO_STYLE.get(tgt.resultado or "pendiente", "dim")
        simbolo = _RESULTADO_SYM.get(tgt.resultado or "pendiente", "○")
        resultado_txt = (
            f"[{estilo}]{simbolo} {(tgt.resultado or 'pendiente').upper()}[/{estilo}]"
        )

        prob_txt = (
            f"{tgt.prob_positivo:.2f}" if tgt.prob_positivo is not None else "[dim]—[/dim]"
        )

        prio_styles = {"ALTA": "bold green", "MEDIA": "bold yellow", "BAJA": "dim"}
        prio_s = prio_styles.get(tgt.prioridad, "")
        prio_txt = f"[{prio_s}]{tgt.prioridad}[/{prio_s}]" if prio_s else tgt.prioridad

        t.add_row(
            tgt.nombre,
            f"{tgt.score:.3f}",
            prio_txt,
            prob_txt,
            resultado_txt,
            f"[muted]{tgt.metodo or '—'}[/muted]",
            f"[dim]{tgt.notas or ''}[/dim]",
        )

    console.print(t)
    console.print()

    # ── Resumen ────────────────────────────────────────────────────────────────
    divider()
    console.print()
    barra = _barra_progreso(resumen.validados, resumen.total_targets)
    console.print(
        f"  [muted]Progreso:[/muted]  {barra}  "
        f"[accent]{resumen.validados}/{resumen.total_targets}[/accent]  "
        f"[muted]({resumen.pct_completado:.0f}%)[/muted]"
    )
    console.print(
        f"  [muted]          [/muted]  "
        f"[bold green]✓ {resumen.positivos} positivos[/bold green]  "
        f"[bold red]✗ {resumen.negativos} negativos[/bold red]  "
        f"[bold yellow]? {resumen.dudosos} dudosos[/bold yellow]  "
        f"[dim]○ {resumen.pendientes} pendientes[/dim]"
    )

    if resumen.pendientes > 0 and not solo_pendientes:
        console.print()
        console.print(
            f"  [muted]Para ver solo los pendientes:[/muted]  "
            "[accent]terraf validate --pendientes[/accent]"
        )

    if resumen.validados >= 10:
        console.print()
        console.print(
            f"  {SYM['ok']}  [muted]Con {resumen.validados} validaciones puedes entrenar el modelo:[/muted]  "
            "[accent]terraf train[/accent]"
        )

    console.print()


# ── Helper mapa ───────────────────────────────────────────────────────────────

def _generar_mapa_validaciones(db_path, analisis_id) -> None:
    from terraf.pipeline.mapper import mapa_validaciones
    try:
        ruta = mapa_validaciones(db_path, analisis_id=analisis_id, abrir=True)
        console.print(
            f"  [muted]Mapa generado:[/muted]  [accent]{ruta}[/accent]\n"
        )
    except ImportError as exc:
        console.print(f"  [yellow]Mapa omitido:[/yellow] {exc}\n")
    except Exception as exc:
        console.print(f"  [yellow]No se pudo generar el mapa:[/yellow] {exc}\n")


# ── Helper barra de progreso ──────────────────────────────────────────────────

def _barra_progreso(actual: int, total: int, ancho: int = 20) -> str:
    if total == 0:
        return "[dim]" + "─" * ancho + "[/dim]"
    llenos = round(actual / total * ancho)
    return (
        "[accent]" + "█" * llenos + "[/accent]"
        + "[dim]" + "░" * (ancho - llenos) + "[/dim]"
    )
