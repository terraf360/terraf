"""
Pipeline ML — M12: Active Learning — selección inteligente de targets para validar.

Estrategia de muestreo:
  - Incertidumbre máxima (Uncertainty Sampling): selecciona los targets
    cuya prob_positivo es más cercana a 0.5 → el modelo sabe menos sobre ellos.
  - Diversidad (opcional): evita seleccionar targets muy cercanos entre sí
    en el espacio de features.

Resultado: lista priorizada de targets SIN validar que más información
aportarían al modelo si se validaran en campo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from terraf.db.models import Analisis, Target, Validacion
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SugerenciaValidacion:
    target_id: int
    nombre: str
    prob_positivo: Optional[float]   # None si el modelo aún no corrió
    incertidumbre: float             # |prob - 0.5|, menor = más incierto
    score_original: float
    prioridad: str
    centroide_lon: Optional[float]
    centroide_lat: Optional[float]
    razon: str                       # Texto explicativo para el usuario


@dataclass
class ResumenMejora:
    n_sin_validar: int
    n_sugeridos: int
    ganancia_esperada: str           # "alta" | "media" | "baja"
    proxima_accion: str


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def sugerir_validaciones(
    db_path: Path,
    analisis_id: Optional[int] = None,
    top_n: int = 5,
    modo: str = "incertidumbre",    # "incertidumbre" | "mixto"
) -> tuple[list[SugerenciaValidacion], ResumenMejora]:
    """
    Sugiere los targets más valiosos para validar en campo.

    Args:
        db_path:      Ruta al terraf.db.
        analisis_id:  Análisis específico (default: último).
        top_n:        Número de sugerencias a devolver.
        modo:         Estrategia de selección.

    Returns:
        (lista de sugerencias, resumen de la situación)
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

        # IDs de targets ya validados
        validados_ids = {
            v.target_id
            for v in session.query(Validacion.target_id).all()
        }

        # Todos los targets sin validar
        targets_sin_val = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .filter(Target.id.notin_(validados_ids))
            .all()
        )

        n_sin_validar = len(targets_sin_val)

        if n_sin_validar == 0:
            resumen = ResumenMejora(
                n_sin_validar=0,
                n_sugeridos=0,
                ganancia_esperada="baja",
                proxima_accion="Todos los targets están validados. Entrena con: terraf train",
            )
            return [], resumen

        # Calcular puntuación de utilidad para cada target no validado
        candidatos = [_score_utilidad(t, modo) for t in targets_sin_val]

        # Ordenar por utilidad descendente
        candidatos.sort(key=lambda x: x[1], reverse=True)

        sugerencias = [s for s, _ in candidatos[:top_n]]

        resumen = _calcular_resumen(
            n_sin_validar=n_sin_validar,
            sugerencias=sugerencias,
            n_validados=len(validados_ids),
        )

        return sugerencias, resumen


def estado_active_learning(
    db_path: Path,
    analisis_id: Optional[int] = None,
) -> dict:
    """
    Retorna un resumen del estado del ciclo de active learning.

    Returns:
        Dict con: n_targets, n_validados, n_sin_validar, n_positivos,
                  n_negativos, n_con_prob, prob_media, ciclo_sugerido.
    """
    with open_session(db_path) as session:
        q = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            q = q.filter_by(id=analisis_id)
        analisis = q.first()

        if analisis is None:
            return {}

        targets = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .all()
        )

        n_total    = len(targets)
        n_con_prob = sum(1 for t in targets if t.prob_positivo is not None)
        probs      = [t.prob_positivo for t in targets if t.prob_positivo is not None]
        prob_media = float(np.mean(probs)) if probs else None

        validaciones = session.query(Validacion).all()
        val_by_target = {v.target_id: v.resultado for v in validaciones}

        n_validados  = len(val_by_target)
        n_positivos  = sum(1 for r in val_by_target.values() if r == "positivo")
        n_negativos  = sum(1 for r in val_by_target.values() if r == "negativo")

        # Ciclo sugerido basado en datos disponibles
        if n_validados == 0:
            ciclo = "Ejecuta 'terraf train' + 'terraf predict' para comenzar"
        elif n_validados < 5:
            ciclo = "Valida más targets → 'terraf improve' para sugerencias"
        elif n_validados < 20:
            ciclo = "Reentrenar recomendado → 'terraf train' → 'terraf predict'"
        else:
            ciclo = "Dataset maduro → 'terraf train --tipo <deposito>' para especializar"

        return {
            "n_targets":      n_total,
            "n_validados":    n_validados,
            "n_sin_validar":  n_total - n_validados,
            "n_positivos":    n_positivos,
            "n_negativos":    n_negativos,
            "n_con_prob":     n_con_prob,
            "prob_media":     prob_media,
            "ciclo_sugerido": ciclo,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _score_utilidad(target: Target, modo: str) -> tuple[SugerenciaValidacion, float]:
    """
    Calcula la utilidad de validar este target.

    Devuelve (SugerenciaValidacion, utilidad_float)  — mayor = más valioso.
    """
    prob = target.prob_positivo  # puede ser None si aún no se corrió predict

    if prob is not None:
        # Incertidumbre: máxima cuando prob = 0.5
        incertidumbre = abs(prob - 0.5)

        # Utilidad base = 1 - incertidumbre (menor incertidumbre = más útil)
        utilidad_incierta = 1.0 - incertidumbre

        if modo == "mixto":
            # Combinar incertidumbre con score original
            utilidad = 0.7 * utilidad_incierta + 0.3 * float(target.score or 0.0)
        else:
            utilidad = utilidad_incierta

        # Texto de razón
        if incertidumbre < 0.10:
            razon = f"Muy incierto (prob={prob:.0%}) — máxima ganancia si se valida"
        elif incertidumbre < 0.25:
            razon = f"Incierto (prob={prob:.0%}) — buena candidatura"
        elif prob > 0.70:
            razon = f"Alta prob. ML ({prob:.0%}) — confirmar en campo"
        else:
            razon = f"Prob. baja ({prob:.0%}) — validar para reforzar negativos"
    else:
        # Sin probabilidad: usar score como proxy, priorizar ALTA
        score    = float(target.score or 0.0)
        prioridad = target.prioridad or ""
        bonus     = 0.2 if prioridad == "ALTA" else (0.1 if prioridad == "MEDIA" else 0.0)
        utilidad  = score + bonus
        incertidumbre = 0.5  # desconocido
        razon = f"Sin predicción ML — score={score:.3f}, valida para entrenar el modelo"

    sug = SugerenciaValidacion(
        target_id=target.id,
        nombre=target.nombre or f"T{target.id}",
        prob_positivo=target.prob_positivo,
        incertidumbre=incertidumbre,
        score_original=float(target.score or 0.0),
        prioridad=target.prioridad or "—",
        centroide_lon=target.centroide_lon,
        centroide_lat=target.centroide_lat,
        razon=razon,
    )
    return sug, utilidad


def _calcular_resumen(
    n_sin_validar: int,
    sugerencias: list[SugerenciaValidacion],
    n_validados: int,
) -> ResumenMejora:
    # Estimar ganancia esperada
    if n_validados < 5:
        ganancia = "alta"
        accion = (
            f"Valida {min(5, n_sin_validar)} targets → reentrenar con 'terraf train'"
        )
    elif n_validados < 20:
        ganancia = "media"
        accion = "Cada validación nueva mejora el modelo — reentrenar tras 3-5 nuevas"
    else:
        ganancia = "baja"
        accion = "Modelo estabilizándose — foco en targets de alta incertidumbre"

    return ResumenMejora(
        n_sin_validar=n_sin_validar,
        n_sugeridos=len(sugerencias),
        ganancia_esperada=ganancia,
        proxima_accion=accion,
    )
