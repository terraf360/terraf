"""
TerraF — Migraciones de esquema automáticas (sin Alembic).

Ejecuta ALTER TABLE / CREATE TABLE para actualizar DBs existentes
al esquema actual de models.py sin destruir datos.

Las migraciones son idempotentes: corren cada vez que se abre la DB
y comprueban si la columna/tabla ya existe antes de aplicar el cambio.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Engine, inspect, text

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Registro de migraciones
# Cada entrada: (descripcion, función_de_migración)
# Se ejecutan en orden y cada una es idempotente.
# ──────────────────────────────────────────────────────────────────────────────

def run_all(engine: Engine) -> None:
    """
    Ejecuta todas las migraciones pendientes en orden.
    Seguro de correr múltiples veces — cada paso comprueba si ya fue aplicado.
    """
    _m01_add_target_ml_columns(engine)
    _m02_create_validaciones_table(engine)


# ──────────────────────────────────────────────────────────────────────────────
# Migración 01 — Añadir columnas ML a la tabla targets
# ──────────────────────────────────────────────────────────────────────────────

def _m01_add_target_ml_columns(engine: Engine) -> None:
    """
    Añade prob_positivo y modelo_version a la tabla targets si no existen.
    Introducidas en M8 (ground truth / ML).
    """
    insp = inspect(engine)
    cols_existentes = {c["name"] for c in insp.get_columns("targets")}

    nuevas: list[tuple[str, str]] = []
    if "prob_positivo" not in cols_existentes:
        nuevas.append(("prob_positivo",  "REAL"))
    if "modelo_version" not in cols_existentes:
        nuevas.append(("modelo_version", "TEXT"))

    if not nuevas:
        return  # ya están — nada que hacer

    with engine.begin() as conn:
        for col, tipo in nuevas:
            conn.execute(text(f"ALTER TABLE targets ADD COLUMN {col} {tipo}"))
            log.info(f"Migración: targets.{col} ({tipo}) añadida")


# ──────────────────────────────────────────────────────────────────────────────
# Migración 02 — Crear tabla validaciones si no existe
# ──────────────────────────────────────────────────────────────────────────────

def _m02_create_validaciones_table(engine: Engine) -> None:
    """
    Crea la tabla validaciones si no existe.
    Introducida en M8.
    """
    insp = inspect(engine)
    if "validaciones" in insp.get_table_names():
        return  # ya existe

    with engine.begin() as conn:
        # Nota: SQLite no admite funciones como DEFAULT en CREATE TABLE via SQLAlchemy text().
        # Se omite el DEFAULT aquí; SQLAlchemy lo gestiona en el ORM (server_default).
        conn.execute(text("""
            CREATE TABLE validaciones (
                id           INTEGER PRIMARY KEY,
                target_id    INTEGER NOT NULL REFERENCES targets(id),
                resultado    TEXT    NOT NULL,
                metodo       TEXT,
                notas        TEXT,
                validado_en  DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_validaciones_target    ON validaciones(target_id)"
        ))
        conn.execute(text(
            "CREATE INDEX idx_validaciones_resultado ON validaciones(resultado)"
        ))
        log.info("Migración: tabla validaciones creada")
