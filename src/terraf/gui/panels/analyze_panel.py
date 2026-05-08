"""
Panel Analizar — Detecta targets de exploración y muestra resultados.
Incluye mapa interactivo de targets coloreados por prioridad.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.map_widget import MapWidget
from terraf.gui.panels.base import BasePanel
from terraf.gui.style import COLORES


class AnalyzePanel(BasePanel):
    """Panel de análisis de targets."""

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        for w in self._make_title(
            "Analizar Targets",
            "Detecta zonas de anomalía espectral y genera los targets de exploración. "
            "Cada target recibe un score de prioridad basado en IOR, Clay y área.",
        ).children():
            if isinstance(w, QWidget):
                root.addWidget(w)

        root.addSpacing(16)

        # ── Parámetros ─────────────────────────────────────────────────────────
        grp = QGroupBox("Parámetros de detección")
        grp_lay = QHBoxLayout(grp)
        grp_lay.setSpacing(24)

        col_ior = QVBoxLayout()
        col_ior.addWidget(QLabel("Umbral IOR"))
        self._spin_ior = QDoubleSpinBox()
        self._spin_ior.setRange(0.5, 3.0)
        self._spin_ior.setSingleStep(0.05)
        self._spin_ior.setValue(1.0)
        col_ior.addWidget(self._spin_ior)
        lbl_ior = QLabel("Ratio mínimo para considerar\nanomalia de hierro")
        lbl_ior.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;")
        col_ior.addWidget(lbl_ior)
        grp_lay.addLayout(col_ior)

        col_clay = QVBoxLayout()
        col_clay.addWidget(QLabel("Umbral Clay"))
        self._spin_clay = QDoubleSpinBox()
        self._spin_clay.setRange(0.5, 3.0)
        self._spin_clay.setSingleStep(0.05)
        self._spin_clay.setValue(1.0)
        col_clay.addWidget(self._spin_clay)
        lbl_clay = QLabel("Ratio mínimo para considerar\nanomalía arcillosa")
        lbl_clay.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;")
        col_clay.addWidget(lbl_clay)
        grp_lay.addLayout(col_clay)

        col_area = QVBoxLayout()
        col_area.addWidget(QLabel("Área mínima (píxeles)"))
        self._spin_area = QSpinBox()
        self._spin_area.setRange(5, 5000)
        self._spin_area.setValue(50)
        col_area.addWidget(self._spin_area)
        lbl_area = QLabel("Clusters más pequeños\nserán ignorados")
        lbl_area.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;")
        col_area.addWidget(lbl_area)
        grp_lay.addLayout(col_area)

        grp_lay.addStretch()
        root.addWidget(grp)
        root.addSpacing(12)

        # ── Botón ──────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_run = QPushButton("Ejecutar análisis")
        self._btn_run.setFixedWidth(220)
        self._btn_run.clicked.connect(self._run_analysis)
        btn_row.addWidget(self._btn_run)
        root.addLayout(btn_row)
        root.addSpacing(8)

        # ── Progreso ───────────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 4)
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        root.addWidget(self._progress)
        root.addSpacing(8)

        # ── Splitter: tabla (arriba) / mapa (abajo) ───────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)

        # Panel superior: tabla
        top = QWidget()
        top.setStyleSheet("background:transparent;")
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(4)

        lbl_tbl = QLabel("TARGETS DETECTADOS")
        lbl_tbl.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:10px;"
            f"font-weight:bold;letter-spacing:1px;"
        )
        top_lay.addWidget(lbl_tbl)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["#", "Score", "Prioridad", "Área (ha)", "IOR Medio", "Clay Medio", "Litología"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        top_lay.addWidget(self._table)

        self._lbl_resumen = QLabel("")
        self._lbl_resumen.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:11px;padding-top:4px;"
        )
        top_lay.addWidget(self._lbl_resumen)

        splitter.addWidget(top)

        # Panel inferior: mapa
        self._map_widget = MapWidget("MAPA DE TARGETS — prioridad por color")
        self._map_widget.generate_clicked.connect(self._gen_map)
        splitter.addWidget(self._map_widget)

        # Tamaños iniciales: 55% tabla, 45% mapa
        splitter.setSizes([320, 260])

        root.addWidget(splitter, 1)

    # ── Pipeline ───────────────────────────────────────────────────────────────

    def _run_analysis(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo.")
            return

        self._btn_run.setEnabled(False)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._table.setRowCount(0)
        self._lbl_resumen.setText("")
        self._log("Iniciando análisis de targets…")
        self._status("Analizando…")

        from terraf.pipeline.analyze import ejecutar_analisis
        from terraf.gui.workers import PipelineWorker

        self._worker = PipelineWorker(
            ejecutar_analisis,
            self._db_path,
            umbral_ior=self._spin_ior.value(),
            umbral_clay=self._spin_clay.value(),
            min_area_px=self._spin_area.value(),
        )
        self._worker.step_signal.connect(self._on_step)
        self._worker.done_signal.connect(self._on_done)
        self._worker.error_signal.connect(self._on_error)
        self._run(self._worker)

    def _on_step(self, msg: str) -> None:
        self._progress.setValue(min(self._progress.value() + 1, 4))
        self._log_step(msg)

    def _on_done(self, resultado) -> None:
        self._progress.setVisible(False)
        self._btn_run.setEnabled(True)

        targets = resultado.targets
        self._table.setRowCount(len(targets))

        _PRIO_COLORS = {
            "ALTA":  COLORES["success"],
            "MEDIA": COLORES["warning"],
            "BAJA":  COLORES["text_muted"],
        }

        for i, t in enumerate(targets):
            vals = [
                t.nombre or f"T{i+1}",
                f"{t.score:.3f}" if t.score else "—",
                t.prioridad or "—",
                f"{t.area_ha:.2f}" if t.area_ha else "—",
                f"{t.ior_media:.3f}" if t.ior_media else "—",
                f"{t.clay_media:.3f}" if t.clay_media else "—",
                t.litologia_dominante or "—",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                if j == 2:
                    from PyQt5.QtGui import QColor
                    item.setForeground(QColor(_PRIO_COLORS.get(v, COLORES["text"])))
                self._table.setItem(i, j, item)

        n_alta  = sum(1 for t in targets if t.prioridad == "ALTA")
        n_media = sum(1 for t in targets if t.prioridad == "MEDIA")
        n_baja  = sum(1 for t in targets if t.prioridad == "BAJA")
        self._lbl_resumen.setText(
            f"Total: {len(targets)} targets  ·  "
            f"Alta: {n_alta}  ·  Media: {n_media}  ·  Baja: {n_baja}"
        )

        self._log_ok(f"Análisis completo: {len(targets)} targets detectados")
        self._status(f"Análisis: {len(targets)} targets  ·  {n_alta} alta prioridad")

        # Auto-generar mapa si hay targets con coordenadas
        if targets:
            self._gen_map()

    def _on_error(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._btn_run.setEnabled(True)
        self._log_err(msg)
        self._status("Error en análisis")
        QMessageBox.critical(self, "Error en análisis", msg)

    # ── Mapa ───────────────────────────────────────────────────────────────────

    def _gen_map(self) -> None:
        if self._db_path is None:
            return
        self._map_widget.set_busy(True)

        from terraf.pipeline.mapper import mapa_analisis
        from terraf.gui.workers import SimpleWorker

        self._map_worker = SimpleWorker(
            lambda: mapa_analisis(self._db_path, abrir=False)
        )
        self._map_worker.done_signal.connect(self._on_map_done)
        self._map_worker.error_signal.connect(self._on_map_error)
        self._run(self._map_worker)

    def _on_map_done(self, path) -> None:
        self._map_widget.load_path(path)
        self._log_step(f"Mapa generado: {path.name}")

    def _on_map_error(self, msg: str) -> None:
        self._map_widget.set_busy(False)
        self._log_err(f"Mapa: {msg}")
