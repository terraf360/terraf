"""
terraf geology — Carga y vincula datos geológicos del SGM.
"""

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from terraf.cli.art import SYM, console, divider, next_step, success, warning, error
from terraf.db.session import require_db
from terraf.pipeline.geology import CAPAS_SOPORTADAS

app = typer.Typer(help="Carga y vincula datos geologicos del SGM al proyecto.")

# Nombres legibles por tipo de capa
_NOMBRES_CAPA: dict[str, str] = {
    "litologia":       "Litología",
    "geoquimica":      "Geoquímica",
    "inventarios":     "Inventarios Mineros",
    "campo_magnetico": "Campo Magnético",
    "geocronologia":   "Geocronología",
    "fallas":          "Fallas",
    "estructuras":     "Estructuras",
    "otro":            "Otro",
}


@app.callback(invoke_without_command=True)
def cmd(
    ruta: str = typer.Argument(..., help="Ruta al directorio de datos SGM"),
    carta: Optional[str] = typer.Option(
        None,
        "--carta", "-c",
        help="ID de carta geológica (autodetectado si no se indica)",
    ),
    capas: Optional[str] = typer.Option(
        None,
        "--capas",
        help=(
            "Capas a cargar separadas por coma: "
            "litologia, geoquimica, inventarios, campo_magnetico, geocronologia "
            "(default: todas)"
        ),
    ),
):
    """Carga shapefiles SGM y registra sus features en la base de datos."""
    from terraf.pipeline.geology import load_geology_to_db

    db_path = require_db()

    # Parsear filtro de capas
    capas_filtro: Optional[list[str]] = None
    if capas:
        capas_filtro = [c.strip().lower() for c in capas.split(",")]
        invalidas = [c for c in capas_filtro if c not in CAPAS_SOPORTADAS]
        if invalidas:
            error(
                f"Capas no reconocidas: {', '.join(invalidas)}\n"
                f"  Capas válidas: {', '.join(CAPAS_SOPORTADAS)}"
            )
            raise typer.Exit(1)

    console.print()

    # Estado de progreso por capa
    _estado: dict[str, str] = {}

    def _on_layer(capa: str) -> None:
        _estado["actual"] = capa
        nombre = _NOMBRES_CAPA.get(capa, capa)
        console.print(f"  [muted]Cargando[/muted] [accent]{nombre}[/accent]...")

    # ── Cargar con spinner global ─────────────────────────────────────────────
    with console.status("[accent]Escaneando directorio SGM...[/accent]"):
        try:
            resultado = load_geology_to_db(
                ruta=Path(ruta),
                db_path=db_path,
                carta_id=carta,
                capas_filtro=capas_filtro,
                on_layer=None,   # usamos el spinner global; progress detallado abajo
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

    # ── Verificar si todo ya existía ──────────────────────────────────────────
    todas_existian = all(c.already_existed for c in resultado.capas)
    if todas_existian:
        warning("Todos los datos geológicos ya estaban registrados en este proyecto.")
        console.print(
            f"    {SYM['arrow']} Ejecuta [accent]terraf status[/accent] "
            "para ver el estado actual."
        )
        console.print()
        raise typer.Exit(0)

    # ── Encabezado de éxito ───────────────────────────────────────────────────
    n_ok = len(resultado.capas_ok)
    carta_txt = resultado.capas[0].carta_id if resultado.capas else ""
    carta_label = f" — {carta_txt}" if carta_txt else ""

    success(f"Datos geológicos cargados{carta_label}")
    console.print()
    divider()
    console.print()

    # ── Tabla resumen ─────────────────────────────────────────────────────────
    tabla = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=_rich_box_simple(),
    )
    tabla.add_column("Capa", style="accent", min_width=22)
    tabla.add_column("Features", justify="right", min_width=10)
    tabla.add_column("CRS", style="muted", min_width=20)
    tabla.add_column("Estado", justify="center", min_width=8)

    for capa_info in resultado.capas:
        nombre = _NOMBRES_CAPA.get(capa_info.capa, capa_info.capa)
        crs_str = _short_crs(capa_info.crs)

        if capa_info.error:
            tabla.add_row(
                nombre,
                "—",
                "—",
                f"{SYM['err']} Error",
            )
        elif capa_info.already_existed:
            tabla.add_row(
                nombre,
                str(capa_info.num_features),
                crs_str,
                f"{SYM['warn']} Ya existía",
            )
        else:
            tabla.add_row(
                nombre,
                str(capa_info.num_features),
                crs_str,
                f"{SYM['ok']}",
            )

    console.print(tabla)

    # ── Errores detallados ────────────────────────────────────────────────────
    if resultado.capas_error:
        console.print()
        for capa_info in resultado.capas_error:
            nombre = _NOMBRES_CAPA.get(capa_info.capa, capa_info.capa)
            error(f"[bold]{nombre}[/bold]: {capa_info.error}")

    console.print()
    divider()
    next_step("terraf indices")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _short_crs(crs: Optional[str]) -> str:
    """Abrevia un string CRS largo a algo legible."""
    if not crs:
        return "—"
    # "EPSG:32613" → "EPSG:32613"
    if crs.startswith("EPSG:") or len(crs) <= 20:
        return crs
    # WKT largo → extraer AUTHORITY si existe
    import re
    m = re.search(r'AUTHORITY\["(\w+)","(\d+)"\]', crs)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return crs[:20] + "…"


def _rich_box_simple():
    """Retorna el estilo de borde SIMPLE_HEAD de Rich."""
    from rich import box
    return box.SIMPLE_HEAD
