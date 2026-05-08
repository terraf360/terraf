"""
CLI principal de terraf — construida con Typer.
"""

import typer

from terraf import __version__
from terraf.cli.art import BANNER, console, print_welcome

app = typer.Typer(
    name="terraf",
    no_args_is_help=False,       # manejamos nosotros el caso sin args
    invoke_without_command=True,
    rich_markup_mode="rich",
    add_completion=True,
)


def version_callback(show: bool):
    if show:
        print_welcome()
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Muestra la version de terraf.",
    ),
):
    """
TERRAF -- Exploracion minera desde la terminal.

Flujo de trabajo:

  1. terraf init [nombre]    Inicializa un proyecto
  2. terraf load [ruta]      Carga imagen de satelite
  3. terraf geology [ruta]   Vincula datos SGM
  4. terraf indices           Calcula indices espectrales
  5. terraf analyze           Detecta targets de exploracion
  6. terraf report            Genera reporte de resultados
  7. terraf export            Exporta a GeoJSON / Shapefile
    """
    if ctx.invoked_subcommand is None:
        # Sin subcomando → pantalla de bienvenida + resumen de comandos
        print_welcome()
        console.print("  [muted]Comandos disponibles:[/muted]\n")
        commands = [
            ("init     [nombre]", "Inicializa un nuevo proyecto"),
            ("load     [ruta]  ", "Carga imagen de satelite (Landsat 9)"),
            ("geology  [ruta]  ", "Vincula datos geologicos del SGM"),
            ("indices          ", "Calcula indices espectrales"),
            ("analyze          ", "Detecta targets de exploracion"),
            ("prospectivity    ", "Mapa de probabilidad de mineralizacion"),
            ("view     [capa]  ", "Visualiza recursos en mapa interactivo"),
            ("datos    [...]   ", "Carga/visualiza datos nacionales (INEGI/SGM)"),
            ("report           ", "Genera reporte de resultados"),
            ("export           ", "Exporta a GeoJSON / Shapefile"),
            ("validate [target]", "Registra validaciones de campo"),
            ("train            ", "Entrena el modelo ML de clasificación"),
            ("predict          ", "Aplica el modelo ML a los targets"),
            ("improve          ", "Active learning: sugiere targets a validar"),
            ("gui              ", "Abre la interfaz gráfica (PyQt5)"),
            ("status           ", "Muestra estado del pipeline"),
        ]
        for cmd, desc in commands:
            console.print(f"  [accent]terraf {cmd}[/accent]  [muted]{desc}[/muted]")
        console.print()
        console.print(
            "  [muted]Ejecuta[/muted] [accent]terraf --help[/accent] "
            "[muted]o[/muted] [accent]terraf [comando] --help[/accent] "
            "[muted]para más detalle.[/muted]\n"
        )


# ── Registrar subcomandos ─────────────────────────────────────────────────────
from terraf.cli import (  # noqa: E402, F401
    analyze, config, datos, db, export, geology, gui, improve, indices, init, load, predict, prospectivity, report, status, train, validate, view,
)

app.add_typer(init.app,      name="init")
app.add_typer(load.app,      name="load")
app.add_typer(geology.app,   name="geology")
app.add_typer(indices.app,   name="indices")
app.add_typer(analyze.app,   name="analyze")
app.add_typer(report.app,    name="report")
app.add_typer(export.app,    name="export")
app.add_typer(status.app,    name="status")
app.add_typer(db.app,        name="db")
app.add_typer(config.app,    name="config")
app.add_typer(validate.app,  name="validate")
app.add_typer(train.app,     name="train")
app.add_typer(predict.app,   name="predict")
app.add_typer(improve.app,   name="improve")
app.add_typer(gui.app,       name="gui")
app.add_typer(datos.app,     name="datos")
app.add_typer(prospectivity.app, name="prospectivity")
app.add_typer(view.app,      name="view")
