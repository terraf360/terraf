"""
terraf db — Consultas directas a la base de datos del proyecto.

Subcomandos:
  tables  Lista las tablas con su conteo de registros.
  stats   Estadísticas resumidas del contenido de la DB.
  query   Ejecuta SQL arbitrario y muestra el resultado.
"""

from __future__ import annotations

import typer
from rich import box
from rich.table import Table

from terraf.cli.art import console, divider, error, success
from terraf.db.session import make_engine, require_db

app = typer.Typer(help="Consultas directas a la base de datos.")

# Orden de display para `stats`
_TABLA_LABELS = {
    "proyectos":          "Proyectos",
    "imagenes":           "Imágenes",
    "datos_geologicos":   "Capas geológicas",
    "features_geologicos":"Features geológicos",
    "indices_espectrales":"Índices espectrales",
    "analisis":           "Análisis",
    "targets":            "Targets",
}


# ──────────────────────────────────────────────────────────────────────────────
# terraf db tables
# ──────────────────────────────────────────────────────────────────────────────

@app.command("tables")
def tables():
    """Lista las tablas disponibles con su conteo de registros."""
    from sqlalchemy import inspect, text  # noqa: PLC0415

    db_path = require_db()
    engine  = make_engine(db_path)

    console.print()

    try:
        inspector   = inspect(engine)
        table_names = inspector.get_table_names()
    except Exception as exc:
        error(f"No se pudo inspeccionar la DB: {exc}")
        raise typer.Exit(1)

    t = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    t.add_column("Tabla",    style="accent", min_width=24)
    t.add_column("Registros", justify="right", min_width=12)

    with engine.connect() as conn:
        for name in sorted(table_names):
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            except Exception:
                count = "—"
            label = _TABLA_LABELS.get(name, name)
            t.add_row(label, str(count))

    console.print(t)
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# terraf db stats
# ──────────────────────────────────────────────────────────────────────────────

@app.command("stats")
def stats():
    """Muestra estadísticas generales del contenido de la base de datos."""
    from sqlalchemy import text  # noqa: PLC0415

    db_path = require_db()
    engine  = make_engine(db_path)

    console.print()

    with engine.connect() as conn:
        def _q(sql: str):
            try:
                return conn.execute(text(sql)).scalar()
            except Exception:
                return None

        # Datos clave
        n_imagenes   = _q("SELECT COUNT(*) FROM imagenes")
        n_indices    = _q("SELECT COUNT(*) FROM indices_espectrales")
        n_analisis   = _q("SELECT COUNT(*) FROM analisis")
        n_targets    = _q("SELECT COUNT(*) FROM targets")
        n_geo        = _q("SELECT COUNT(*) FROM datos_geologicos")
        n_features   = _q("SELECT COUNT(*) FROM features_geologicos")

        alta  = _q("SELECT COUNT(*) FROM targets WHERE prioridad='ALTA'")
        media = _q("SELECT COUNT(*) FROM targets WHERE prioridad='MEDIA'")
        baja  = _q("SELECT COUNT(*) FROM targets WHERE prioridad='BAJA'")

        area_total  = _q("SELECT SUM(area_ha) FROM targets")
        score_max   = _q("SELECT MAX(score) FROM targets")
        score_med   = _q("SELECT AVG(score) FROM targets")

        scene_id    = _q("SELECT scene_id FROM imagenes ORDER BY cargada_en DESC LIMIT 1")
        nombre_proj = _q("SELECT nombre FROM proyectos LIMIT 1")

    # ── Encabezado ─────────────────────────────────────────────────────────────
    if nombre_proj:
        console.print(f"  [bold]Proyecto:[/bold] [accent]{nombre_proj}[/accent]")
        console.print()

    divider()
    console.print()

    # ── Grid de estadísticas ───────────────────────────────────────────────────
    grid = Table.grid(padding=(0, 4))
    grid.add_column(style="muted", justify="right", min_width=24)
    grid.add_column()

    def _row(label: str, val, style: str = "accent") -> None:
        grid.add_row(f"{label}:", f"[{style}]{val}[/{style}]" if val is not None else "[dim]—[/dim]")

    _row("Imagen cargada",    scene_id or "ninguna")
    _row("Índices calculados", n_indices or 0)
    _row("Análisis ejecutados", n_analisis or 0)
    grid.add_row("", "")
    _row("Targets totales",   n_targets or 0)
    _row("  Prioridad ALTA",  alta or 0, "bold green")
    _row("  Prioridad MEDIA", media or 0, "bold yellow")
    _row("  Prioridad BAJA",  baja or 0, "dim")
    if area_total:
        _row("Área total de interés", f"{area_total:.2f} ha")
    if score_max:
        _row("Score máximo",  f"{score_max:.3f}")
    if score_med:
        _row("Score promedio", f"{score_med:.3f}")
    grid.add_row("", "")
    _row("Capas geológicas",      n_geo or 0)
    _row("Features geológicos",   n_features or 0)

    console.print(grid)
    console.print()
    divider()
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# terraf db query
# ──────────────────────────────────────────────────────────────────────────────

@app.command("query")
def query(
    sql: str = typer.Argument(..., help='Sentencia SQL. Ej: "SELECT * FROM targets LIMIT 5"'),
    limit: int = typer.Option(50, "--limit", "-n", help="Máximo de filas a mostrar (default: 50)"),
):
    """Ejecuta una sentencia SQL y muestra el resultado como tabla."""
    from sqlalchemy import text  # noqa: PLC0415

    db_path = require_db()
    engine  = make_engine(db_path)

    console.print()

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            cols   = list(result.keys())
            rows   = result.fetchmany(limit)
    except Exception as exc:
        error(f"Error al ejecutar SQL:\n  {exc}")
        raise typer.Exit(1)

    if not rows:
        console.print("  [muted](Sin resultados)[/muted]")
        console.print()
        raise typer.Exit(0)

    t = Table(
        show_header=True,
        header_style="bold",
        border_style="dim",
        box=box.SIMPLE_HEAD,
    )
    for col in cols:
        t.add_column(str(col), overflow="fold", max_width=40)

    for row in rows:
        t.add_row(*[str(v) if v is not None else "—" for v in row])

    console.print(t)

    if len(rows) == limit:
        console.print(
            f"  [muted](Mostrando primeras {limit} filas. "
            "Usa --limit N para ver más.)[/muted]"
        )
    console.print()
