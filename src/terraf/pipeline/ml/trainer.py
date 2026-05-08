"""
Pipeline ML — M10: Entrenamiento del modelo de clasificación.

Estrategia de entrenamiento:
  1. Genera muestras sintéticas con los priors espectrales del tipo de depósito.
  2. Si hay datos de campo reales (validaciones), los añade con peso mayor.
  3. Entrena un RandomForestClassifier (scikit-learn).
  4. Guarda el modelo + metadatos en modelos/<version>.pkl.

Uso:
    from terraf.pipeline.ml.trainer import entrenar
    info = entrenar(db_path, tipo_deposito="porfido_cu")
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from terraf.pipeline.ml.features import (
    DatasetML,
    apply_normalization,
    extract_features,
    normalize_features,
)
from terraf.pipeline.ml.priors import generate_synthetic_samples


# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

# Versión del esquema del artefacto guardado (bump al cambiar estructura)
_ARTIFACT_VERSION = "1"

# Carpeta relativa al directorio de trabajo donde se guardan los modelos
_MODELOS_DIR = Path("modelos")

# Número de muestras sintéticas por clase cuando no hay datos reales
_N_SYNTH_DEFAULT = 100

# Peso relativo de las muestras reales sobre las sintéticas
_PESO_REAL = 5.0


# ──────────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ModeloInfo:
    version: str
    ruta_pkl: Path
    tipo_deposito: str
    n_sinteticos: int
    n_reales: int
    n_total: int
    score_cv: Optional[float]           # accuracy CV estimada (None si < 5 muestras reales)
    feature_names: list[str]
    min_vals: list[float]
    max_vals: list[float]
    entrenado_en: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class _Artifact:
    """Lo que se serializa en el .pkl"""
    schema_version: str
    model: object                        # RandomForestClassifier
    min_vals: np.ndarray
    max_vals: np.ndarray
    feature_names: list[str]
    tipo_deposito: str
    entrenado_en: str
    n_sinteticos: int
    n_reales: int


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def entrenar(
    db_path: Path,
    tipo_deposito: str = "generico",
    analisis_id: Optional[int] = None,
    n_sinteticos: int = _N_SYNTH_DEFAULT,
    on_step: Optional[Callable[[str], None]] = None,
) -> ModeloInfo:
    """
    Entrena el modelo de clasificación y lo guarda en disco.

    Args:
        db_path:        Ruta al terraf.db.
        tipo_deposito:  Tipo de depósito (default: "generico").
        analisis_id:    Análisis específico (default: último).
        n_sinteticos:   Muestras sintéticas por clase.
        on_step:        Callback(mensaje) para reportar progreso.

    Returns:
        ModeloInfo con metadatos del modelo guardado.

    Raises:
        RuntimeError: Si scikit-learn no está instalado o no hay análisis.
        ImportError:  Si scikit-learn no está disponible.
    """
    _step(on_step, "Cargando scikit-learn…")
    rf_cls = _load_sklearn()

    # ── Paso 1: Extraer features de la DB ─────────────────────────────────────
    _step(on_step, "Extrayendo características de los targets…")
    dataset = extract_features(db_path, analisis_id=analisis_id)

    # Separar targets con etiqueta real (positivo=1 / negativo=0)
    X_real, y_real = _get_labeled_real(dataset)
    n_reales = len(y_real) if y_real is not None else 0

    # ── Paso 2: Generar datos sintéticos ──────────────────────────────────────
    _step(on_step, f"Generando {n_sinteticos*2} muestras sintéticas ({tipo_deposito})…")
    X_synth, y_synth = generate_synthetic_samples(
        tipo_deposito=tipo_deposito,
        n_positivos=n_sinteticos,
        n_negativos=n_sinteticos,
    )

    # ── Paso 3: Combinar y normalizar ─────────────────────────────────────────
    _step(on_step, "Combinando datos y normalizando…")
    X_comb, y_comb, sample_weights = _combine(X_synth, y_synth, X_real, y_real)

    X_norm, min_vals, max_vals = normalize_features(X_comb)

    # ── Paso 4: Entrenar RandomForest ─────────────────────────────────────────
    _step(on_step, "Entrenando RandomForest…")
    rf = rf_cls(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=3,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_norm, y_comb, sample_weight=sample_weights)

    # CV rápida solo si hay suficientes datos reales
    score_cv: Optional[float] = None
    if n_reales >= 6:
        score_cv = _cross_val_score(rf_cls, X_norm, y_comb, sample_weights)
        _step(on_step, f"CV accuracy estimada: {score_cv:.2%}")

    # ── Paso 5: Guardar artefacto ──────────────────────────────────────────────
    _step(on_step, "Guardando modelo…")
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_pkl = _guardar_artefacto(
        model=rf,
        min_vals=min_vals,
        max_vals=max_vals,
        feature_names=dataset.feature_names,
        tipo_deposito=tipo_deposito,
        version=version,
        n_sinteticos=n_sinteticos * 2,
        n_reales=n_reales,
    )

    return ModeloInfo(
        version=version,
        ruta_pkl=ruta_pkl,
        tipo_deposito=tipo_deposito,
        n_sinteticos=n_sinteticos * 2,
        n_reales=n_reales,
        n_total=len(y_comb),
        score_cv=score_cv,
        feature_names=dataset.feature_names,
        min_vals=min_vals.tolist(),
        max_vals=max_vals.tolist(),
        entrenado_en=version,
    )


def cargar_ultimo_modelo(base_dir: Optional[Path] = None) -> "_Artifact":
    """
    Carga el modelo más reciente guardado en modelos/.

    Args:
        base_dir: Directorio base (default: cwd).

    Returns:
        _Artifact con modelo y metadatos.

    Raises:
        FileNotFoundError: Si no hay modelos guardados.
    """
    mod_dir = (base_dir or Path.cwd()) / _MODELOS_DIR
    pkls = sorted(mod_dir.glob("modelo_*.pkl"), reverse=True)
    if not pkls:
        raise FileNotFoundError(
            f"No hay modelos entrenados en {mod_dir}.\n"
            "Ejecuta 'terraf train' primero."
        )
    with open(pkls[0], "rb") as f:
        artifact: _Artifact = pickle.load(f)
    return artifact


def listar_modelos(base_dir: Optional[Path] = None) -> list[dict]:
    """
    Lista todos los modelos guardados con sus metadatos básicos.

    Returns:
        Lista de dicts con: version, tipo_deposito, entrenado_en, n_reales, ruta.
    """
    mod_dir = (base_dir or Path.cwd()) / _MODELOS_DIR
    if not mod_dir.exists():
        return []

    resultado = []
    for pkl in sorted(mod_dir.glob("modelo_*.pkl"), reverse=True):
        try:
            with open(pkl, "rb") as f:
                art: _Artifact = pickle.load(f)
            meta_file = pkl.with_suffix(".json")
            extra: dict = {}
            if meta_file.exists():
                with open(meta_file) as mf:
                    extra = json.load(mf)
            resultado.append({
                "version":       art.entrenado_en,
                "tipo_deposito": art.tipo_deposito,
                "entrenado_en":  art.entrenado_en,
                "n_reales":      art.n_reales,
                "n_sinteticos":  art.n_sinteticos,
                "ruta":          str(pkl),
                **extra,
            })
        except Exception:
            continue

    return resultado


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _load_sklearn():
    """Importa RandomForestClassifier o lanza ImportError amigable."""
    try:
        from sklearn.ensemble import RandomForestClassifier  # noqa: PLC0415
        return RandomForestClassifier
    except ImportError:
        raise ImportError(
            "scikit-learn no está instalado.\n"
            "  Instálalo con: pip install scikit-learn"
        )


def _get_labeled_real(
    dataset: DatasetML,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Extrae solo los targets con etiqueta real (1 o 0, excluye -1).
    Retorna (None, None) si no hay etiquetas útiles.
    """
    if dataset.y is None:
        return None, None

    mask = dataset.y >= 0  # excluye -1 (sin etiqueta)
    if mask.sum() == 0:
        return None, None

    return dataset.X[mask], dataset.y[mask].astype(np.int8)


def _combine(
    X_synth: np.ndarray,
    y_synth: np.ndarray,
    X_real: Optional[np.ndarray],
    y_real: Optional[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Combina datos sintéticos y reales con pesos diferenciados.
    Los datos reales tienen peso _PESO_REAL veces mayor.
    """
    w_synth = np.ones(len(y_synth), dtype=np.float32)

    if X_real is not None and len(X_real) > 0:
        w_real = np.full(len(y_real), _PESO_REAL, dtype=np.float32)
        X_comb = np.vstack([X_synth, X_real])
        y_comb = np.concatenate([y_synth, y_real])
        w_comb = np.concatenate([w_synth, w_real])
    else:
        X_comb = X_synth
        y_comb = y_synth
        w_comb = w_synth

    return X_comb, y_comb.astype(np.int8), w_comb


def _cross_val_score(rf_cls, X: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """CV de 3-fold simplificada sin sklearn.model_selection para ser ligera."""
    try:
        from sklearn.model_selection import cross_val_score  # noqa: PLC0415
        rf_cv = rf_cls(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
        scores = cross_val_score(rf_cv, X, y, cv=3, scoring="accuracy")
        return float(scores.mean())
    except Exception:
        return 0.0


def _guardar_artefacto(
    model,
    min_vals: np.ndarray,
    max_vals: np.ndarray,
    feature_names: list[str],
    tipo_deposito: str,
    version: str,
    n_sinteticos: int,
    n_reales: int,
) -> Path:
    """Serializa el artefacto y guarda metadatos JSON paralelo."""
    mod_dir = Path.cwd() / _MODELOS_DIR
    mod_dir.mkdir(parents=True, exist_ok=True)

    artifact = _Artifact(
        schema_version=_ARTIFACT_VERSION,
        model=model,
        min_vals=min_vals,
        max_vals=max_vals,
        feature_names=feature_names,
        tipo_deposito=tipo_deposito,
        entrenado_en=version,
        n_sinteticos=n_sinteticos,
        n_reales=n_reales,
    )

    ruta_pkl = mod_dir / f"modelo_{version}.pkl"
    with open(ruta_pkl, "wb") as f:
        pickle.dump(artifact, f, protocol=5)

    # JSON con metadatos legibles
    meta = {
        "schema_version": _ARTIFACT_VERSION,
        "tipo_deposito":  tipo_deposito,
        "entrenado_en":   version,
        "n_sinteticos":   n_sinteticos,
        "n_reales":       n_reales,
        "feature_names":  feature_names,
        "min_vals":       min_vals.tolist(),
        "max_vals":       max_vals.tolist(),
    }
    with open(ruta_pkl.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return ruta_pkl


def _step(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        cb(msg)
