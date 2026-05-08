"""
Pipeline — M8: Ground truth / validación de campo.

Permite marcar targets como positivo/negativo/pendiente/dudoso
y consultar el estado de validación del proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from terraf.db.models import Analisis, Target, Validacion
from terraf.db.session import open_session


# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

RESULTADOS_VALIDOS = ("positivo", "negativo", "pendiente", "dudoso")
METODOS_VALIDOS    = ("campo", "imagen", "geofisica", "laboratorio")


# ──────────────────────────────────────────────────────────────────────────────
# Tipos de retorno
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ValidacionInfo:
    validacion_id: int
    target_id: int
    target_nombre: str
    resultado: str
    metodo: Optional[str]
    notas: Optional[str]
    actualizado: bool   # True si era una validación existente que se actualizó


@dataclass
class TargetConValidacion:
    target_id: int
    nombre: str
    score: float
    prioridad: str
    area_ha: float
    prob_positivo: Optional[float]
    resultado: Optional[str]    # None si no tiene validación aún
    metodo: Optional[str]
    notas: Optional[str]


@dataclass
class ResumenValidaciones:
    total_targets: int
    validados: int
    pendientes: int
    positivos: int
    negativos: int
    dudosos: int
    pct_completado: float


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def validar_target(
    db_path: Path,
    identificador: str,
    resultado: str,
    metodo: Optional[str] = None,
    notas: Optional[str] = None,
    analisis_id: Optional[int] = None,
) -> ValidacionInfo:
    """
    Marca un target como positivo/negativo/pendiente/dudoso.

    Si el target ya tiene una validación, la actualiza (upsert).

    Args:
        db_path:       Ruta al archivo terraf.db.
        identificador: Nombre del target ("T001") o su ID numérico.
        resultado:     "positivo" | "negativo" | "pendiente" | "dudoso"
        metodo:        "campo" | "imagen" | "geofisica" | "laboratorio"
        notas:         Texto libre opcional.
        analisis_id:   Busca el target en este análisis (default: último).

    Returns:
        ValidacionInfo con los datos guardados.

    Raises:
        ValueError:  Si resultado o método no son válidos.
        LookupError: Si no se encuentra el target.
        RuntimeError: Si no hay análisis en la DB.
    """
    resultado = resultado.lower()
    if resultado not in RESULTADOS_VALIDOS:
        raise ValueError(
            f"Resultado '{resultado}' no válido.\n"
            f"  Opciones: {', '.join(RESULTADOS_VALIDOS)}"
        )

    if metodo is not None:
        metodo = metodo.lower()
        if metodo not in METODOS_VALIDOS:
            raise ValueError(
                f"Método '{metodo}' no válido.\n"
                f"  Opciones: {', '.join(METODOS_VALIDOS)}"
            )

    with open_session(db_path) as session:
        # Obtener el análisis
        query = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            query = query.filter_by(id=analisis_id)
        analisis = query.first()

        if analisis is None:
            raise RuntimeError(
                "No hay análisis registrado.\nEjecuta 'terraf analyze' primero."
            )

        # Buscar target por nombre (ej: "T001") o por ID numérico
        target_query = session.query(Target).filter_by(analisis_id=analisis.id)

        if identificador.isdigit():
            target = target_query.filter_by(id=int(identificador)).first()
        else:
            # Case-insensitive por si el usuario escribe "t001"
            target = target_query.filter(
                Target.nombre.ilike(identificador)
            ).first()

        if target is None:
            raise LookupError(
                f"No se encontró el target '{identificador}' en el último análisis.\n"
                "Usa 'terraf validate --lista' para ver los targets disponibles."
            )

        # Upsert: buscar validación existente para este target
        val_existente = (
            session.query(Validacion)
            .filter_by(target_id=target.id)
            .first()
        )

        actualizado = val_existente is not None

        if actualizado:
            val_existente.resultado = resultado
            if metodo is not None:
                val_existente.metodo = metodo
            if notas is not None:
                val_existente.notas = notas
            session.flush()
            validacion_id = val_existente.id
        else:
            nueva = Validacion(
                target_id=target.id,
                resultado=resultado,
                metodo=metodo,
                notas=notas,
            )
            session.add(nueva)
            session.flush()
            validacion_id = nueva.id

        return ValidacionInfo(
            validacion_id=validacion_id,
            target_id=target.id,
            target_nombre=target.nombre or identificador,
            resultado=resultado,
            metodo=metodo,
            notas=notas,
            actualizado=actualizado,
        )


def listar_validaciones(
    db_path: Path,
    analisis_id: Optional[int] = None,
    solo_pendientes: bool = False,
) -> list[TargetConValidacion]:
    """
    Lista todos los targets del último análisis con su estado de validación.

    Args:
        db_path:         Ruta al archivo terraf.db.
        analisis_id:     Análisis específico (default: último).
        solo_pendientes: Si True, solo retorna los sin validación.

    Returns:
        Lista de TargetConValidacion ordenada por score descendente.
    """
    with open_session(db_path) as session:
        query = session.query(Analisis).order_by(Analisis.ejecutado_en.desc())
        if analisis_id is not None:
            query = query.filter_by(id=analisis_id)
        analisis = query.first()

        if analisis is None:
            raise RuntimeError(
                "No hay análisis registrado.\nEjecuta 'terraf analyze' primero."
            )

        targets = (
            session.query(Target)
            .filter_by(analisis_id=analisis.id)
            .order_by(Target.score.desc())
            .all()
        )

        resultado: list[TargetConValidacion] = []
        for t in targets:
            val = (
                session.query(Validacion)
                .filter_by(target_id=t.id)
                .first()
            )
            tiene_val = val is not None

            if solo_pendientes and tiene_val:
                continue

            resultado.append(TargetConValidacion(
                target_id=t.id,
                nombre=t.nombre or "—",
                score=t.score or 0.0,
                prioridad=t.prioridad or "—",
                area_ha=t.area_ha or 0.0,
                prob_positivo=t.prob_positivo,
                resultado=val.resultado if val else None,
                metodo=val.metodo if val else None,
                notas=val.notas if val else None,
            ))

        return resultado


def resumen_validaciones(db_path: Path, analisis_id: Optional[int] = None) -> ResumenValidaciones:
    """Retorna conteos de validaciones del último análisis."""
    targets = listar_validaciones(db_path, analisis_id=analisis_id)

    total     = len(targets)
    validados = sum(1 for t in targets if t.resultado is not None)
    positivos = sum(1 for t in targets if t.resultado == "positivo")
    negativos = sum(1 for t in targets if t.resultado == "negativo")
    dudosos   = sum(1 for t in targets if t.resultado == "dudoso")
    pendientes = total - validados

    return ResumenValidaciones(
        total_targets=total,
        validados=validados,
        pendientes=pendientes,
        positivos=positivos,
        negativos=negativos,
        dudosos=dudosos,
        pct_completado=round(validados / total * 100, 1) if total else 0.0,
    )
