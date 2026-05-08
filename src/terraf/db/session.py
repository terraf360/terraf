"""
Gestión de sesión SQLAlchemy — engine y fábrica de sesiones.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

from terraf.db.models import Base


def make_engine(db_path: Path) -> Engine:
    """Crea un engine SQLite para la ruta dada."""
    url = f"sqlite:///{db_path}"
    return create_engine(url, connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    """
    Crea todas las tablas si no existen y aplica migraciones al esquema actual.

    Seguro de llamar múltiples veces: create_all y las migraciones son idempotentes.
    """
    Base.metadata.create_all(engine)           # crea tablas nuevas
    from terraf.db.migrations import run_all   # aplica ALTER TABLE si hacen falta
    run_all(engine)


def get_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def open_session(db_path: Path) -> Generator[Session, None, None]:
    """
    Context manager que abre una sesión de DB y hace commit/rollback automático.
    Aplica migraciones de esquema automáticamente al abrir.

    Uso:
        with open_session(db_path) as session:
            session.add(...)
    """
    engine = make_engine(db_path)
    init_db(engine)                        # ← migración automática en cada apertura
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def find_db(start: Path | None = None) -> Path | None:
    """
    Busca terraf.db subiendo desde el directorio actual.
    Retorna la ruta si la encuentra, None si no existe proyecto inicializado.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / "terraf.db"
        if candidate.exists():
            return candidate
    return None


def require_db(start: Path | None = None) -> Path:
    """
    Como find_db pero lanza un error rico si no encuentra la DB.
    Usado por los comandos que requieren un proyecto inicializado.
    """
    db_path = find_db(start)
    if db_path is None:
        from rich.console import Console
        import typer
        Console().print(
            "[red]✘[/red] No se encontró un proyecto terraf en este directorio.\n"
            "  Ejecuta [cyan]terraf init <nombre>[/cyan] para inicializar uno."
        )
        raise typer.Exit(1)
    return db_path
