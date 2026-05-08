"""
terraf export — Exporta resultados a GeoJSON y/o Shapefile.
"""

from pathlib import Path
from typing import Optional

import typer

from terraf.cli.art import SYM, console, divider, success, error, warning
from terraf.db.session import require_db

app = typer.Typer(help="Exporta resultados a formatos GIS estandar.")

_FORMATOS = ["geojson", "shapefile", "ambos"]
_INCLUIR  = ["targets", "indices", "todo"]


@app.callback(invoke_without_command=True)
def cmd(
    formato: str = typer.Option(
        "ambos", "--formato", "-f",
        help="Formato de exportacion: geojson, shapefile, ambos",
    ),
    ruta: Optional[str] = typer.Option(
        None, "--ruta", "-r",
        help="Directorio de salida (default: resultados/targets/)",
    ),
    analisis_id: Optional[int] = typer.Option(
        None, "--analisis",
        help="ID de analisis especifico (default: ultimo)",
    ),
    sobreescribir: bool = typer.Option(
        True, "--sobreescribir/--no-sobreescribir",
        help="Sobreescribir archivos existentes",
    ),
):
    """Exporta targets del ultimo analisis a GeoJSON y/o Shapefile."""
    from terraf.pipeline.exporter import exportar

    db_path = require_db()

    if formato not in _FORMATOS:
        error(
            f"Formato '{formato}' no valido.\n"
            f"  Opciones: {', '.join(_FORMATOS)}"
        )
        raise typer.Exit(1)

    directorio = Path(ruta) if ruta else None

    console.print()
    with console.status("[accent]Exportando resultados...[/accent]"):
        try:
            resultado = exportar(
                db_path=db_path,
                formato=formato,
                directorio=directorio,
                analisis_id=analisis_id,
                sobreescribir=sobreescribir,
            )
        except (RuntimeError, ValueError) as exc:
            error(str(exc))
            raise typer.Exit(1)
        except FileExistsError as exc:
            warning(str(exc))
            raise typer.Exit(0)

    # ── Resumen ────────────────────────────────────────────────────────────────
    success(
        f"Exportacion completada  "
        f"[muted]({resultado.n_targets} target(s))[/muted]"
    )
    console.print()
    divider()
    console.print()

    # Tabla de archivos generados
    for arch in resultado.archivos:
        if arch.tamanio_kb == 0:
            console.print(f"  {SYM['warn']}  {arch.descripcion}")
        else:
            console.print(
                f"  {SYM['ok']}  [accent]{arch.ruta.name}[/accent]"
                f"  [muted]{arch.descripcion}  ·  "
                f"{arch.n_features} features  ·  {arch.tamanio_kb} KB[/muted]"
            )

    # ── Hints de uso ──────────────────────────────────────────────────────────
    geojson_arch = next(
        (a for a in resultado.archivos if a.ruta.suffix == ".geojson"), None
    )
    console.print()
    if geojson_arch:
        console.print(
            "  [muted]Para visualizar en QGIS:[/muted]\n"
            f"    [accent]Capa → Agregar capa → {geojson_arch.ruta}[/accent]"
        )
        console.print(
            "  [muted]Para Google Earth:[/muted]\n"
            "    [accent]ogr2ogr targets.kml targets.geojson[/accent]"
        )
    console.print()
    divider()
    console.print()
