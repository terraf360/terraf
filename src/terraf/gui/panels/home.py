"""
Panel Inicio — Dashboard del proyecto.

Muestra:
  - Nombre del proyecto + ruta de la DB
  - Estado de cada paso del pipeline (✓ / pendiente)
  - Resumen rápido: targets, validaciones, modelo
  - Botón "Actualizar"
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.panels.base import BasePanel
from terraf.gui.style import COLORES, badge


class HomePanel(BasePanel):
    """Panel de bienvenida / dashboard."""

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        # Título
        for w in self._make_title(
            "🏠  Inicio — TerraF",
            "Herramienta de exploración minera asistida por IA.",
        ).children():
            if isinstance(w, QWidget):
                root.addWidget(w)

        root.addSpacing(8)

        # Área scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_lay = QVBoxLayout(content)
        self._content_lay.setSpacing(16)
        self._content_lay.setContentsMargins(0, 0, 0, 24)

        # Placeholder inicial
        self._placeholder = QLabel("Cargando proyecto…")
        self._placeholder.setStyleSheet(f"color:{COLORES['text_muted']};")
        self._content_lay.addWidget(self._placeholder)
        self._content_lay.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

        # Botón actualizar (abajo)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_refresh = QPushButton("⟳  Actualizar")
        self._btn_refresh.setProperty("class", "secondary")
        self._btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(self._btn_refresh)
        root.addSpacing(8)
        root.addLayout(btn_row)

    def on_db_ready(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self._db_path is None:
            return
        from terraf.gui.workers import SimpleWorker
        self._worker = SimpleWorker(self._load_data)
        self._worker.done_signal.connect(self._render)
        self._worker.error_signal.connect(lambda e: self._log_err(e))
        self._run(self._worker)

    def _load_data(self) -> dict:
        from sqlalchemy import text
        from terraf.db.session import make_engine
        from terraf.pipeline.validation import resumen_validaciones
        from terraf.pipeline.ml.trainer import listar_modelos

        engine = make_engine(self._db_path)
        data: dict = {}

        with engine.connect() as conn:
            def q(sql):
                try: return conn.execute(text(sql)).scalar()
                except: return None

            data["proyecto"]    = q("SELECT nombre FROM proyectos LIMIT 1") or "Sin nombre"
            data["n_imagenes"]  = q("SELECT COUNT(*) FROM imagenes") or 0
            data["n_indices"]   = q("SELECT COUNT(*) FROM indices_espectrales") or 0
            data["n_analisis"]  = q("SELECT COUNT(*) FROM analisis") or 0
            data["n_targets"]   = q("SELECT COUNT(*) FROM targets") or 0
            data["n_geo"]       = q("SELECT COUNT(*) FROM datos_geologicos") or 0
            data["alta"]        = q("SELECT COUNT(*) FROM targets WHERE prioridad='ALTA'") or 0
            data["media"]       = q("SELECT COUNT(*) FROM targets WHERE prioridad='MEDIA'") or 0
            data["baja"]        = q("SELECT COUNT(*) FROM targets WHERE prioridad='BAJA'") or 0

        try:
            res = resumen_validaciones(self._db_path)
            data["validados"]   = res.validados
            data["positivos"]   = res.positivos
            data["negativos"]   = res.negativos
            data["pendientes"]  = res.pendientes
            data["pct"]         = res.pct_completado
        except:
            data["validados"] = data["positivos"] = data["negativos"] = data["pendientes"] = 0
            data["pct"] = 0.0

        modelos = listar_modelos()
        data["n_modelos"]    = len(modelos)
        data["ultimo_modelo"] = modelos[0].get("tipo_deposito", "—") if modelos else None

        return data

    def _render(self, data: dict) -> None:
        # Limpiar contenido previo
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Card: proyecto ─────────────────────────────────────────────────────
        lay_proy = QVBoxLayout()
        lay_proy.setSpacing(8)
        lay_proy.addLayout(self._kv_row("Proyecto:", data["proyecto"]))
        lay_proy.addLayout(self._kv_row("Base de datos:", str(self._db_path)))
        card_proy = self._make_card(lay_proy)
        lbl_proy = QLabel("PROYECTO")
        lbl_proy.setStyleSheet(f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;margin-bottom:4px;")
        self._content_lay.addWidget(lbl_proy)
        self._content_lay.addWidget(card_proy)

        # ── Card: estado del pipeline ──────────────────────────────────────────
        lbl_pipe = QLabel("PIPELINE")
        lbl_pipe.setStyleSheet(f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;margin-top:8px;margin-bottom:4px;")
        self._content_lay.addWidget(lbl_pipe)

        pasos = [
            ("Imagen cargada",     data["n_imagenes"] > 0,  f"{data['n_imagenes']} imagen(es)"),
            ("Geología vinculada", data["n_geo"] > 0,       f"{data['n_geo']} capas"),
            ("Índices calculados", data["n_indices"] > 0,   f"{data['n_indices']} índice(s)"),
            ("Análisis ejecutado", data["n_analisis"] > 0,  f"{data['n_analisis']} análisis / {data['n_targets']} targets"),
            ("Validaciones",       data["validados"] > 0,   f"{data['validados']} validados ({data['pct']:.0f}%)"),
            ("Modelo entrenado",   data["n_modelos"] > 0,   f"{data['n_modelos']} modelo(s) · {data['ultimo_modelo'] or '—'}"),
        ]

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (nombre, ok, detalle) in enumerate(pasos):
            icon = QLabel("✓" if ok else "○")
            icon.setStyleSheet(
                f"color:{'#a6e3a1' if ok else COLORES['text_muted']};"
                f"font-size:16px;font-weight:bold;"
            )
            icon.setFixedWidth(24)

            lbl_n = QLabel(nombre)
            lbl_n.setStyleSheet(f"color:{COLORES['text']};font-weight:{'bold' if ok else 'normal'};")

            lbl_d = QLabel(detalle)
            lbl_d.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;")
            lbl_d.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            grid.addWidget(icon,  i, 0)
            grid.addWidget(lbl_n, i, 1)
            grid.addWidget(lbl_d, i, 2)

        grid.setColumnStretch(1, 1)
        card_pipe = self._make_card()
        card_pipe.setLayout(grid)
        self._content_lay.addWidget(card_pipe)

        # ── Card: targets ──────────────────────────────────────────────────────
        if data["n_targets"] > 0:
            lbl_tgt = QLabel("TARGETS")
            lbl_tgt.setStyleSheet(f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;margin-top:8px;margin-bottom:4px;")
            self._content_lay.addWidget(lbl_tgt)

            row_tgt = QHBoxLayout()
            row_tgt.setSpacing(12)
            for txt, val, color in [
                ("ALTA",  data["alta"],  COLORES["success"]),
                ("MEDIA", data["media"], COLORES["warning"]),
                ("BAJA",  data["baja"],  COLORES["text_muted"]),
            ]:
                mini = QVBoxLayout()
                mini.setAlignment(Qt.AlignCenter)
                lv = QLabel(str(val))
                lv.setStyleSheet(f"color:{color};font-size:28px;font-weight:bold;")
                lv.setAlignment(Qt.AlignCenter)
                lt = QLabel(txt)
                lt.setStyleSheet(f"color:{COLORES['text_muted']};font-size:10px;letter-spacing:1px;")
                lt.setAlignment(Qt.AlignCenter)
                mini.addWidget(lv)
                mini.addWidget(lt)
                card_mini = self._make_card()
                card_mini.setLayout(mini)
                card_mini.setFixedHeight(80)
                row_tgt.addWidget(card_mini)

            w_tgt = QWidget()
            w_tgt.setStyleSheet("background:transparent;")
            w_tgt.setLayout(row_tgt)
            self._content_lay.addWidget(w_tgt)

        self._content_lay.addStretch()
        self._status(f"Proyecto: {data['proyecto']}  ·  {data['n_targets']} targets  ·  {data['validados']} validados")
