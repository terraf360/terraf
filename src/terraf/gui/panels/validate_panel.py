"""
Panel Validar — Registra validaciones de campo sobre los targets.
Incluye mapa interactivo con estado de validación por color.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.map_widget import MapWidget
from terraf.gui.panels.base import BasePanel
from terraf.gui.style import COLORES
from terraf.pipeline.validation import METODOS_VALIDOS, RESULTADOS_VALIDOS

_RESULTADO_COLORS = {
    "positivo":  "#a6e3a1",
    "negativo":  "#f38ba8",
    "dudoso":    "#f9e2af",
    "pendiente": "#6c7086",
}

_RESULTADO_SYM = {
    "positivo":  "✓ POSITIVO",
    "negativo":  "✗ NEGATIVO",
    "dudoso":    "? DUDOSO",
    "pendiente": "○ PENDIENTE",
}


class ValidatePanel(BasePanel):
    """Panel de validaciones de campo."""

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        for w in self._make_title(
            "Validaciones de Campo",
            "Registra el resultado de visitar cada target en campo. "
            "Selecciona un target de la tabla, elige el resultado y guarda. "
            "Estos datos se usan para entrenar el modelo ML.",
        ).children():
            if isinstance(w, QWidget):
                root.addWidget(w)

        root.addSpacing(12)

        # ── Formulario de entrada rápida ───────────────────────────────────────
        form_lay = QHBoxLayout()
        form_lay.setSpacing(12)

        form_lay.addWidget(QLabel("Target:"))
        self._combo_target = QComboBox()
        self._combo_target.setMinimumWidth(120)
        self._combo_target.setEditable(True)
        form_lay.addWidget(self._combo_target)

        form_lay.addWidget(QLabel("Resultado:"))
        self._combo_resultado = QComboBox()
        for r in RESULTADOS_VALIDOS:
            self._combo_resultado.addItem(_RESULTADO_SYM.get(r, r), r)
        form_lay.addWidget(self._combo_resultado)

        form_lay.addWidget(QLabel("Método:"))
        self._combo_metodo = QComboBox()
        self._combo_metodo.addItem("—", None)
        for m in METODOS_VALIDOS:
            self._combo_metodo.addItem(m.capitalize(), m)
        form_lay.addWidget(self._combo_metodo)

        form_lay.addWidget(QLabel("Notas:"))
        self._input_notas = QLineEdit()
        self._input_notas.setPlaceholderText("Observaciones opcionales…")
        form_lay.addWidget(self._input_notas)

        self._btn_save = QPushButton("Guardar")
        self._btn_save.setFixedWidth(100)
        self._btn_save.clicked.connect(self._save_validation)
        form_lay.addWidget(self._btn_save)

        root.addLayout(form_lay)
        root.addSpacing(10)

        # ── Barra de progreso de validación ───────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        root.addWidget(self._progress_bar)

        self._lbl_prog = QLabel("0 / 0 validados  (0%)")
        self._lbl_prog.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:11px;padding:3px 0;"
        )
        root.addWidget(self._lbl_prog)
        root.addSpacing(6)

        # ── Filtros ────────────────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filtrar:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["Todos", "Pendientes", "Positivos", "Negativos", "Dudosos"])
        self._filter_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self._filter_combo)
        filter_row.addStretch()

        btn_refresh = QPushButton("Actualizar")
        btn_refresh.setProperty("secondary", "1")
        btn_refresh.clicked.connect(self.refresh)
        filter_row.addWidget(btn_refresh)
        root.addLayout(filter_row)
        root.addSpacing(6)

        # ── Splitter: tabla (arriba) / mapa (abajo) ───────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)

        # Panel superior: tabla
        top = QWidget()
        top.setStyleSheet("background:transparent;")
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(0)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["#", "Score", "Prioridad", "Prob. ML", "Resultado", "Método", "Notas"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        top_lay.addWidget(self._table)

        splitter.addWidget(top)

        # Panel inferior: mapa
        self._map_widget = MapWidget("MAPA DE VALIDACIONES — color por resultado de campo")
        self._map_widget.generate_clicked.connect(self._gen_map)
        splitter.addWidget(self._map_widget)

        splitter.setSizes([300, 280])

        root.addWidget(splitter, 1)

    # ── Datos ──────────────────────────────────────────────────────────────────

    def on_db_ready(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self._db_path is None:
            return

        filtro = self._filter_combo.currentText() if hasattr(self, "_filter_combo") else "Todos"
        solo_pend = filtro == "Pendientes"

        from terraf.gui.workers import SimpleWorker
        from terraf.pipeline.validation import listar_validaciones, resumen_validaciones

        def load():
            targets = listar_validaciones(self._db_path, solo_pendientes=solo_pend)
            resumen = resumen_validaciones(self._db_path)
            return targets, resumen, filtro

        self._worker_ref = SimpleWorker(load)
        self._worker_ref.done_signal.connect(self._render)
        self._worker_ref.error_signal.connect(lambda e: self._log_err(e))
        self._run(self._worker_ref)

    def _render(self, payload) -> None:
        targets, resumen, filtro = payload

        if filtro == "Positivos":
            targets = [t for t in targets if t.resultado == "positivo"]
        elif filtro == "Negativos":
            targets = [t for t in targets if t.resultado == "negativo"]
        elif filtro == "Dudosos":
            targets = [t for t in targets if t.resultado == "dudoso"]

        # Combo de targets
        self._combo_target.clear()
        for t in targets:
            self._combo_target.addItem(t.nombre, t.nombre)

        # Barra de progreso
        pct = int(resumen.pct_completado)
        self._progress_bar.setValue(pct)
        self._lbl_prog.setText(
            f"{resumen.validados} / {resumen.total_targets} validados  ({pct}%)   ·   "
            f"✓ {resumen.positivos} pos   ✗ {resumen.negativos} neg   "
            f"? {resumen.dudosos} dudosos"
        )

        # Tabla
        self._table.setRowCount(len(targets))
        for i, t in enumerate(targets):
            res = t.resultado or "pendiente"
            color = QColor(_RESULTADO_COLORS.get(res, COLORES["text_muted"]))
            vals = [
                t.nombre,
                f"{t.score:.3f}",
                t.prioridad,
                f"{t.prob_positivo:.2f}" if t.prob_positivo is not None else "—",
                _RESULTADO_SYM.get(res, res),
                t.metodo or "—",
                t.notas or "",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                if j == 4:
                    item.setForeground(color)
                self._table.setItem(i, j, item)

        self._status(
            f"Validaciones: {resumen.validados}/{resumen.total_targets}  "
            f"·  {resumen.positivos} pos  ·  {resumen.negativos} neg"
        )

        # Auto-generar mapa
        self._gen_map()

    # ── Selección en tabla ─────────────────────────────────────────────────────

    def _on_row_selected(self) -> None:
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        res_txt = self._table.item(row, 4)
        if not res_txt:
            return
        txt = res_txt.text()
        for r, sym in _RESULTADO_SYM.items():
            if sym == txt:
                idx = self._combo_resultado.findData(r)
                if idx >= 0:
                    self._combo_resultado.setCurrentIndex(idx)
                break
        nombre_item = self._table.item(row, 0)
        if nombre_item:
            idx_t = self._combo_target.findText(nombre_item.text())
            if idx_t >= 0:
                self._combo_target.setCurrentIndex(idx_t)

    # ── Guardar validación ─────────────────────────────────────────────────────

    def _save_validation(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo.")
            return

        identificador = self._combo_target.currentText().strip()
        resultado     = self._combo_resultado.currentData()
        metodo        = self._combo_metodo.currentData()
        notas         = self._input_notas.text().strip() or None

        if not identificador:
            QMessageBox.warning(self, "Sin target", "Selecciona o escribe el nombre del target.")
            return

        self._btn_save.setEnabled(False)
        self._log(f"Guardando: {identificador} → {resultado}")

        from terraf.pipeline.validation import validar_target
        from terraf.gui.workers import SimpleWorker

        def do_save():
            return validar_target(
                self._db_path, identificador, resultado, metodo, notas
            )

        self._save_worker = SimpleWorker(do_save)
        self._save_worker.done_signal.connect(self._on_saved)
        self._save_worker.error_signal.connect(self._on_save_error)
        self._run(self._save_worker)

    def _on_saved(self, info) -> None:
        self._btn_save.setEnabled(True)
        accion = "actualizado" if info.actualizado else "guardado"
        self._log_ok(f"{info.target_nombre} → {info.resultado} ({accion})")
        self._input_notas.clear()
        self.refresh()

    def _on_save_error(self, msg: str) -> None:
        self._btn_save.setEnabled(True)
        self._log_err(msg)
        QMessageBox.warning(self, "Error al guardar", msg)

    # ── Mapa ───────────────────────────────────────────────────────────────────

    def _gen_map(self) -> None:
        if self._db_path is None:
            return
        self._map_widget.set_busy(True)

        from terraf.pipeline.mapper import mapa_validaciones
        from terraf.gui.workers import SimpleWorker

        self._map_worker = SimpleWorker(
            lambda: mapa_validaciones(self._db_path, abrir=False)
        )
        self._map_worker.done_signal.connect(self._on_map_done)
        self._map_worker.error_signal.connect(self._on_map_error)
        self._run(self._map_worker)

    def _on_map_done(self, path) -> None:
        self._map_widget.load_path(path)
        self._log_step(f"Mapa actualizado: {path.name}")

    def _on_map_error(self, msg: str) -> None:
        self._map_widget.set_busy(False)
        self._log_err(f"Mapa: {msg}")
