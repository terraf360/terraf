"""
terraf predict — Aplica el modelo ML a todos los targets.

Uso:
  terraf predict
  terraf predict --modelo modelos/modelo_20240101_120000.pkl
  terraf predict --top 15
"""

from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, error, success, warning
from terraf.db.session import require_db

app = typer.Typer(help="Aplica el modelo ML a los targets del análisis.")


@app.callback(invoke_without_command=True)
def cmd(
    modelo: Optional[Path] = typer.Option(
        None, "--modelo", "-m",
        help="Ruta a un .pkl específico (default: modelo más reciente)",
    ),
    top: int = typer.Option(
        10, "--top", "-n",
        help="Targets top a mostrar en la tabla de resultados (default: 10)",
    ),
    analisis_id: Optional[int] = typer.Option(
        None, "--analisis",
        help="ID de análisis específico (default: último)",
    ),
    mapa: bool = typer.Option(
        False, "--mapa",
        help="Genera un mapa HTML con probabilidades ML y lo abre en el navegador",
    ),
):
    """Predice la probabilidad de ser target positivo para cada candidato."""
    from terraf.pipeline.ml.predictor import obtener_predicciones, predecir

    db_path = require_db()
    console.print()

    paso_actual = [0]

    def on_step(msg: str) -> None:
        paso_actual[0] += 1
        console.print(f"  [{paso_actual[0]}] [muted]{msg}[/muted]")

    try:
        info = predecir(
            db_path=db_path,
            analisis_id=analisis_id,
            modelo_path=modelo,
            on_step=on_step,
        )
    except FileNotFoundError as exc:
        error(str(exc))
        console.print(
            f"  [muted]Entrena el modelo primero:[/muted]  "
            "[accent]terraf train[/accent]"
        )
        raise typer.Exit(1)
    except RuntimeError as exc:
        error(str(exc))
        raise typer.Exit(1)
    except Exception as exc:
        error(f"Error inesperado:\n  {exc}")
        raise typer.Exit(1)

    console.print()
    divider()
    console.print()

    # ── Resumen ────────────────────────────────────────────────────────────────
    success(
        f"[bold]{info.n_targets}[/bold] targets actualizados  "
        f"[muted]·[/muted]  modelo [accent]{info.version_modelo[:15]}[/accent]"
    )
    console.print()

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="muted", justify="right", min_width=22)
    grid.add_column()

    grid.add_row("Tipo depósito:",  f"[accent]{info.tipo_deposito}[/accent]")
    grid.add_row("Prob. media:",    f"[accent]{info.prob_media:.2%}[/accent]")
    grid.add_row("Prob. máx:",      f"[bold green]{info.prob_max:.2%}[/bold green]")
    grid.add_row("Alta confianza (≥70%):",  f"[bold green]{info.n_alta}[/bold green]")
    grid.add_row("Media confianza (40-70%):", f"[bold yellow]{info.n_media}[/bold yellow]")
    grid.add_row("Baja confianza (<40%):",  f"[dim]{info.n_baja}[/dim]")

    console.print(grid)
    console.print()

    # ── Tabla top N ───────────────────────────────────────────────────────────
    try:
        predicciones = obtener_predicciones(
            db_path, analisis_id=analisis_id, top_n=top
        )
    except Exception:
        predicciones = []

    if predicciones:
        divider()
        console.print()
        console.print(f"  [bold]Top {top} por probabilidad ML:[/bold]")
        console.print()

        t = Table(
            show_header=True,
            header_style="bold",
            border_style="dim",
            box=box.SIMPLE_HEAD,
        )
        t.add_column("#",           justify="center", min_width=6)
        t.add_column("Prob. ML",    justify="right",  min_width=10)
        t.add_column("Score",       justify="right",  min_width=8)
        t.add_column("Confianza",   justify="center", min_width=12)

        for p in predicciones:
            prob = p.prob_positivo
            if prob >= 0.70:
                conf_txt = "[bold green]ALTA[/bold green]"
            elif prob >= 0.40:
                conf_txt = "[bold yellow]MEDIA[/bold yellow]"
            else:
                conf_txt = "[dim]BAJA[/dim]"

            t.add_row(
                p.nombre,
                f"[accent]{prob:.2%}[/accent]",
                f"{p.score_original:.3f}",
                conf_txt,
            )

        console.print(t)
        console.print()

    # ── Hints ──────────────────────────────────────────────────────────────────
    if info.n_alta > 0:
        console.print(
            f"  {SYM['ok']}  [muted]Valida los targets de alta confianza en campo:[/muted]  "
            "[accent]terraf validate --lista[/accent]"
        )
    console.print(
        f"  {SYM['arrow']}  [muted]Para mejorar el modelo:[/muted]  "
        "[accent]terraf improve[/accent]"
    )
    console.print()

    if mapa:
        from terraf.pipeline.mapper import mapa_prediccion
        try:
            ruta = mapa_prediccion(db_path, analisis_id=analisis_id, abrir=True)
            console.print(
                f"  [muted]Mapa generado:[/muted]  [accent]{ruta}[/accent]\n"
            )
        except ImportError as exc:
            console.print(f"  [yellow]Mapa omitido:[/yellow] {exc}\n")
        except Exception as exc:
            console.print(f"  [yellow]No se pudo generar el mapa:[/yellow] {exc}\n")
