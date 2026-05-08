"""
terraf datos — Integración con datos nacionales de México.

Comandos:
  terraf datos inegi --ruta /path/to/inegi_ambi_usosue_1993.shp
  terraf datos sgm   --ruta /path/to/sgm/  --tipo geologia
  terraf datos       --lista
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, next_step, success, warning, error
from terraf.db.session import require_db

app = typer.Typer(
    help="Carga datos nacionales de Mexico (INEGI, SGM) al proyecto.",
    invoke_without_command=True,
)

# Nombres legibles de capas
_NOMBRES_CAPA: dict[str, str] = {
    "inegi_usosue":         "INEGI — Uso de Suelo y Vegetación",
    "sgm_geologia":         "SGM — Geología",
    "sgm_geofisica":        "SGM — Geofísica",
    "sgm_geoquimica":       "SGM — Geoquímica",
    "sgm_inventario_minero": "SGM — Inventario Minero",
}

_TIPOS_SGM = ["geologia", "geofisica", "geoquimica", "inventario_minero"]


# ──────────────────────────────────────────────────────────────────────────────
# Subcomando: datos inegi
# ──────────────────────────────────────────────────────────────────────────────

@app.command("inegi")
def cmd_inegi(
    ruta: str = typer.Option(
        ...,
        "--ruta", "-r",
        help="Ruta al shapefile INEGI (.shp) de Uso de Suelo y Vegetación.",
    ),
):
    """Carga el shapefile de Uso de Suelo y Vegetacion del INEGI (Serie II)."""
    from terraf.pipeline.datos_nacionales import cargar_inegi_usosue

    db_path = require_db()
    shp_path = Path(ruta)

    if not shp_path.exists():
        error(f"Ruta no encontrada: {shp_path}")
        raise typer.Exit(1)

    console.print()

    pasos: list[str] = []

    def _on_step(msg: str) -> None:
        pasos.append(msg)
        prefijo = f"  {SYM['warn']}  " if "ADVERTENCIA" in msg else "  [muted]·[/muted]  "
        console.print(f"{prefijo}[muted]{msg}[/muted]")

    with console.status("[accent]Procesando datos INEGI...[/accent]"):
        try:
            resultado = cargar_inegi_usosue(
                db_path=db_path,
                shp_path=shp_path,
                on_step=_on_step,
            )
        except FileNotFoundError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except Exception as exc:
            error(f"Error inesperado: {exc}")
            raise typer.Exit(1)

    console.print()

    # ── Idempotencia ──────────────────────────────────────────────────────────
    if resultado.n_ya_existian:
        warning("Los datos INEGI ya estaban cargados en este proyecto.")
        console.print(
            f"    {SYM['arrow']} Ejecuta [accent]terraf datos --lista[/accent] "
            "para ver las capas disponibles."
        )
        console.print()
        raise typer.Exit(0)

    # ── Resumen de éxito ──────────────────────────────────────────────────────
    nombre_capa = _NOMBRES_CAPA.get(resultado.capa, resultado.capa)
    success(f"Datos cargados: [bold]{nombre_capa}[/bold]")
    console.print()
    divider()
    console.print()

    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="muted", justify="right", min_width=14)
    tabla.add_column()

    tabla.add_row("Fuente:", f"[accent]{resultado.fuente.upper()}[/accent]")
    tabla.add_row("Capa:", f"[accent]{resultado.capa}[/accent]")
    tabla.add_row("Features:", f"[accent]{resultado.n_features:,}[/accent]")

    if resultado.bbox_usado:
        minx, miny, maxx, maxy = resultado.bbox_usado
        tabla.add_row(
            "BBox (WGS84):",
            f"[muted]{minx:.4f}, {miny:.4f} → {maxx:.4f}, {maxy:.4f}[/muted]",
        )
    else:
        tabla.add_row("BBox:", "[muted]Sin recorte (país completo)[/muted]")

    tabla.add_row("Archivo:", f"[muted]{shp_path.name}[/muted]")

    console.print(tabla)
    console.print()
    divider()
    next_step("terraf datos --lista", extra="para ver todas las capas cargadas")


# ──────────────────────────────────────────────────────────────────────────────
# Subcomando: datos sgm
# ──────────────────────────────────────────────────────────────────────────────

@app.command("sgm")
def cmd_sgm(
    ruta: str = typer.Option(
        ...,
        "--ruta", "-r",
        help="Ruta al directorio SGM o a un .shp específico.",
    ),
    tipo: str = typer.Option(
        "geologia",
        "--tipo", "-t",
        help=(
            "Tipo de datos SGM: geologia, geofisica, geoquimica, inventario_minero "
            "(default: geologia)"
        ),
    ),
):
    """Carga datos del SGM (GeoInfoMex): geologia, geofisica, geoquimica o inventario minero."""
    from terraf.pipeline.datos_nacionales import cargar_sgm

    db_path = require_db()

    tipo = tipo.lower().strip()
    if tipo not in _TIPOS_SGM:
        error(
            f"Tipo no reconocido: '{tipo}'\n"
            f"  Tipos válidos: {', '.join(_TIPOS_SGM)}"
        )
        raise typer.Exit(1)

    data_path = Path(ruta)
    if not data_path.exists():
        error(f"Ruta no encontrada: {data_path}")
        raise typer.Exit(1)

    console.print()

    def _on_step(msg: str) -> None:
        prefijo = f"  {SYM['warn']}  " if "ADVERTENCIA" in msg else "  [muted]·[/muted]  "
        console.print(f"{prefijo}[muted]{msg}[/muted]")

    with console.status(f"[accent]Procesando datos SGM ({tipo})...[/accent]"):
        try:
            resultado = cargar_sgm(
                db_path=db_path,
                data_path=data_path,
                tipo=tipo,
                on_step=_on_step,
            )
        except FileNotFoundError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except Exception as exc:
            error(f"Error inesperado: {exc}")
            raise typer.Exit(1)

    console.print()

    # ── Idempotencia ──────────────────────────────────────────────────────────
    if resultado.n_ya_existian:
        warning(f"Los datos SGM '{tipo}' ya estaban cargados en este proyecto.")
        console.print(
            f"    {SYM['arrow']} Ejecuta [accent]terraf datos --lista[/accent] "
            "para ver las capas disponibles."
        )
        console.print()
        raise typer.Exit(0)

    # ── Resumen de éxito ──────────────────────────────────────────────────────
    nombre_capa = _NOMBRES_CAPA.get(resultado.capa, resultado.capa)
    success(f"Datos cargados: [bold]{nombre_capa}[/bold]")
    console.print()
    divider()
    console.print()

    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="muted", justify="right", min_width=14)
    tabla.add_column()

    tabla.add_row("Fuente:", "[accent]SGM (GeoInfoMex)[/accent]")
    tabla.add_row("Capa:", f"[accent]{resultado.capa}[/accent]")
    tabla.add_row("Features:", f"[accent]{resultado.n_features:,}[/accent]")

    if resultado.bbox_usado:
        minx, miny, maxx, maxy = resultado.bbox_usado
        tabla.add_row(
            "BBox (WGS84):",
            f"[muted]{minx:.4f}, {miny:.4f} → {maxx:.4f}, {maxy:.4f}[/muted]",
        )
    else:
        tabla.add_row("BBox:", "[muted]Sin recorte (área completa)[/muted]")

    if data_path.is_dir():
        tabla.add_row("Directorio:", f"[muted]{data_path.name}/[/muted]")
    else:
        tabla.add_row("Archivo:", f"[muted]{data_path.name}[/muted]")

    console.print(tabla)
    console.print()
    divider()
    next_step("terraf datos --lista", extra="para ver todas las capas cargadas")


# ──────────────────────────────────────────────────────────────────────────────
# Subcomando: datos mapa
# ──────────────────────────────────────────────────────────────────────────────

@app.command("mapa")
def cmd_mapa(
    capa: str = typer.Option(
        ...,
        "--capa", "-c",
        help=(
            "Nombre de la capa a visualizar: "
            "inegi_usosue, sgm_geofisica, sgm_geologia, "
            "sgm_geoquimica, sgm_inventario_minero"
        ),
    ),
    abrir: bool = typer.Option(
        True,
        "--abrir/--no-abrir",
        help="Abrir el mapa en el navegador al terminar (default: sí).",
    ),
):
    """Genera un mapa interactivo Folium para una capa de datos nacionales."""
    import webbrowser
    from terraf.pipeline.datos_nacionales import generar_mapa_dato_nacional

    db_path = require_db()

    console.print()

    def _on_step(msg: str) -> None:
        console.print(f"  [muted]·[/muted]  [muted]{msg}[/muted]")

    with console.status(f"[accent]Generando mapa para '{capa}'...[/accent]"):
        try:
            html_path = generar_mapa_dato_nacional(
                db_path=db_path,
                capa=capa,
                on_step=_on_step,
            )
        except RuntimeError as exc:
            from terraf.cli.art import error
            error(str(exc))
            raise typer.Exit(1)
        except Exception as exc:
            from terraf.cli.art import error
            error(f"Error inesperado: {exc}")
            raise typer.Exit(1)

    console.print()
    success(f"Mapa generado: [bold]{html_path.name}[/bold]")
    console.print(f"  [muted]Ubicación:[/muted]  [accent]{html_path}[/accent]")
    console.print()

    if abrir:
        webbrowser.open(html_path.as_uri())
        console.print(f"  {SYM['arrow']}  Abriendo en el navegador...")
        console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Callback raíz: --lista
# ──────────────────────────────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def cmd_root(
    ctx: typer.Context,
    lista: bool = typer.Option(
        False,
        "--lista", "-l",
        help="Muestra las capas de datos nacionales ya cargadas.",
        is_eager=True,
    ),
):
    """Integración con datos nacionales de Mexico: INEGI y SGM."""
    if lista:
        from terraf.pipeline.datos_nacionales import listar_datos

        db_path = require_db()
        capas = listar_datos(db_path)

        console.print()

        if not capas:
            warning("No hay datos nacionales cargados en este proyecto.")
            console.print(
                f"\n    {SYM['arrow']} Usa [accent]terraf datos inegi --ruta <ruta>[/accent] "
                "o [accent]terraf datos sgm --ruta <ruta>[/accent] para cargar datos."
            )
            console.print()
            raise typer.Exit(0)

        tabla = Table(
            show_header=True,
            header_style="bold",
            border_style="dim",
            box=box.SIMPLE_HEAD,
        )
        tabla.add_column("Fuente",    style="accent",  min_width=8)
        tabla.add_column("Capa",      style="muted",   min_width=26)
        tabla.add_column("Features",  justify="right", min_width=10)
        tabla.add_column("Cargada",   style="muted",   min_width=16)

        for c in capas:
            nombre = _NOMBRES_CAPA.get(c["capa"], c["capa"])
            tabla.add_row(
                c["fuente"],
                nombre,
                f"{c['n_features']:,}",
                c["cargada_en"],
            )

        success(f"Capas de datos nacionales ({len(capas)} registradas)")
        console.print()
        divider()
        console.print()
        console.print(tabla)
        console.print()
        raise typer.Exit(0)

    # Sin flag y sin subcomando → mostrar ayuda
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(0)
