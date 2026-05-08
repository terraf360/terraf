"""
Pipeline ML — M9a: Feature engineering para targets.

Extrae un vector de características por target usando:
  - Índices espectrales medios ya almacenados en la DB (ior_media, clay_media)
  - Estadísticas de índices_espectrales (si están disponibles)
  - Atributos geométricos (área, score compuesto)
  - Contexto geológico (litología dominante codificada)

El resultado es un DataFrame con una fila por target y columnas numéricas
listas para entrenar scikit-learn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from terraf.db.models import Analisis, IndiceEspectral, Target
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

# Nombres de columnas del vector de características (en orden fijo)
FEATURE_NAMES: list[str] = [
    "ior_media",
    "clay_media",
    "ferrous_media",
    "ndvi_media",
    "ndwi_media",
    "evi_media",
    "savi_media",
    "area_ha",
    "score",
    "lit_favoreciable",   # 1.0 si litología dominante es favorable, else 0.0
]

# Litologías consideradas favorables para exploración cuprífero/aurífero genérica
_LIT_FAVORABLES = {
    "andesita", "riolita", "porfido", "granodiorita", "granito",
    "diorita", "tonalita", "monzonita", "dacita", "cuarcita",
    "skarn", "brecha", "volcanico", "volcanica",
}


# ──────────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TargetFeatures:
    target_id: int
    nombre: str
    features: np.ndarray           # shape (len(FEATURE_NAMES),)
    etiqueta: Optional[str] = None # "positivo" | "negativo" | "dudoso" | None


@dataclass
class DatasetML:
    """Resultado de extract_features() — contiene X, y y metadatos."""
    target_ids: list[int]
    nombres: list[str]
    X: np.ndarray                  # shape (n_targets, n_features)
    y: Optional[np.ndarray] = None # shape (n_labeled,) — None si no hay etiquetas
    etiquetas_raw: list[Optional[str]] = field(default_factory=list)
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))

    @property
    def n_labeled(self) -> int:
        return sum(1 for e in self.etiquetas_raw if e in ("positivo", "negativo"))

    @property
    def n_targets(self) -> int:
        return len(self.target_ids)


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def extract_features(
    db_path: Path,
    analisis_id: Optional[int] = None,
    incluir_dudosos: bool = False,
) -> DatasetML:
    """
    Extrae el vector de características para todos los targets de un análisis.

    Args:
        db_path:          Ruta al terraf.db.
        analisis_id:      Análisis específico (default: último).
        incluir_dudosos:  Si True, los targets 'dudoso' se tratan como no etiquetados.

    Returns:
        DatasetML con X (features), y (etiquetas binarias 1/0 donde existen)
        y metadatos.

    Raises:
        RuntimeError: Si no hay análisis en la DB.
    """
    with open_session(db_path) as session:
        # Obtener análisis
        q = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            q = q.filter_by(id=analisis_id)
        analisis = q.first()

        if analisis is None:
            raise RuntimeError(
                "No hay análisis registrado. Ejecuta 'terraf analyze' primero."
            )

        # Cargar índices espectrales del análisis (para complementar medias)
        indices_por_nombre = _load_indices_stats(session, analisis.imagen_id)

        # Cargar targets con validaciones
        targets = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .order_by(Target.score.desc())
            .all()
        )

        rows_features: list[np.ndarray] = []
        target_ids: list[int] = []
        nombres: list[str] = []
        etiquetas_raw: list[Optional[str]] = []

        for t in targets:
            vec = _build_feature_vector(t, indices_por_nombre)
            rows_features.append(vec)
            target_ids.append(t.id)
            nombres.append(t.nombre or f"T{t.id}")

            # Etiqueta desde validaciones (toma la primera / única)
            val = t.validaciones[0] if t.validaciones else None
            etiquetas_raw.append(val.resultado if val else None)

        X = np.array(rows_features, dtype=np.float32)

        # Construir y binario (1=positivo, 0=negativo) solo donde hay etiqueta útil
        y = _build_y(etiquetas_raw, incluir_dudosos)

        return DatasetML(
            target_ids=target_ids,
            nombres=nombres,
            X=X,
            y=y,
            etiquetas_raw=etiquetas_raw,
            feature_names=list(FEATURE_NAMES),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _load_indices_stats(session, imagen_id: int) -> dict[str, dict]:
    """
    Carga estadísticas de índices_espectrales para una imagen.
    Retorna dict: nombre_indice -> {media, min_val, max_val, ...}
    """
    indices = session.query(IndiceEspectral).filter_by(imagen_id=imagen_id).all()
    return {
        i.nombre_indice: {
            "media":    i.media,
            "min_val":  i.min_val,
            "max_val":  i.max_val,
            "desv_std": i.desv_std,
        }
        for i in indices
    }


def _build_feature_vector(
    target: Target,
    indices_stats: dict[str, dict],
) -> np.ndarray:
    """
    Construye el vector de features para un target.

    Prioridad de valores por índice:
    1. Valor almacenado directamente en target (ior_media, clay_media)
    2. Media global del índice en la imagen (como proxy)
    3. 0.0 (si no hay dato)
    """
    def _get(attr: str, idx_name: str) -> float:
        # 1. Campo directo del target
        v = getattr(target, attr, None)
        if v is not None:
            return float(v)
        # 2. Media global del índice
        stats = indices_stats.get(idx_name)
        if stats and stats.get("media") is not None:
            return float(stats["media"])
        return 0.0

    ior     = _get("ior_media",  "ior")
    clay    = _get("clay_media", "clay")
    ferrous = _get_index_mean(indices_stats, "ferrous")
    ndvi    = _get_index_mean(indices_stats, "ndvi")
    ndwi    = _get_index_mean(indices_stats, "ndwi")
    evi     = _get_index_mean(indices_stats, "evi")
    savi    = _get_index_mean(indices_stats, "savi")

    area_ha = float(target.area_ha or 0.0)
    score   = float(target.score   or 0.0)

    # Litología favorable
    lit = (target.litologia_dominante or "").lower()
    lit_fav = 1.0 if any(k in lit for k in _LIT_FAVORABLES) else 0.0

    return np.array(
        [ior, clay, ferrous, ndvi, ndwi, evi, savi, area_ha, score, lit_fav],
        dtype=np.float32,
    )


def _get_index_mean(stats: dict[str, dict], nombre: str) -> float:
    s = stats.get(nombre)
    if s and s.get("media") is not None:
        return float(s["media"])
    return 0.0


def _build_y(
    etiquetas: list[Optional[str]],
    incluir_dudosos: bool,
) -> Optional[np.ndarray]:
    """
    Convierte etiquetas texto a array binario.
    Retorna None si no hay ninguna etiqueta útil.
    """
    y = []
    for e in etiquetas:
        if e == "positivo":
            y.append(1)
        elif e == "negativo":
            y.append(0)
        elif e == "dudoso" and incluir_dudosos:
            y.append(0)  # dudoso = negativo suave
        else:
            y.append(None)

    if all(v is None for v in y):
        return None

    # Array con -1 para no etiquetados (uso en semisupervised o filtrado externo)
    return np.array([-1 if v is None else v for v in y], dtype=np.int8)


def normalize_features(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Normaliza X a [0,1] por columna usando min-max.

    Returns:
        X_norm, min_vals, max_vals  (guardar min/max para aplicar en predict)
    """
    min_vals = X.min(axis=0)
    max_vals = X.max(axis=0)
    rng = max_vals - min_vals
    rng[rng == 0] = 1.0  # evitar división por cero
    X_norm = (X - min_vals) / rng
    return X_norm, min_vals, max_vals


def apply_normalization(
    X: np.ndarray,
    min_vals: np.ndarray,
    max_vals: np.ndarray,
) -> np.ndarray:
    """Aplica normalización min-max usando parámetros ya calculados."""
    rng = max_vals - min_vals
    rng[rng == 0] = 1.0
    return (X - min_vals) / rng
