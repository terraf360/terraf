"""
terraf load — Carga una imagen de satélite en el proyecto.
"""

from pathlib import Path

import typer
from rich.table import Table

from terraf.cli.art import SYM, console, divider, next_step, success, warning, error
from terraf.db.session import require_db

app = typer.Typer(help="Carga una imagen de satelite en el proyecto.")


@app.callback(invoke_without_command=True)
def cmd(
    ruta: str = typer.Argument(..., help="Ruta al directorio de la imagen (Landsat 9)"),
    sensor: str = typer.Option(
        None,
        "--sensor", "-s",
        help="Sensor: landsat9, sentinel2 (autodetectado si no se indica)",
    ),
    nombre: str = typer.Option(
        None,
        "--nombre", "-n",
        help="Alias descriptivo opcional",
    ),
):
    """Registra una imagen satelital y sus metadatos en la base de datos."""
    from terraf.pipeline.loader import load_image_to_db

    db_path = require_db()

    console.print()

    # ── Leer metadatos con spinner ─────────────────────────────────────────────
    with console.status("[accent]Leyendo metadatos de la imagen...[/accent]"):
        try:
            img = load_image_to_db(
                ruta=Path(ruta),
                db_path=db_path,
                sensor_override=sensor,
                nombre=nombre,
            )
        except FileNotFoundError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except ValueError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(1)

    # ── Idempotencia ──────────────────────────────────────────────────────────
    if img.already_existed:
        warning(
            f"La imagen [bold]{img.scene_id}[/bold] ya estaba registrada en este proyecto."
        )
        console.print(
            f"    {SYM['arrow']} Ejecuta [accent]terraf status[/accent] "
            "para ver el estado actual."
        )
        console.print()
        raise typer.Exit(0)

    # ── Resumen de éxito ──────────────────────────────────────────────────────
    success(f"Imagen cargada: [bold]{img.scene_id}[/bold]")
    console.print()
    divider()
    console.print()

    # Tabla de metadatos (grid de 2 columnas: etiqueta | valor)
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="muted", justify="right", min_width=12)
    tabla.add_column()

    tabla.add_row("Sensor:", f"[accent]{img.sensor}[/accent]")

    if img.fecha_adquisicion:
        tabla.add_row("Fecha:", f"[accent]{img.fecha_adquisicion}[/accent]")

    if img.crs:
        tabla.add_row("CRS:", f"[accent]{img.crs}[/accent]")

    if img.ancho_px and img.alto_px:
        res_txt = f"  [muted]({img.resolucion_m:.0f} m/px)[/muted]" if img.resolucion_m else ""
        tabla.add_row(
            "Dimensiones:",
            f"[accent]{img.ancho_px:,} × {img.alto_px:,} px[/accent]{res_txt}",
        )

    if img.bandas:
        tabla.add_row("Bandas:", f"[accent]{' · '.join(img.bandas)}[/accent]")

    console.print(tabla)
    console.print()
    divider()

    next_step(
        "terraf geology <ruta_sgm>",
        extra="o: terraf indices  (sin datos geologicos)",
    )
