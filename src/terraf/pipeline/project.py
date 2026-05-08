"""
Lógica de negocio para init y status del proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from terraf.db.models import Analisis, DatoGeologico, Imagen, IndiceEspectral, Proyecto, Target
from terraf.db.session import init_db, make_engine, open_session
import terraf.config as cfg_module

# Directorios que crea terraf init
PROJECT_DIRS = [
    "datos",
    "resultados/indices",
    "resultados/targets",
    "resultados/visualizaciones",
    "resultados/reportes",
]


# ──────────────────────────────────────────────────────────────────────────────
# init_project
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class InitResult:
    already_existed: bool
    project_dir: Path
    db_path: Path
    config_path: Path
    nombre: str


def init_project(nombre: str, directory: Path | None = None) -> InitResult:
    """
    Inicializa un nuevo proyecto de exploración.

    Si `directory` es None (uso normal desde CLI), crea una SUBCARPETA con
    el nombre del proyecto dentro del directorio actual, igual que `git init`.
    Ejemplo: `terraf init zacatecas` en ~/Documents crea ~/Documents/zacatecas/

    Si `directory` se pasa explícitamente, se usa ese directorio tal cual
    (útil para tests o integración programática).

    Si el proyecto ya existe (detectado por terraf.toml), retorna
    InitResult con already_existed=True sin modificar nada.
    """
    if directory is not None:
        project_dir = directory.resolve()
    else:
        # Comportamiento estándar: subcarpeta con el nombre del proyecto
        project_dir = (Path.cwd() / nombre).resolve()
    config_path = project_dir / "terraf.toml"
    db_path = project_dir / "terraf.db"

    # ── Idempotencia ──────────────────────────────────────────────────────────
    if config_path.exists():
        existing_cfg = cfg_module.load(config_path)
        existing_nombre = existing_cfg.get("proyecto", {}).get("nombre", nombre)
        return InitResult(
            already_existed=True,
            project_dir=project_dir,
            db_path=db_path,
            config_path=config_path,
            nombre=existing_nombre,
        )

    # ── Crear directorios ─────────────────────────────────────────────────────
    for rel in PROJECT_DIRS:
        (project_dir / rel).mkdir(parents=True, exist_ok=True)

    # ── Crear base de datos y tablas ──────────────────────────────────────────
    engine = make_engine(db_path)
    init_db(engine)
    engine.dispose()

    # ── Crear terraf.toml ─────────────────────────────────────────────────────
    cfg_module.create_default(nombre, config_path)

    # ── Registrar proyecto en la DB ───────────────────────────────────────────
    with open_session(db_path) as session:
        session.add(Proyecto(nombre=nombre, directorio=str(project_dir)))

    return InitResult(
        already_existed=False,
        project_dir=project_dir,
        db_path=db_path,
        config_path=config_path,
        nombre=nombre,
    )


# ──────────────────────────────────────────────────────────────────────────────
# get_project_status
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineStatus:
    nombre: str
    imagen: Imagen | None
    num_capas_geo: int
    num_indices: int
    ultimo_analisis: Analisis | None
    num_targets: int
    exportado: bool


def get_project_status(db_path: Path) -> PipelineStatus:
    """Lee el estado actual del pipeline desde la base de datos."""
    with open_session(db_path) as session:
        proyecto = session.scalar(select(Proyecto).limit(1))
        nombre = proyecto.nombre if proyecto else "sin nombre"

        imagen = session.scalar(
            select(Imagen).where(Imagen.proyecto_id == proyecto.id).limit(1)
        ) if proyecto else None

        from sqlalchemy import func as sqlfunc
        num_capas_geo = session.execute(
            select(sqlfunc.count()).select_from(DatoGeologico)
            .where(DatoGeologico.proyecto_id == proyecto.id)
        ).scalar() if proyecto else 0

        num_indices = session.execute(
            select(sqlfunc.count()).select_from(IndiceEspectral)
            .join(Imagen)
            .where(Imagen.proyecto_id == proyecto.id)
        ).scalar() if proyecto else 0

        ultimo_analisis = session.scalar(
            select(Analisis)
            .where(Analisis.proyecto_id == proyecto.id)
            .order_by(Analisis.ejecutado_en.desc())
            .limit(1)
        ) if proyecto else None

        num_targets = session.execute(
            select(sqlfunc.count()).select_from(Target)
            .join(Analisis)
            .where(Analisis.proyecto_id == proyecto.id)
        ).scalar() if proyecto else 0

        # Exportado = existe algún archivo en resultados/targets/
        project_dir = Path(proyecto.directorio) if proyecto else db_path.parent
        targets_dir = project_dir / "resultados" / "targets"
        exportado = targets_dir.exists() and any(targets_dir.iterdir())

    return PipelineStatus(
        nombre=nombre,
        imagen=imagen,
        num_capas_geo=num_capas_geo,
        num_indices=num_indices,
        ultimo_analisis=ultimo_analisis,
        num_targets=num_targets,
        exportado=exportado,
    )
