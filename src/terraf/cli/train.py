"""
terraf train — Entrena el modelo de clasificación ML.

Uso:
  terraf train
  terraf train --tipo porfido_cu
  terraf train --tipo epitermal_au --sinteticos 150
  terraf train --lista
"""

from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, error, success, warning
from terraf.db.session import require_db
from terraf.pipeline.ml.priors import TIPOS_DEPOSITO, list_tipos, prior_description

app = typer.Typer(help="Entrena el modelo ML de clasificación de targets.")


@app.callback(invoke_without_command=True)
def cmd(
    tipo: str = typer.Option(
        "generico",
        "--tipo", "-t",
        help=f"Tipo de depósito: {', '.join(TIPOS_DEPOSITO)}",
    ),
    sinteticos: int = typer.Option(
        100, "--sinteticos", "-s",
        help="Muestras sintéticas por clase (default: 100)",
    ),
    analisis_id: Optional[int] = typer.Option(
        None, "--analisis",
        help="ID de análisis específico (default: último)",
    ),
    lista: bool = typer.Option(
        False, "--lista", "-l",
        help="Lista los tipos de depósito disponibles y modelos guardados",
    ),
):
    """Entrena el modelo de clasificación con datos reales + priors sintéticos."""
    from terraf.pipeline.ml.trainer import entrenar, listar_modelos

    if lista:
        _mostrar_lista()
        return

    # Validar tipo
    if tipo not in TIPOS_DEPOSITO:
        error(
            f"Tipo '{tipo}' no válido.\n"
            f"  Opciones: {', '.join(TIPOS_DEPOSITO)}"
        )
        raise typer.Exit(1)

    db_path = require_db()

    console.print()
    console.print(f"  [bold]Tipo de depósito:[/bold]  [accent]{tipo}[/accent]")
    console.print(f"  [muted]{prior_description(tipo)}[/muted]")
    console.print()

    pasos: list[str] = []
    paso_actual = [0]

    def on_step(msg: str) -> None:
        paso_actual[0] += 1
        console.print(f"  [{paso_actual[0]}] [muted]{msg}[/muted]")

    try:
        info = entrenar(
            db_path=db_path,
            tipo_deposito=tipo,
            analisis_id=analisis_id,
            n_sinteticos=sinteticos,
            on_step=on_step,
        )
    except ImportError as exc:
        error(str(exc))
        raise typer.Exit(1)
    except RuntimeError as exc:
        error(str(exc))
        raise typer.Exit(1)
    except Exception as exc:
        error(f"Error inesperado durante el entrenamiento:\n  {exc}")
        raise typer.Exit(1)

    console.print()
    divider()
    console.print()

    # ── Resumen ────────────────────────────────────────────────────────────────
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="muted", justify="right", min_width=22)
    grid.add_column(style="accent")

    grid.add_row("Versión:",        info.version)
    grid.add_row("Tipo depósito:",  info.tipo_deposito)
    grid.add_row("Muestras totales:", str(info.n_total))
    grid.add_row("  Sintéticas:",   str(info.n_sinteticos))
    grid.add_row("  Reales:",       f"[bold green]{info.n_reales}[/bold green]"
                                    if info.n_reales > 0 else "[dim]0[/dim]")

    if info.score_cv is not None:
        color = "bold green" if info.score_cv >= 0.80 else "bold yellow"
        grid.add_row("CV accuracy:",   f"[{color}]{info.score_cv:.1%}[/{color}]")

    grid.add_row("Guardado en:",    str(info.ruta_pkl))

    console.print(grid)
    console.print()

    if info.n_reales == 0:
        warning(
            "Entrenado solo con priors sintéticos (sin datos de campo).\n"
            f"    {SYM['arrow']} Usa [accent]terraf validate[/accent] para registrar "
            "validaciones de campo y reentrenar."
        )
    elif info.n_reales < 10:
        warning(
            f"Solo {info.n_reales} validaciones reales — modelo experimental.\n"
            f"    {SYM['arrow']} Se recomiendan ≥ 10 para resultados confiables."
        )
    else:
        success(
            f"Modelo entrenado con [bold]{info.n_reales}[/bold] validaciones reales."
        )

    console.print()
    console.print(
        f"  {SYM['ok']}  Aplica el modelo con:  [accent]terraf predict[/accent]"
    )
    console.print()


# ── Vista lista de tipos y modelos ─────────────────────────────────────────────

def _mostrar_lista() -> None:
    from terraf.pipeline.ml.trainer import listar_modelos

    console.print()

    # Tipos disponibles
    console.print("  [bold]Tipos de depósito disponibles:[/bold]")
    console.print()

    t = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    t.add_column("Tipo",       style="accent", min_width=16)
    t.add_column("Descripción")

    for tipo in list_tipos():
        t.add_row(tipo, prior_description(tipo))

    console.print(t)
    console.print()

    # Modelos guardados
    console.print("  [bold]Modelos entrenados:[/bold]")
    console.print()

    modelos = listar_modelos()
    if not modelos:
        console.print("  [muted](Sin modelos guardados. Ejecuta terraf train)[/muted]")
        console.print()
        return

    m = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    m.add_column("Versión",       style="accent", min_width=18)
    m.add_column("Tipo",          min_width=14)
    m.add_column("Reales",        justify="right", min_width=8)
    m.add_column("Sintéticos",    justify="right", min_width=10)
    m.add_column("Fecha")

    for mod in modelos:
        fecha = mod.get("entrenado_en", "—")
        m.add_row(
            mod.get("version", "—"),
            mod.get("tipo_deposito", "—"),
            str(mod.get("n_reales", 0)),
            str(mod.get("n_sinteticos", 0)),
            fecha[:16].replace("_", " ") if "_" in fecha else fecha[:16],
        )

    console.print(m)
    console.print()
