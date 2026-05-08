"""
terraf status — Muestra el estado actual del pipeline.
"""

import typer

from terraf.cli.art import SYM, console, divider
from terraf.db.session import require_db
from terraf.pipeline.project import get_project_status

app = typer.Typer(help="Muestra el estado actual del proyecto.")


@app.callback(invoke_without_command=True)
def cmd():
    """Muestra qué pasos del pipeline se han completado."""
    db_path = require_db()
    s = get_project_status(db_path)

    console.print()
    console.print(f"  [bold]Proyecto:[/bold] [accent]{s.nombre}[/accent]")
    console.print()
    divider()
    console.print()

    # ── Pasos del pipeline ────────────────────────────────────────────────────
    img = s.imagen

    _step(
        done=img is not None,
        label="Imagen satelital",
        detail=f"[accent]{img.scene_id}[/accent]  [muted]{img.sensor} · {img.fecha_adquisicion}[/muted]" if img else None,
        hint="terraf load <ruta>",
    )

    _step(
        done=s.num_capas_geo > 0,
        label="Datos geológicos",
        detail=f"[accent]{s.num_capas_geo} capa(s) SGM[/accent]" if s.num_capas_geo else None,
        hint="terraf geology <ruta>",
    )

    _step(
        done=s.num_indices > 0,
        label="Índices espectrales",
        detail=f"[accent]{s.num_indices} índice(s) calculados[/accent]" if s.num_indices else None,
        hint="terraf indices",
    )

    _step(
        done=s.ultimo_analisis is not None,
        label="Análisis de targets",
        detail=f"[accent]{s.num_targets} target(s) identificados[/accent]" if s.ultimo_analisis else None,
        hint="terraf analyze",
    )

    _step(
        done=s.exportado,
        label="Exportación",
        detail="[accent]GeoJSON · Shapefile[/accent]" if s.exportado else None,
        hint="terraf export",
    )

    # ── Siguiente paso ────────────────────────────────────────────────────────
    console.print()
    divider()
    console.print()

    if img is None:
        _next("terraf load <ruta_imagen>")
    elif s.num_indices == 0 and s.num_capas_geo == 0:
        _next("terraf geology <ruta>", alt="terraf indices  (sin datos SGM)")
    elif s.num_indices == 0:
        _next("terraf indices")
    elif s.ultimo_analisis is None:
        _next("terraf analyze")
    elif not s.exportado:
        _next("terraf export", alt="terraf report  para ver resultados en terminal")
    else:
        console.print(f"  {SYM['ok']}  [primary]Pipeline completo.[/primary]")

    console.print()


# ── Helpers locales ───────────────────────────────────────────────────────────

def _step(done: bool, label: str, detail: str | None, hint: str) -> None:
    sym = SYM["ok"] if done else SYM["pending"]
    if done:
        console.print(f"  {sym}  [bold]{label}[/bold]")
        if detail:
            console.print(f"       {detail}")
    else:
        console.print(f"  {sym}  [muted]{label}[/muted]")
        console.print(f"       [muted]→ {hint}[/muted]")


def _next(cmd: str, alt: str | None = None) -> None:
    console.print(f"  [muted]Siguiente paso:[/muted]  [accent]{cmd}[/accent]")
    if alt:
        console.print(f"  [muted]           o:[/muted]  [muted]{alt}[/muted]")
