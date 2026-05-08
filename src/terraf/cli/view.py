"""
terraf view — Visualización flexible del proyecto.

Compón mapas combinando libremente índices, datos vectoriales, targets y
mapa de prospectividad. Las capas son togglables en el mapa.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import SYM, console, divider, error, next_step, success, warning
from terraf.db.session import require_db

app = typer.Typer(
    help="Visualiza recursos del proyecto en un mapa interactivo.",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def cmd(
    recursos: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Recursos a visualizar (separados por espacio). "
            "Sin argumentos: muestra lo más relevante disponible."
        ),
    ),
    listar: bool = typer.Option(
        False,
        "--listar", "-l",
        help="Solo lista los recursos disponibles, sin abrir el mapa.",
    ),
    todo: bool = typer.Option(
        False,
        "--todo", "-t",
        help="Incluye TODOS los recursos disponibles.",
    ),
    abrir: bool = typer.Option(
        True,
        "--abrir/--no-abrir",
        help="Abrir el mapa en el navegador al terminar.",
    ),
    salida: Optional[Path] = typer.Option(
        None,
        "--salida", "-o",
        help="Ruta personalizada para el HTML de salida.",
    ),
):
    """
    Visualiza recursos del proyecto en un mapa interactivo.

    Ejemplos:

      terraf view                          # auto: lo más relevante
      terraf view --todo                   # todo lo disponible
      terraf view ior clay                 # solo IOR y Clay
      terraf view rgb prospectividad targets   # combinación
      terraf view geologia magnetico       # capas vectoriales
      terraf view --listar                 # ver qué hay disponible
    """
    from terraf.pipeline.view import (
        generar_vista,
        listar_recursos_disponibles,
    )

    db_path = require_db()

    # ── Modo listar ───────────────────────────────────────────────────────────
    if listar:
        inventario = listar_recursos_disponibles(db_path)
        console.print()
        if not inventario:
            warning(
                "No hay recursos disponibles todavía.\n"
                "  Carga una imagen con [accent]terraf load[/accent] o calcula "
                "índices con [accent]terraf indices[/accent]."
            )
            console.print()
            raise typer.Exit(0)

        success(f"Recursos disponibles ({len(inventario)})")
        console.print()
        divider()
        console.print()

        # Agrupar por tipo
        grupos: dict[str, list[tuple[str, dict]]] = {
            "Imagen":         [],
            "Índices":        [],
            "Vectoriales":    [],
            "Resultados":     [],
        }
        for nombre, info in inventario.items():
            t = info["tipo"]
            if t == "rgb":
                grupos["Imagen"].append((nombre, info))
            elif t == "raster_indice":
                grupos["Índices"].append((nombre, info))
            elif t == "vector":
                grupos["Vectoriales"].append((nombre, info))
            elif t in ("targets", "raster_prospectividad", "validaciones"):
                grupos["Resultados"].append((nombre, info))

        seen_capa_real: set[str] = set()
        for grupo, items in grupos.items():
            if not items:
                continue
            console.print(f"  [bold]{grupo}[/bold]")
            for nombre, info in items:
                # Evitar duplicar alias de la misma capa
                cr = info.get("capa_real")
                if cr and cr in seen_capa_real:
                    continue
                if cr:
                    seen_capa_real.add(cr)
                desc = info.get("descripcion", "")
                console.print(f"    [accent]{nombre:24}[/accent]  [muted]{desc}[/muted]")
            console.print()

        console.print(
            f"  [muted]Uso:[/muted] [accent]terraf view <recurso1> <recurso2>...[/accent]"
        )
        console.print(
            f"  [muted]    [/muted] [accent]terraf view --todo[/accent]\n"
        )
        raise typer.Exit(0)

    # ── Resolver lista de recursos ────────────────────────────────────────────
    if todo:
        inv = listar_recursos_disponibles(db_path)
        # Eliminar duplicados por capa_real
        recursos_lista: list[str] = []
        seen_capa: set[str] = set()
        for n, info in inv.items():
            cr = info.get("capa_real")
            if cr and cr in seen_capa:
                continue
            if cr:
                seen_capa.add(cr)
            recursos_lista.append(n)
    else:
        recursos_lista = list(recursos) if recursos else None

    console.print()

    def _on_step(msg: str) -> None:
        prefijo = (
            f"  {SYM['warn']}  " if msg.lstrip().startswith(("!", "ADVERTENCIA"))
            else "  [muted]·[/muted]  "
        )
        console.print(f"{prefijo}[muted]{msg}[/muted]")

    with console.status("[accent]Construyendo mapa...[/accent]"):
        try:
            resultado = generar_vista(
                db_path=db_path,
                recursos=recursos_lista,
                out_path=salida,
                on_step=_on_step,
            )
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except Exception as exc:
            error(f"Error inesperado: {exc}")
            raise typer.Exit(1)

    console.print()
    success(f"Mapa generado: [bold]{resultado.html_path.name}[/bold]")
    console.print(f"  [muted]Ubicación:[/muted]  [accent]{resultado.html_path}[/accent]")
    console.print()

    # Tabla de capas incluidas
    if resultado.capas_incluidas:
        console.print(
            f"  [muted]Capas:[/muted]  "
            f"[accent]{', '.join(resultado.capas_incluidas)}[/accent]"
        )
    if resultado.capas_no_disponibles:
        console.print(
            f"  {SYM['warn']}  No disponibles: "
            f"[muted]{', '.join(resultado.capas_no_disponibles)}[/muted]"
        )
        console.print(
            f"      [muted]Ejecuta[/muted] [accent]terraf view --listar[/accent] "
            f"[muted]para ver qué hay.[/muted]"
        )
    console.print()

    if abrir:
        webbrowser.open(resultado.html_path.as_uri())
        console.print(f"  {SYM['arrow']}  Abriendo en el navegador...")
        console.print()
