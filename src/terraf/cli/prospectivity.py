"""
terraf prospectivity — Mapa de probabilidad de mineralización.

Combina todas las evidencias disponibles en el proyecto (índices espectrales,
geología, magnetometría, gravimetría) en un mapa continuo de prospectividad
usando lógica difusa.
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
    help="Genera un mapa de probabilidad de mineralización (Mineral Prospectivity Map).",
    invoke_without_command=True,
)


def _parse_pesos(pesos_str: Optional[str]) -> Optional[dict[str, float]]:
    """
    Parsea string 'ior=0.4,clay=0.3,magnetico=0.3' a dict.
    """
    if not pesos_str:
        return None
    out: dict[str, float] = {}
    for parte in pesos_str.split(","):
        if "=" not in parte:
            continue
        k, v = parte.split("=", 1)
        try:
            out[k.strip()] = float(v.strip())
        except ValueError:
            pass
    return out or None


@app.callback(invoke_without_command=True)
def cmd(
    metodo: str = typer.Option(
        "fuzzy",
        "--metodo", "-m",
        help="Método de combinación: fuzzy (recomendado), overlay, and, or.",
    ),
    evidencias: Optional[str] = typer.Option(
        None,
        "--evidencias", "-e",
        help="Lista separada por comas: 'ior,clay,magnetico'. Default: todas las disponibles.",
    ),
    pesos: Optional[str] = typer.Option(
        None,
        "--pesos", "-p",
        help="Pesos por evidencia: 'ior=0.4,clay=0.3,magnetico=0.3'. Se normalizan a 1.",
    ),
    gamma: float = typer.Option(
        0.75,
        "--gamma", "-g",
        help="Parámetro fuzzy gamma (0=AND estricto, 1=OR permisivo). Default 0.75.",
        min=0.0, max=1.0,
    ),
    reduccion: int = typer.Option(
        4,
        "--reduccion", "-r",
        help="Factor de reducción del raster (1=full res, 4=1/4, 8=1/8). Más rápido con valores altos.",
        min=1, max=16,
    ),
    abrir: bool = typer.Option(
        True,
        "--abrir/--no-abrir",
        help="Abrir el mapa en el navegador al terminar.",
    ),
):
    """
    Genera un mapa continuo de probabilidad de mineralización combinando
    todas las evidencias disponibles (índices espectrales, geología,
    magnetometría, gravimetría) con lógica difusa.

    Ejemplos:

      terraf prospectivity                              # todo automático
      terraf prospectivity --evidencias ior,clay,magnetico
      terraf prospectivity --pesos ior=0.5,clay=0.3,magnetico=0.2
      terraf prospectivity --metodo overlay --no-abrir
    """
    from terraf.pipeline.prospectivity import generar_mapa_prospectividad

    db_path = require_db()

    metodo = metodo.lower().strip()
    if metodo not in ("fuzzy", "overlay", "and", "or"):
        error(f"Método no reconocido: '{metodo}'. Usa: fuzzy, overlay, and, or.")
        raise typer.Exit(1)

    evidencias_lista: Optional[list[str]] = None
    if evidencias:
        evidencias_lista = [e.strip() for e in evidencias.split(",") if e.strip()]

    pesos_dict = _parse_pesos(pesos)

    console.print()

    def _on_step(msg: str) -> None:
        prefijo = (
            f"  {SYM['warn']}  " if "ADVERTENCIA" in msg or "skip" in msg.lower()
            else "  [muted]·[/muted]  "
        )
        console.print(f"{prefijo}[muted]{msg}[/muted]")

    with console.status("[accent]Construyendo mapa de prospectividad...[/accent]"):
        try:
            resultado = generar_mapa_prospectividad(
                db_path=db_path,
                metodo=metodo,
                evidencias_solicitadas=evidencias_lista,
                pesos_custom=pesos_dict,
                gamma=gamma,
                reduccion=reduccion,
                on_step=_on_step,
            )
        except RuntimeError as exc:
            error(str(exc))
            raise typer.Exit(1)
        except Exception as exc:
            error(f"Error inesperado: {exc}")
            raise typer.Exit(1)

    console.print()
    success(f"Mapa de prospectividad generado")
    console.print()
    divider()
    console.print()

    # ── Resumen ──────────────────────────────────────────────────────────────
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="muted", justify="right", min_width=18)
    tabla.add_column()

    tabla.add_row("Método:",      f"[accent]{resultado.metodo}[/accent]")
    tabla.add_row("Evidencias:",  f"[accent]{', '.join(resultado.evidencias_usadas)}[/accent]")
    tabla.add_row("Raster:",      f"[muted]{resultado.raster_path}[/muted]")
    tabla.add_row("Mapa HTML:",   f"[muted]{resultado.html_path}[/muted]")
    console.print(tabla)
    console.print()

    # Tabla de pesos
    tpesos = Table(
        show_header=True, header_style="bold",
        border_style="dim", box=box.SIMPLE_HEAD,
    )
    tpesos.add_column("Evidencia",  style="accent",  min_width=14)
    tpesos.add_column("Peso (%)",   justify="right", min_width=10)
    for ev, p in resultado.pesos_normalizados.items():
        tpesos.add_row(ev, f"{p*100:.1f}%")
    console.print("  [muted]Pesos normalizados:[/muted]")
    console.print(tpesos)
    console.print()

    # Estadísticas
    e = resultado.estadisticas
    tstats = Table.grid(padding=(0, 2))
    tstats.add_column(style="muted", justify="right", min_width=22)
    tstats.add_column()
    tstats.add_row("Probabilidad mín:",        f"[muted]{e['min']:.3f}[/muted]")
    tstats.add_row("Probabilidad máx:",        f"[muted]{e['max']:.3f}[/muted]")
    tstats.add_row("Probabilidad media:",      f"[muted]{e['media']:.3f}[/muted]")
    tstats.add_row("% área con p > 0.70:",     f"[accent]{e['p_alta']*100:.2f}%[/accent]")
    tstats.add_row("% área con p > 0.85:",     f"[accent]{e['p_muy_alta']*100:.3f}%[/accent]")
    console.print("  [muted]Estadísticas del mapa:[/muted]")
    console.print(tstats)
    console.print()

    divider()

    if abrir:
        webbrowser.open(resultado.html_path.as_uri())
        console.print(f"  {SYM['arrow']}  Abriendo mapa en el navegador...")
        console.print()

    next_step(
        "terraf analyze",
        extra="para extraer targets desde el mapa de probabilidad",
    )
