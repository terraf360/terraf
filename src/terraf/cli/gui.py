"""
terraf gui — Lanza la interfaz gráfica de TerraF.

Uso:
  terraf gui
"""

import typer

app = typer.Typer(help="Lanza la interfaz gráfica de TerraF (PyQt5).")


@app.callback(invoke_without_command=True)
def cmd():
    """Abre la ventana gráfica de TerraF."""
    try:
        from terraf.gui.app import main
        main()
    except ImportError as exc:
        typer.echo(
            f"Error: PyQt5 no está instalado.\n"
            f"  Instálalo con: pip install 'terraf[gui]'\n"
            f"  o directamente: pip install PyQt5\n\n"
            f"  Detalle: {exc}"
        )
        raise typer.Exit(1)
