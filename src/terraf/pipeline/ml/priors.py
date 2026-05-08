"""
Pipeline ML — M9b: Modelos de priors espectrales por tipo de depósito.

Genera muestras sintéticas basadas en firmas espectrales de referencia
(USGS / literatura) para cada tipo de depósito mineral, permitiendo
entrenar un clasificador incluso sin datos de campo validados.

Tipos de depósito soportados:
  - porfido_cu     : Pórfido cuprífero (Cu-Mo-Au)
  - epitermal_au   : Epitermal de baja sulfuración (Au-Ag)
  - epitermal_hs   : Epitermal de alta sulfuración (Au-Cu)
  - skarn          : Skarn de Cu-Fe-Au
  - vms            : Sulfuros masivos volcanogénicos
  - generico        : Prior genérico (sin tipo definido)

Cada tipo define distribuciones Normal(mu, sigma) para cada feature
derivadas de bibliografía espectral (Landsat-8/9 OLI bandas 2-7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from terraf.pipeline.ml.features import FEATURE_NAMES


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de depósito disponibles
# ──────────────────────────────────────────────────────────────────────────────

TIPOS_DEPOSITO = (
    "porfido_cu",
    "epitermal_au",
    "epitermal_hs",
    "skarn",
    "vms",
    "generico",
)


# ──────────────────────────────────────────────────────────────────────────────
# Priors: (mu_positivo, sigma_positivo, mu_negativo, sigma_negativo)
# Orden de features: ior, clay, ferrous, ndvi, ndwi, evi, savi, area_ha, score, lit_fav
# ──────────────────────────────────────────────────────────────────────────────

# Cada entrada: [mu_pos, sig_pos, mu_neg, sig_neg] por feature
_PRIORS: dict[str, dict[str, list[float]]] = {

    "porfido_cu": {
        # Alta alteración argílica (clay) e hidrotermal (ior/ferrous)
        # ior_media
        "ior_media":      [1.30, 0.12,  1.05, 0.10],
        # clay_media
        "clay_media":     [1.25, 0.15,  0.95, 0.10],
        # ferrous_media
        "ferrous_media":  [1.20, 0.15,  1.00, 0.12],
        # ndvi bajo (poca vegetación sobre zona alterada)
        "ndvi_media":     [0.10, 0.08,  0.35, 0.15],
        # ndwi bajo
        "ndwi_media":    [-0.10, 0.08, -0.05, 0.08],
        # evi bajo
        "evi_media":      [0.08, 0.06,  0.22, 0.12],
        # savi bajo
        "savi_media":     [0.10, 0.07,  0.28, 0.14],
        # área mayor
        "area_ha":        [15.0, 8.0,   5.0,  4.0],
        # score
        "score":          [0.72, 0.15,  0.35, 0.18],
        # litología favorable
        "lit_favoreciable": [0.85, 0.20, 0.30, 0.25],
    },

    "epitermal_au": {
        # Alteración silícea + argílica moderada
        "ior_media":      [1.20, 0.12,  1.05, 0.10],
        "clay_media":     [1.15, 0.12,  0.95, 0.10],
        "ferrous_media":  [1.10, 0.12,  1.00, 0.10],
        "ndvi_media":     [0.12, 0.09,  0.30, 0.15],
        "ndwi_media":    [-0.08, 0.07, -0.03, 0.07],
        "evi_media":      [0.10, 0.07,  0.20, 0.10],
        "savi_media":     [0.12, 0.08,  0.26, 0.12],
        "area_ha":        [8.0,  5.0,   3.0,  3.0],
        "score":          [0.65, 0.18,  0.30, 0.18],
        "lit_favoreciable": [0.80, 0.22, 0.35, 0.28],
    },

    "epitermal_hs": {
        # Alta sulfuración: alunita, caolinita → clay muy alto, ior alto
        "ior_media":      [1.35, 0.14,  1.05, 0.10],
        "clay_media":     [1.40, 0.18,  0.95, 0.10],
        "ferrous_media":  [1.25, 0.16,  1.00, 0.12],
        "ndvi_media":     [0.08, 0.06,  0.32, 0.14],
        "ndwi_media":    [-0.12, 0.07, -0.04, 0.07],
        "evi_media":      [0.07, 0.05,  0.20, 0.10],
        "savi_media":     [0.09, 0.06,  0.25, 0.12],
        "area_ha":        [6.0,  4.0,   2.5,  2.5],
        "score":          [0.68, 0.16,  0.32, 0.18],
        "lit_favoreciable": [0.82, 0.20, 0.35, 0.28],
    },

    "skarn": {
        # Alteración de contacto: ferrous y clay moderados
        "ior_media":      [1.25, 0.12,  1.05, 0.10],
        "clay_media":     [1.10, 0.12,  0.95, 0.10],
        "ferrous_media":  [1.30, 0.15,  1.00, 0.12],
        "ndvi_media":     [0.15, 0.10,  0.33, 0.15],
        "ndwi_media":    [-0.07, 0.07, -0.03, 0.07],
        "evi_media":      [0.12, 0.08,  0.21, 0.10],
        "savi_media":     [0.14, 0.09,  0.27, 0.12],
        "area_ha":        [10.0, 6.0,   3.5,  3.0],
        "score":          [0.60, 0.18,  0.30, 0.18],
        "lit_favoreciable": [0.75, 0.22, 0.35, 0.28],
    },

    "vms": {
        # Sulfuros volcanogénicos: ferrous muy alto, zona volcánica
        "ior_media":      [1.22, 0.12,  1.05, 0.10],
        "clay_media":     [1.08, 0.12,  0.95, 0.10],
        "ferrous_media":  [1.35, 0.15,  1.00, 0.12],
        "ndvi_media":     [0.13, 0.09,  0.30, 0.14],
        "ndwi_media":    [-0.09, 0.07, -0.03, 0.07],
        "evi_media":      [0.11, 0.07,  0.20, 0.10],
        "savi_media":     [0.13, 0.08,  0.26, 0.12],
        "area_ha":        [7.0,  4.0,   2.5,  2.5],
        "score":          [0.62, 0.17,  0.30, 0.17],
        "lit_favoreciable": [0.78, 0.22, 0.35, 0.28],
    },

    "generico": {
        # Prior conservador — señal espectral moderada
        "ior_media":      [1.20, 0.15,  1.02, 0.12],
        "clay_media":     [1.15, 0.15,  0.96, 0.12],
        "ferrous_media":  [1.15, 0.15,  1.00, 0.12],
        "ndvi_media":     [0.12, 0.10,  0.32, 0.15],
        "ndwi_media":    [-0.08, 0.08, -0.04, 0.08],
        "evi_media":      [0.10, 0.08,  0.21, 0.12],
        "savi_media":     [0.12, 0.09,  0.27, 0.13],
        "area_ha":        [8.0,  6.0,   3.0,  3.0],
        "score":          [0.60, 0.20,  0.30, 0.18],
        "lit_favoreciable": [0.70, 0.25, 0.35, 0.28],
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def generate_synthetic_samples(
    tipo_deposito: str = "generico",
    n_positivos: int = 80,
    n_negativos: int = 80,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Genera muestras sintéticas para el tipo de depósito dado.

    Args:
        tipo_deposito: Uno de TIPOS_DEPOSITO.
        n_positivos:   Cantidad de muestras positivas a generar.
        n_negativos:   Cantidad de muestras negativas a generar.
        seed:          Semilla aleatoria para reproducibilidad.

    Returns:
        X_synth: np.ndarray shape (n_positivos + n_negativos, n_features)
        y_synth: np.ndarray shape (n_positivos + n_negativos,) con 1/0
    """
    if tipo_deposito not in _PRIORS:
        tipo_deposito = "generico"

    prior = _PRIORS[tipo_deposito]
    rng = np.random.default_rng(seed)

    rows_pos: list[list[float]] = []
    rows_neg: list[list[float]] = []

    for feat in FEATURE_NAMES:
        params = prior.get(feat, [0.5, 0.2, 0.3, 0.2])
        mu_p, sig_p, mu_n, sig_n = params

        vals_pos = rng.normal(mu_p, sig_p, n_positivos).tolist()
        vals_neg = rng.normal(mu_n, sig_n, n_negativos).tolist()

        rows_pos.append(vals_pos)
        rows_neg.append(vals_neg)

    # Transponer: (n_features, n_samples) → (n_samples, n_features)
    X_pos = np.array(rows_pos, dtype=np.float32).T  # (n_pos, n_feat)
    X_neg = np.array(rows_neg, dtype=np.float32).T  # (n_neg, n_feat)

    # Clip valores a rangos razonables
    X_pos = _clip_features(X_pos)
    X_neg = _clip_features(X_neg)

    X_synth = np.vstack([X_pos, X_neg])
    y_synth = np.array([1] * n_positivos + [0] * n_negativos, dtype=np.int8)

    # Mezclar
    idx = rng.permutation(len(y_synth))
    return X_synth[idx], y_synth[idx]


def list_tipos() -> list[str]:
    """Retorna la lista de tipos de depósito disponibles."""
    return list(TIPOS_DEPOSITO)


def prior_description(tipo_deposito: str) -> str:
    """Descripción legible del tipo de depósito."""
    _DESCS = {
        "porfido_cu":   "Pórfido Cu-Mo-Au — alteración argílica e hidrotermal intensa",
        "epitermal_au": "Epitermal Au-Ag baja sulfuración — alteración silícea moderada",
        "epitermal_hs": "Epitermal Au-Cu alta sulfuración — alunita/caolinita prominente",
        "skarn":        "Skarn Cu-Fe-Au — alteración de contacto con ferrous elevado",
        "vms":          "VMS — sulfuros masivos volcanogénicos, ferrous muy alto",
        "generico":     "Genérico — prior conservador para cualquier tipo de depósito",
    }
    return _DESCS.get(tipo_deposito, tipo_deposito)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

# Límites físicos por feature (min, max)
_FEATURE_BOUNDS: dict[str, tuple[float, float]] = {
    "ior_media":        (0.5, 3.0),
    "clay_media":       (0.5, 3.0),
    "ferrous_media":    (0.5, 3.0),
    "ndvi_media":       (-1.0, 1.0),
    "ndwi_media":       (-1.0, 1.0),
    "evi_media":        (-1.0, 2.5),
    "savi_media":       (-1.0, 1.5),
    "area_ha":          (0.1, 200.0),
    "score":            (0.0, 1.0),
    "lit_favoreciable": (0.0, 1.0),
}


def _clip_features(X: np.ndarray) -> np.ndarray:
    """Recorta cada columna a sus límites físicos."""
    X = X.copy()
    for i, feat in enumerate(FEATURE_NAMES):
        lo, hi = _FEATURE_BOUNDS.get(feat, (-np.inf, np.inf))
        X[:, i] = np.clip(X[:, i], lo, hi)
    return X
