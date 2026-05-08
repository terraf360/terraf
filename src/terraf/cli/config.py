"""
terraf config — Gestiona la configuración del proyecto (terraf.toml).

Subcomandos:
  show          Muestra la configuración actual.
  set <k> <v>  Modifica un parámetro y guarda.
"""

from __future__ import annotations

import typer
from rich.table import Table

from terraf.cli.art import SYM, console, divider, error, success, warning
from terraf.config import DEFAULT_CONFIG, find_config, get_value, load, save, set_value

app = typer.Typer(help="Gestiona la configuracion del proyecto.")

# Descripciones de claves conocidas para mostrar en `show`
_DESCRIPCIONES: dict[str, str] = {
    "proyecto.nombre":              "Nombre del proyecto",
    "proyecto.creado":              "Fecha de creación",
    "proyecto.version_terraf":      "Versión de TerraF",
    "procesamiento.umbral_ior":     "Umbral Iron Oxide Ratio",
    "procesamiento.umbral_clay":    "Umbral Clay Ratio",
    "procesamiento.buffer_litologia": "Buffer de litología (m)",
    "procesamiento.min_area_cluster": "Área mínima de cluster (px)",
    "exportacion.formato_default":  "Formato de exportación default",
    "exportacion.directorio_salida":"Directorio de salida",
    "database.ruta":                "Ruta de la base de datos",
}


# ──────────────────────────────────────────────────────────────────────────────
# terraf config show
# ──────────────────────────────────────────────────────────────────────────────

@app.command("show")
def show():
    """Muestra la configuración actual del proyecto (terraf.toml)."""
    config_path = find_config()
    if config_path is None:
        error(
            "No se encontró terraf.toml en este directorio.\n"
            "  Ejecuta [accent]terraf init <nombre>[/accent] para crear un proyecto."
        )
        raise typer.Exit(1)

    try:
        cfg = load(config_path)
    except Exception as exc:
        error(f"No se pudo leer terraf.toml: {exc}")
        raise typer.Exit(1)

    console.print()
    console.print(f"  [muted]Archivo:[/muted] [accent]{config_path}[/accent]")
    console.print()

    for seccion, valores in cfg.items():
        if not isinstance(valores, dict):
            continue

        # Encabezado de sección
        console.print(f"  [bold]\\[{seccion}][/bold]")

        t = Table.grid(padding=(0, 3))
        t.add_column(style="muted", justify="right", min_width=30)
        t.add_column(style="accent", min_width=20)
        t.add_column(style="dim")

        for clave, valor in valores.items():
            key_full = f"{seccion}.{clave}"
            desc = _DESCRIPCIONES.get(key_full, "")
            t.add_row(clave, str(valor), desc)

        console.print(t)
        console.print()

    divider()
    console.print()
    console.print(
        f"  [muted]Para modificar:[/muted]  "
        "[accent]terraf config set <seccion.clave> <valor>[/accent]"
    )
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# terraf config set
# ──────────────────────────────────────────────────────────────────────────────

@app.command("set")
def set_cmd(
    clave: str = typer.Argument(
        ...,
        help="Clave en notacion de punto (ej: procesamiento.umbral_ior)",
    ),
    valor: str = typer.Argument(
        ...,
        help="Nuevo valor",
    ),
):
    """Modifica un parámetro de configuracion y lo guarda en terraf.toml."""
    config_path = find_config()
    if config_path is None:
        error(
            "No se encontró terraf.toml en este directorio.\n"
            "  Ejecuta [accent]terraf init <nombre>[/accent] para crear un proyecto."
        )
        raise typer.Exit(1)

    try:
        cfg = load(config_path)
    except Exception as exc:
        error(f"No se pudo leer terraf.toml: {exc}")
        raise typer.Exit(1)

    # Advertir si la clave no existe en la configuración actual
    valor_anterior = get_value(cfg, clave)
    if valor_anterior is None:
        # Verificar si existe en defaults
        from terraf.config import _deep_copy  # noqa: PLC0415
        defaults_flat = _flatten(DEFAULT_CONFIG)
        if clave not in defaults_flat:
            warning(
                f"La clave [bold]{clave}[/bold] no existe en la configuración default.\n"
                f"    {SYM['arrow']} Se creará como nueva entrada."
            )

    # Aplicar y guardar
    try:
        cfg = set_value(cfg, clave, valor)
        save(cfg, config_path)
    except Exception as exc:
        error(f"No se pudo guardar la configuración: {exc}")
        raise typer.Exit(1)

    valor_nuevo = get_value(cfg, clave)
    console.print()

    if valor_anterior is not None:
        success(
            f"[bold]{clave}[/bold]  "
            f"[muted]{valor_anterior}[/muted]  [accent]→[/accent]  "
            f"[accent]{valor_nuevo}[/accent]"
        )
    else:
        success(f"[bold]{clave}[/bold]  [accent]{valor_nuevo}[/accent]  [muted](creado)[/muted]")

    console.print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flatten(d: dict, prefix: str = "") -> dict:
    """Aplana un dict anidado a claves con notación de punto."""
    out: dict = {}
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, full))
        else:
            out[full] = v
    return out
