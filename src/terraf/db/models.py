"""
Modelos SQLAlchemy — esquema de 7 tablas según spec-database.md
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# proyectos
# ──────────────────────────────────────────────────────────────────────────────

class Proyecto(Base):
    __tablename__ = "proyectos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    directorio: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    config_json: Mapped[Optional[str]] = mapped_column(Text)

    imagenes: Mapped[list["Imagen"]] = relationship(back_populates="proyecto")
    datos_geologicos: Mapped[list["DatoGeologico"]] = relationship(back_populates="proyecto")
    analisis: Mapped[list["Analisis"]] = relationship(back_populates="proyecto")


# ──────────────────────────────────────────────────────────────────────────────
# imagenes
# ──────────────────────────────────────────────────────────────────────────────

class Imagen(Base):
    __tablename__ = "imagenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(ForeignKey("proyectos.id"), nullable=False)
    scene_id: Mapped[str] = mapped_column(Text, nullable=False)
    sensor: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_adquisicion: Mapped[Optional[str]] = mapped_column(Text)   # DATE como TEXT
    crs: Mapped[Optional[str]] = mapped_column(Text)
    ancho_px: Mapped[Optional[int]] = mapped_column(Integer)
    alto_px: Mapped[Optional[int]] = mapped_column(Integer)
    resolucion_m: Mapped[Optional[float]] = mapped_column(Float)
    bounds_json: Mapped[Optional[str]] = mapped_column(Text)
    transform_json: Mapped[Optional[str]] = mapped_column(Text)
    ruta_archivo: Mapped[Optional[str]] = mapped_column(Text)
    bandas_json: Mapped[Optional[str]] = mapped_column(Text)
    cargada_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    proyecto: Mapped["Proyecto"] = relationship(back_populates="imagenes")
    indices: Mapped[list["IndiceEspectral"]] = relationship(back_populates="imagen")
    analisis: Mapped[list["Analisis"]] = relationship(back_populates="imagen")

    __table_args__ = (
        Index("idx_imagenes_proyecto", "proyecto_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# datos_geologicos
# ──────────────────────────────────────────────────────────────────────────────

class DatoGeologico(Base):
    __tablename__ = "datos_geologicos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(ForeignKey("proyectos.id"), nullable=False)
    carta_id: Mapped[Optional[str]] = mapped_column(Text)
    capa: Mapped[str] = mapped_column(Text, nullable=False)
    num_features: Mapped[Optional[int]] = mapped_column(Integer)
    crs: Mapped[Optional[str]] = mapped_column(Text)
    ruta_archivo: Mapped[Optional[str]] = mapped_column(Text)
    cargada_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    proyecto: Mapped["Proyecto"] = relationship(back_populates="datos_geologicos")
    features: Mapped[list["FeatureGeologico"]] = relationship(back_populates="dato_geologico")

    __table_args__ = (
        Index("idx_datos_geo_proyecto", "proyecto_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# features_geologicos
# ──────────────────────────────────────────────────────────────────────────────

class FeatureGeologico(Base):
    __tablename__ = "features_geologicos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dato_geologico_id: Mapped[int] = mapped_column(
        ForeignKey("datos_geologicos.id"), nullable=False
    )
    tipo: Mapped[Optional[str]] = mapped_column(Text)
    nombre: Mapped[Optional[str]] = mapped_column(Text)
    atributos_json: Mapped[Optional[str]] = mapped_column(Text)
    geometria_wkt: Mapped[Optional[str]] = mapped_column(Text)
    es_favorable: Mapped[Optional[bool]] = mapped_column(Boolean)

    dato_geologico: Mapped["DatoGeologico"] = relationship(back_populates="features")

    __table_args__ = (
        Index("idx_features_dato", "dato_geologico_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# indices_espectrales
# ──────────────────────────────────────────────────────────────────────────────

class IndiceEspectral(Base):
    __tablename__ = "indices_espectrales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imagen_id: Mapped[int] = mapped_column(ForeignKey("imagenes.id"), nullable=False)
    nombre_indice: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[Optional[str]] = mapped_column(Text)
    umbral: Mapped[Optional[float]] = mapped_column(Float)
    min_val: Mapped[Optional[float]] = mapped_column(Float)
    max_val: Mapped[Optional[float]] = mapped_column(Float)
    media: Mapped[Optional[float]] = mapped_column(Float)
    desv_std: Mapped[Optional[float]] = mapped_column(Float)
    percentil_25: Mapped[Optional[float]] = mapped_column(Float)
    percentil_75: Mapped[Optional[float]] = mapped_column(Float)
    px_sobre_umbral: Mapped[Optional[int]] = mapped_column(Integer)
    pct_sobre_umbral: Mapped[Optional[float]] = mapped_column(Float)
    ruta_raster: Mapped[Optional[str]] = mapped_column(Text)
    calculado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    imagen: Mapped["Imagen"] = relationship(back_populates="indices")

    __table_args__ = (
        Index("idx_indices_imagen", "imagen_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# analisis
# ──────────────────────────────────────────────────────────────────────────────

class Analisis(Base):
    __tablename__ = "analisis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(ForeignKey("proyectos.id"), nullable=False)
    imagen_id: Mapped[int] = mapped_column(ForeignKey("imagenes.id"), nullable=False)
    metodo: Mapped[Optional[str]] = mapped_column(Text)
    parametros_json: Mapped[Optional[str]] = mapped_column(Text)
    num_targets: Mapped[Optional[int]] = mapped_column(Integer)
    ejecutado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    duracion_seg: Mapped[Optional[float]] = mapped_column(Float)

    proyecto: Mapped["Proyecto"] = relationship(back_populates="analisis")
    imagen: Mapped["Imagen"] = relationship(back_populates="analisis")
    targets: Mapped[list["Target"]] = relationship(back_populates="analisis")

    __table_args__ = (
        Index("idx_analisis_proyecto", "proyecto_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# targets
# ──────────────────────────────────────────────────────────────────────────────

class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analisis_id: Mapped[int] = mapped_column(ForeignKey("analisis.id"), nullable=False)
    nombre: Mapped[Optional[str]] = mapped_column(Text)
    centroide_x: Mapped[Optional[float]] = mapped_column(Float)
    centroide_y: Mapped[Optional[float]] = mapped_column(Float)
    centroide_lon: Mapped[Optional[float]] = mapped_column(Float)
    centroide_lat: Mapped[Optional[float]] = mapped_column(Float)
    area_ha: Mapped[Optional[float]] = mapped_column(Float)
    area_px: Mapped[Optional[int]] = mapped_column(Integer)
    score: Mapped[Optional[float]] = mapped_column(Float)
    prioridad: Mapped[Optional[str]] = mapped_column(Text)
    ior_media: Mapped[Optional[float]] = mapped_column(Float)
    clay_media: Mapped[Optional[float]] = mapped_column(Float)
    litologia_dominante: Mapped[Optional[str]] = mapped_column(Text)
    geometria_wkt: Mapped[Optional[str]] = mapped_column(Text)
    notas: Mapped[Optional[str]] = mapped_column(Text)

    # Campos ML — poblados por `terraf predict`
    prob_positivo: Mapped[Optional[float]] = mapped_column(Float)
    modelo_version: Mapped[Optional[str]] = mapped_column(Text)

    analisis: Mapped["Analisis"] = relationship(back_populates="targets")
    validaciones: Mapped[list["Validacion"]] = relationship(back_populates="target")

    __table_args__ = (
        Index("idx_targets_analisis", "analisis_id"),
        Index("idx_targets_prioridad", "prioridad"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# validaciones  (ground truth de campo)
# ──────────────────────────────────────────────────────────────────────────────

class Validacion(Base):
    __tablename__ = "validaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"), nullable=False)
    resultado: Mapped[str] = mapped_column(Text, nullable=False)
    # 'positivo' | 'negativo' | 'pendiente' | 'dudoso'
    metodo: Mapped[Optional[str]] = mapped_column(Text)
    # 'campo' | 'imagen' | 'geofisica' | 'laboratorio'
    notas: Mapped[Optional[str]] = mapped_column(Text)
    validado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    target: Mapped["Target"] = relationship(back_populates="validaciones")

    __table_args__ = (
        Index("idx_validaciones_target", "target_id"),
        Index("idx_validaciones_resultado", "resultado"),
    )
