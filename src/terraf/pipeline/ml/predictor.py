"""
Pipeline ML — M11: Inferencia del modelo sobre todos los targets.

Carga el modelo más reciente, aplica la normalización, predice
prob_positivo para cada target y actualiza el campo en la DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from terraf.db.models import Analisis, Target
from terraf.db.session import open_session
from terraf.pipeline.ml.features import apply_normalization, extract_features


# ──────────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PrediccionInfo:
    n_targets: int
    version_modelo: str
    tipo_deposito: str
    prob_media: float
    prob_max: float
    prob_min: float
    n_alta: int      # prob_positivo >= 0.70
    n_media: int     # 0.40 <= prob < 0.70
    n_baja: int      # prob < 0.40


@dataclass
class TargetPrediccion:
    target_id: int
    nombre: str
    prob_positivo: float
    score_original: float


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def predecir(
    db_path: Path,
    analisis_id: Optional[int] = None,
    modelo_path: Optional[Path] = None,
    on_step: Optional[Callable[[str], None]] = None,
) -> PrediccionInfo:
    """
    Predice prob_positivo para todos los targets y actualiza la DB.

    Args:
        db_path:      Ruta al terraf.db.
        analisis_id:  Análisis específico (default: último).
        modelo_path:  Ruta explícita a un .pkl (default: modelo más reciente).
        on_step:      Callback(msg) para progreso.

    Returns:
        PrediccionInfo con resumen de predicciones.

    Raises:
        FileNotFoundError: Si no hay modelo entrenado.
        RuntimeError:      Si no hay análisis en la DB.
    """
    from terraf.pipeline.ml.trainer import cargar_ultimo_modelo  # noqa: PLC0415

    # ── Paso 1: Cargar modelo ──────────────────────────────────────────────────
    _step(on_step, "Cargando modelo…")
    if modelo_path:
        import pickle  # noqa: PLC0415
        with open(modelo_path, "rb") as f:
            artifact = pickle.load(f)
    else:
        artifact = cargar_ultimo_modelo()

    version = artifact.entrenado_en
    tipo    = artifact.tipo_deposito

    # ── Paso 2: Extraer features ───────────────────────────────────────────────
    _step(on_step, "Extrayendo características de los targets…")
    dataset = extract_features(db_path, analisis_id=analisis_id)

    if dataset.n_targets == 0:
        raise RuntimeError(
            "No hay targets en el análisis. Ejecuta 'terraf analyze' primero."
        )

    # ── Paso 3: Normalizar con los parámetros del modelo ──────────────────────
    _step(on_step, "Normalizando features…")
    X_norm = apply_normalization(
        dataset.X,
        artifact.min_vals,
        artifact.max_vals,
    )

    # ── Paso 4: Predecir probabilidades ───────────────────────────────────────
    _step(on_step, f"Prediciendo {dataset.n_targets} targets…")
    try:
        probs = artifact.model.predict_proba(X_norm)[:, 1]  # prob clase positiva
    except Exception as exc:
        raise RuntimeError(f"Error durante la predicción: {exc}") from exc

    # ── Paso 5: Actualizar DB ─────────────────────────────────────────────────
    _step(on_step, "Actualizando base de datos…")
    _update_db(
        db_path=db_path,
        analisis_id=analisis_id,
        target_ids=dataset.target_ids,
        probs=probs,
        version=version,
    )

    # ── Resumen ────────────────────────────────────────────────────────────────
    n_alta  = int((probs >= 0.70).sum())
    n_media = int(((probs >= 0.40) & (probs < 0.70)).sum())
    n_baja  = int((probs < 0.40).sum())

    return PrediccionInfo(
        n_targets=dataset.n_targets,
        version_modelo=version,
        tipo_deposito=tipo,
        prob_media=float(probs.mean()),
        prob_max=float(probs.max()),
        prob_min=float(probs.min()),
        n_alta=n_alta,
        n_media=n_media,
        n_baja=n_baja,
    )


def obtener_predicciones(
    db_path: Path,
    analisis_id: Optional[int] = None,
    top_n: int = 20,
) -> list[TargetPrediccion]:
    """
    Retorna los targets ordenados por prob_positivo descendente.

    Args:
        db_path:      Ruta al terraf.db.
        analisis_id:  Análisis específico (default: último).
        top_n:        Máximo de targets a retornar.

    Returns:
        Lista de TargetPrediccion ordenada por prob_positivo desc.
    """
    with open_session(db_path) as session:
        q = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            q = q.filter_by(id=analisis_id)
        analisis = q.first()

        if analisis is None:
            raise RuntimeError(
                "No hay análisis registrado. Ejecuta 'terraf analyze' primero."
            )

        targets = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .filter(Target.prob_positivo.isnot(None))
            .order_by(Target.prob_positivo.desc())
            .limit(top_n)
            .all()
        )

        return [
            TargetPrediccion(
                target_id=t.id,
                nombre=t.nombre or f"T{t.id}",
                prob_positivo=float(t.prob_positivo),
                score_original=float(t.score or 0.0),
            )
            for t in targets
        ]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _update_db(
    db_path: Path,
    analisis_id: Optional[int],
    target_ids: list[int],
    probs: np.ndarray,
    version: str,
) -> None:
    """Escribe prob_positivo y modelo_version en cada Target."""
    with open_session(db_path) as session:
        for tid, prob in zip(target_ids, probs):
            t = session.query(Target).filter_by(id=tid).first()
            if t is not None:
                t.prob_positivo  = float(prob)
                t.modelo_version = version
        session.flush()


def _step(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        cb(msg)
