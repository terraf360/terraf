"""
terraf init — Inicializa un nuevo proyecto de exploración.

Crea una SUBCARPETA con el nombre del proyecto en el directorio actual:
    terraf init zacatecas
    → crea ./zacatecas/terraf.db, ./zacatecas/terraf.toml, etc.

Para especificar dónde crear el proyecto:
    terraf init zacatecas --en /datos/proyectos/
    → crea /datos/proyectos/zacatecas/
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from terraf.cli.art import SYM, console, divider, error, next_step, warning
from terraf.pipeline.project import PROJECT_DIRS, init_project

app = typer.Typer(help="Inicializa un nuevo proyecto de exploración.")

# Directorios que se consideran "peligrosos" para crear proyectos directamente
_DIRS_PELIGROSOS = {
    Path.home(),
    Path.home() / "Documents",
    Path.home() / "Documentos",
    Path.home() / "Desktop",
    Path.home() / "Escritorio",
    Path.home() / "Downloads",
    Path.home() / "Descargas",
    Path.home() / "OneDrive",
}


@app.callback(invoke_without_command=True)
def cmd(
    nombre: str = typer.Argument(..., help="Nombre del proyecto (se creará una subcarpeta con este nombre)"),
    en: Optional[Path] = typer.Option(
        None, "--en", "-d",
        help="Directorio padre donde crear el proyecto (default: directorio actual)",
        exists=False,
    ),
):
    """
    Inicializa un nuevo proyecto en una subcarpeta del directorio actual.

    Ejemplo:
        terraf init zacatecas
        → crea ./zacatecas/ con terraf.db, terraf.toml y carpetas del pipeline.
    """
    # ── Determinar directorio padre ────────────────────────────────────────────
    parent = (en or Path.cwd()).resolve()

    # ── Advertencia si el padre es una carpeta de sistema ──────────────────────
    try:
        parent_resolved = parent.resolve()
        is_dangerous = any(
            parent_resolved == d.resolve()
            for d in _DIRS_PELIGROSOS
            if d.exists()
        )
    except Exception:
        is_dangerous = False

    if is_dangerous:
        console.print()
        warning(
            f"Estás a punto de crear el proyecto en [bold]{parent}[/bold]\n"
            f"  Esta es una carpeta del sistema. Los proyectos TerraF\n"
            f"  funcionan mejor en una carpeta de trabajo dedicada."
        )
        console.print(
            f"  El proyecto se creará en: "
            f"[accent]{parent / nombre}[/accent]"
        )
        console.print()
        confirmar = typer.confirm(
            "  ¿Continuar de todas formas?",
            default=False,
        )
        if not confirmar:
            console.print(
                f"\n  [muted]Sugerencia: crea primero una carpeta de trabajo:[/muted]\n"
                f"  [accent]mkdir proyectos && cd proyectos[/accent]\n"
                f"  [accent]terraf init {nombre}[/accent]\n"
            )
            raise typer.Exit(0)

    # ── Inicializar proyecto ───────────────────────────────────────────────────
    project_dir_objetivo = parent / nombre

    # Verificar que el nombre no sea inválido para una carpeta
    if "/" in nombre or "\\" in nombre:
        error(f"El nombre del proyecto no puede contener '/' ni '\\'.\n  Recibido: {nombre!r}")
        raise typer.Exit(1)

    result = init_project(nombre, directory=project_dir_objetivo)

    if result.already_existed:
        warning(
            f"El proyecto [bold]{result.nombre}[/bold] ya está inicializado en:\n"
            f"  [accent]{result.project_dir}[/accent]"
        )
        console.print(
            f"    {SYM['arrow']} Ejecuta [accent]terraf status[/accent] "
            f"dentro de esa carpeta para ver el estado."
        )
        console.print()
        raise typer.Exit(0)

    # ── Éxito ─────────────────────────────────────────────────────────────────
    console.print()
    console.print(
        f"  [primary]Proyecto creado:[/primary] [bold]{result.nombre}[/bold]"
    )
    console.print(
        f"  [muted]Ubicación:[/muted]  [accent]{result.project_dir}[/accent]"
    )
    console.print()

    # Árbol de archivos
    divider()
    console.print()
    console.print(f"  [muted]  {result.project_dir.name}/[/muted]")
    for d in PROJECT_DIRS:
        parts = d.split("/")
        indent = "    " + "  " * (len(parts) - 1)
        console.print(f"  [muted]{indent}[/muted][dim]{parts[-1]}/[/dim]")
    console.print(f"  [muted]    [/muted][accent]terraf.db[/accent]    [muted]← base de datos[/muted]")
    console.print(f"  [muted]    [/muted][accent]terraf.toml[/accent]  [muted]← configuración[/muted]")
    console.print()
    divider()
    console.print()

    # Indicar cómo entrar al proyecto
    console.print(
        f"  {SYM['arrow']}  Para trabajar en el proyecto entra a la carpeta:"
    )
    console.print(f"  [accent]  cd {result.project_dir.name}[/accent]")
    console.print()

    next_step("terraf load <ruta_imagen_satelital>")
