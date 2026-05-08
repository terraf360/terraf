"""
Panel Índices Espectrales — Calcula IOR, Clay, NDVI, etc.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.panels.base import BasePanel
from terraf.gui.style import COLORES

# Descripción de cada índice para mostrar en la UI
_INDICES_INFO = {
    "ior":     ("Iron Oxide Ratio",   "Detecta óxidos de hierro (alteración hidrotermal)"),
    "clay":    ("Clay Ratio",         "Detecta minerales arcillosos (caolinita, alunita)"),
    "ferrous": ("Ferrous Minerals",   "Minerales ferrosos (piroxenos, anfíboles)"),
    "ndvi":    ("NDVI",               "Índice de vegetación — ayuda a enmascarar cobertura"),
    "ndwi":    ("NDWI",               "Índice de agua — detecta humedad y cuerpos de agua"),
    "evi":     ("EVI",                "Índice de vegetación mejorado"),
    "savi":    ("SAVI",               "NDVI corregido por suelo"),
}


class IndicesPanel(BasePanel):
    """Panel para calcular índices espectrales."""

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        for w in self._make_title(
            "📊  Índices Espectrales",
            "Calcula índices espectrales sobre la imagen cargada. "
            "Estos índices resaltan anomalías minerales y de alteración en el terreno.",
        ).children():
            if isinstance(w, QWidget):
                root.addWidget(w)

        root.addSpacing(16)

        # ── Selección de índices ───────────────────────────────────────────────
        grp = QGroupBox("Índices a calcular")
        grp_lay = QGridLayout(grp)
        grp_lay.setSpacing(10)

        self._checks: dict[str, QCheckBox] = {}
        for i, (key, (nombre, desc)) in enumerate(_INDICES_INFO.items()):
            row, col = divmod(i, 2)
            cell = QVBoxLayout()
            chk = QCheckBox(nombre)
            chk.setChecked(True)  # todos activados por defecto
            chk.setStyleSheet(f"font-weight:bold;color:{COLORES['text']};")
            cell.addWidget(chk)
            lbl_d = QLabel(desc)
            lbl_d.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;margin-left:24px;")
            cell.addWidget(lbl_d)
            w_cell = QWidget()
            w_cell.setStyleSheet("background:transparent;")
            w_cell.setLayout(cell)
            grp_lay.addWidget(w_cell, row, col)
            self._checks[key] = chk

        root.addWidget(grp)
        root.addSpacing(12)

        # ── Opciones adicionales ───────────────────────────────────────────────
        opts_lay = QHBoxLayout()
        self._chk_force = QCheckBox("Recalcular si ya existen (forzar)")
        self._chk_force.setStyleSheet(f"color:{COLORES['text_muted']};")
        opts_lay.addWidget(self._chk_force)
        opts_lay.addStretch()
        root.addLayout(opts_lay)
        root.addSpacing(12)

        # ── Botones ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_sel_all = QPushButton("Seleccionar todos")
        btn_sel_all.setProperty("class", "secondary")
        btn_sel_all.clicked.connect(lambda: [c.setChecked(True) for c in self._checks.values()])
        btn_row.addWidget(btn_sel_all)

        btn_sel_min = QPushButton("Solo IOR + Clay")
        btn_sel_min.setProperty("class", "secondary")
        btn_sel_min.clicked.connect(self._select_minimal)
        btn_row.addWidget(btn_sel_min)

        btn_row.addStretch()

        self._btn_calc = QPushButton("▶  Calcular índices")
        self._btn_calc.setFixedWidth(200)
        self._btn_calc.clicked.connect(self._run)
        btn_row.addWidget(self._btn_calc)
        root.addLayout(btn_row)

        root.addSpacing(16)

        # ── Progreso ───────────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        root.addWidget(self._progress)

        root.addSpacing(16)

        # ── Resultado ──────────────────────────────────────────────────────────
        self._result_card = QWidget()
        self._result_card.setVisible(False)
        res_lay = QVBoxLayout(self._result_card)
        res_lay.setSpacing(4)

        lbl_res = QLabel("RESULTADOS")
        lbl_res.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;"
        )
        res_lay.addWidget(lbl_res)
        self._result_grid = QGridLayout()
        self._result_grid.setSpacing(6)
        res_lay.addLayout(self._result_grid)

        root.addWidget(self._result_card)
        root.addStretch()

    def _select_minimal(self) -> None:
        for key, chk in self._checks.items():
            chk.setChecked(key in ("ior", "clay"))

    def _run(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo.")
            return

        seleccionados = [k for k, c in self._checks.items() if c.isChecked()]
        if not seleccionados:
            QMessageBox.warning(self, "Sin selección", "Selecciona al menos un índice.")
            return

        self._btn_calc.setEnabled(False)
        self._progress.setVisible(True)
        self._result_card.setVisible(False)
        self._log(f"Calculando índices: {', '.join(seleccionados)}")
        self._status("Calculando índices espectrales…")

        from terraf.pipeline.indices import calcular_indices
        from terraf.gui.workers import PipelineWorker

        self._worker = PipelineWorker(
            calcular_indices,
            self._db_path,
            indices=seleccionados,
            forzar=self._chk_force.isChecked(),
            guardar_raster=True,
        )
        self._worker.step_signal.connect(self._log_step)
        self._worker.done_signal.connect(self._on_done)
        self._worker.error_signal.connect(self._on_error)
        self._run(self._worker)

    def _on_done(self, resultados) -> None:
        self._progress.setVisible(False)
        self._btn_calc.setEnabled(True)

        # Limpiar grid previo
        while self._result_grid.count():
            item = self._result_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Headers
        for col, hdr in enumerate(["Índice", "Media", "Mín", "Máx", "% > umbral", "Estado"]):
            lbl = QLabel(hdr)
            lbl.setStyleSheet(
                f"color:{COLORES['text_muted']};font-size:11px;font-weight:bold;letter-spacing:0.5px;"
            )
            self._result_grid.addWidget(lbl, 0, col)

        for row, r in enumerate(resultados, start=1):
            nombre = _INDICES_INFO.get(r.nombre_indice, (r.nombre_indice, ""))[0]
            vals = [
                nombre,
                f"{r.media:.4f}" if r.media is not None else "—",
                f"{r.min_val:.4f}" if r.min_val is not None else "—",
                f"{r.max_val:.4f}" if r.max_val is not None else "—",
                f"{r.pct_sobre_umbral:.1f}%" if r.pct_sobre_umbral is not None else "—",
                "✓ OK" if not r.ya_existia else "○ Ya existía",
            ]
            for col, v in enumerate(vals):
                lbl = QLabel(str(v))
                if col == 5:
                    lbl.setStyleSheet(f"color:{COLORES['success'] if '✓' in v else COLORES['text_muted']};")
                self._result_grid.addWidget(lbl, row, col)

        self._result_card.setVisible(True)
        self._log_ok(f"Calculados {len(resultados)} índices")
        self._status(f"Índices: {len(resultados)} calculados")

    def _on_error(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._btn_calc.setEnabled(True)
        self._log_err(msg)
        self._status("Error en cálculo de índices")
        QMessageBox.critical(self, "Error", msg)
