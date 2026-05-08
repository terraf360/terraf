"""
Panel ML — Entrena, predice y mejora con active learning.
Usa tabs: [Entrenar] [Predecir] [Mejorar]
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.map_widget import MapWidget
from terraf.gui.panels.base import BasePanel
from terraf.gui.style import COLORES
from terraf.pipeline.ml.priors import TIPOS_DEPOSITO, prior_description


class MLPanel(BasePanel):
    """Panel unificado de ML: Train / Predict / Improve."""

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        for w in self._make_title(
            "🤖  Módulo ML",
            "Entrena un clasificador con priors espectrales + datos de campo, "
            "predice la probabilidad de ser target positivo y sugiere qué validar después.",
        ).children():
            if isinstance(w, QWidget):
                root.addWidget(w)

        root.addSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._build_train_tab(),   "⚙  Entrenar")
        tabs.addTab(self._build_predict_tab(), "🔮  Predecir")
        tabs.addTab(self._build_improve_tab(), "🔄  Mejorar")
        root.addWidget(tabs)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: ENTRENAR
    # ─────────────────────────────────────────────────────────────────────────

    def _build_train_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # Tipo de depósito
        grp = QGroupBox("Configuración del modelo")
        grp_lay = QHBoxLayout(grp)
        grp_lay.setSpacing(20)

        col_tipo = QVBoxLayout()
        col_tipo.addWidget(QLabel("Tipo de depósito:"))
        self._combo_tipo = QComboBox()
        for t in TIPOS_DEPOSITO:
            self._combo_tipo.addItem(t, t)
        self._combo_tipo.setCurrentText("generico")
        self._combo_tipo.currentIndexChanged.connect(self._update_tipo_desc)
        col_tipo.addWidget(self._combo_tipo)
        grp_lay.addLayout(col_tipo)

        col_synth = QVBoxLayout()
        col_synth.addWidget(QLabel("Muestras sintéticas / clase:"))
        self._spin_synth = QSpinBox()
        self._spin_synth.setRange(20, 500)
        self._spin_synth.setValue(100)
        self._spin_synth.setSingleStep(20)
        col_synth.addWidget(self._spin_synth)
        grp_lay.addLayout(col_synth)

        grp_lay.addStretch()
        lay.addWidget(grp)

        # Descripción del tipo
        self._lbl_tipo_desc = QLabel(prior_description("generico"))
        self._lbl_tipo_desc.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:11px;padding:4px 0;"
        )
        self._lbl_tipo_desc.setWordWrap(True)
        lay.addWidget(self._lbl_tipo_desc)

        # Botón entrenar
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_train = QPushButton("▶  Entrenar modelo")
        self._btn_train.setFixedWidth(200)
        self._btn_train.clicked.connect(self._run_train)
        btn_row.addWidget(self._btn_train)
        lay.addLayout(btn_row)

        # Progreso
        self._train_progress = QProgressBar()
        self._train_progress.setRange(0, 0)
        self._train_progress.setVisible(False)
        self._train_progress.setFixedHeight(6)
        lay.addWidget(self._train_progress)

        # Resultado
        self._train_result = QWidget()
        self._train_result.setVisible(False)
        tr_lay = QVBoxLayout(self._train_result)
        tr_lay.setContentsMargins(0, 8, 0, 0)
        tr_lay.setSpacing(4)

        lbl_r = QLabel("RESULTADO DEL ENTRENAMIENTO")
        lbl_r.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;"
        )
        tr_lay.addWidget(lbl_r)
        self._train_info_lay = QVBoxLayout()
        tr_lay.addLayout(self._train_info_lay)
        lay.addWidget(self._train_result)
        lay.addStretch()

        return w

    def _update_tipo_desc(self) -> None:
        tipo = self._combo_tipo.currentData()
        self._lbl_tipo_desc.setText(prior_description(tipo or "generico"))

    def _run_train(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo.")
            return

        tipo = self._combo_tipo.currentData()
        n_synth = self._spin_synth.value()

        self._btn_train.setEnabled(False)
        self._train_progress.setVisible(True)
        self._train_result.setVisible(False)
        self._log(f"Entrenando modelo: tipo={tipo}, sintéticos={n_synth}×2")
        self._status("Entrenando modelo ML…")

        from terraf.pipeline.ml.trainer import entrenar
        from terraf.gui.workers import PipelineWorker

        self._train_worker = PipelineWorker(
            entrenar,
            self._db_path,
            tipo_deposito=tipo,
            n_sinteticos=n_synth,
        )
        self._train_worker.step_signal.connect(self._log_step)
        self._train_worker.done_signal.connect(self._on_train_done)
        self._train_worker.error_signal.connect(self._on_train_error)
        self._run(self._train_worker)

    def _on_train_done(self, info) -> None:
        self._train_progress.setVisible(False)
        self._btn_train.setEnabled(True)

        # Limpiar y rellenar resultado
        while self._train_info_lay.count():
            item = self._train_info_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        campos = [
            ("Versión:",          info.version),
            ("Tipo depósito:",    info.tipo_deposito),
            ("Muestras totales:", str(info.n_total)),
            ("  Sintéticas:",     str(info.n_sinteticos)),
            ("  Reales:",         str(info.n_reales)),
            ("CV accuracy:",      f"{info.score_cv:.1%}" if info.score_cv else "—"),
            ("Guardado en:",      str(info.ruta_pkl.name)),
        ]
        for k, v in campos:
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_w.setLayout(self._kv_row(k, v))
            self._train_info_lay.addWidget(row_w)

        self._train_result.setVisible(True)
        self._log_ok(f"Modelo entrenado: {info.version}  ·  {info.n_reales} datos reales")

        if info.n_reales == 0:
            self._log("  ⚠  Solo priors sintéticos — valida targets en campo para mejorar")
        self._status(f"Modelo entrenado: {info.tipo_deposito}  ·  {info.n_reales} reales")

    def _on_train_error(self, msg: str) -> None:
        self._train_progress.setVisible(False)
        self._btn_train.setEnabled(True)
        self._log_err(msg)
        self._status("Error en entrenamiento")
        QMessageBox.critical(self, "Error al entrenar", msg)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: PREDECIR
    # ─────────────────────────────────────────────────────────────────────────

    def _build_predict_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # Descripción
        lbl_info = QLabel(
            "Aplica el modelo más reciente a todos los targets del análisis "
            "y actualiza su probabilidad ML (prob_positivo) en la base de datos."
        )
        lbl_info.setStyleSheet(f"color:{COLORES['text_muted']};font-size:12px;")
        lbl_info.setWordWrap(True)
        lay.addWidget(lbl_info)

        # Botón + progreso
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_predict = QPushButton("Predecir")
        self._btn_predict.setFixedWidth(160)
        self._btn_predict.clicked.connect(self._run_predict)
        btn_row.addWidget(self._btn_predict)
        lay.addLayout(btn_row)

        self._pred_progress = QProgressBar()
        self._pred_progress.setRange(0, 0)
        self._pred_progress.setVisible(False)
        self._pred_progress.setFixedHeight(6)
        lay.addWidget(self._pred_progress)

        # Resumen de resultados (footer)
        self._pred_resumen = QLabel("")
        self._pred_resumen.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:11px;"
        )
        lay.addWidget(self._pred_resumen)

        # ── Splitter: tabla top-15 (arriba) / mapa de predicciones (abajo) ────
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)

        top = QWidget()
        top.setStyleSheet("background:transparent;")
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(4)

        lbl_top = QLabel("TOP 15 — MAYOR PROBABILIDAD ML")
        lbl_top.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:10px;"
            f"font-weight:bold;letter-spacing:1px;"
        )
        top_lay.addWidget(lbl_top)

        self._pred_table = QTableWidget(0, 4)
        self._pred_table.setHorizontalHeaderLabels(["#", "Prob. ML", "Score", "Confianza"])
        self._pred_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._pred_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._pred_table.verticalHeader().setVisible(False)
        top_lay.addWidget(self._pred_table)

        splitter.addWidget(top)

        # Mapa de predicciones ML
        self._pred_map_widget = MapWidget("MAPA ML — probabilidad por color (rojo = alta)")
        self._pred_map_widget.generate_clicked.connect(self._gen_pred_map)
        splitter.addWidget(self._pred_map_widget)

        splitter.setSizes([250, 260])
        lay.addWidget(splitter, 1)

        return w

    def _run_predict(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo.")
            return

        self._btn_predict.setEnabled(False)
        self._pred_progress.setVisible(True)
        self._pred_table.setRowCount(0)
        self._log("Aplicando modelo ML a todos los targets…")
        self._status("Prediciendo…")

        from terraf.pipeline.ml.predictor import predecir
        from terraf.gui.workers import PipelineWorker

        self._pred_worker = PipelineWorker(predecir, self._db_path)
        self._pred_worker.step_signal.connect(self._log_step)
        self._pred_worker.done_signal.connect(self._on_predict_done)
        self._pred_worker.error_signal.connect(self._on_predict_error)
        self._run(self._pred_worker)

    def _on_predict_done(self, info) -> None:
        self._pred_progress.setVisible(False)
        self._btn_predict.setEnabled(True)

        self._pred_resumen.setText(
            f"{info.n_targets} targets actualizados  ·  "
            f"Alta (≥70%): {info.n_alta}  ·  "
            f"Media: {info.n_media}  ·  "
            f"Baja: {info.n_baja}  ·  "
            f"Prob. media: {info.prob_media:.1%}"
        )
        self._log_ok(f"Predicción completa: {info.n_targets} targets  ·  {info.n_alta} de alta confianza")
        self._status(f"Predicción: {info.n_targets} targets  ·  {info.n_alta} alta conf.")

        # Cargar tabla top-15
        from terraf.pipeline.ml.predictor import obtener_predicciones
        from terraf.gui.workers import SimpleWorker

        def load_top():
            return obtener_predicciones(self._db_path, top_n=15)

        self._top_worker = SimpleWorker(load_top)
        self._top_worker.done_signal.connect(self._render_top)
        self._run(self._top_worker)

    def _render_top(self, predicciones) -> None:
        self._pred_table.setRowCount(len(predicciones))
        for i, p in enumerate(predicciones):
            prob = p.prob_positivo
            if prob >= 0.70:
                conf, color = "ALTA", COLORES["success"]
            elif prob >= 0.40:
                conf, color = "MEDIA", COLORES["warning"]
            else:
                conf, color = "BAJA", COLORES["text_muted"]

            vals = [p.nombre, f"{prob:.1%}", f"{p.score_original:.3f}", conf]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                if j == 3:
                    from PyQt5.QtGui import QColor
                    item.setForeground(QColor(color))
                self._pred_table.setItem(i, j, item)

        # Auto-generar mapa de predicciones
        self._gen_pred_map()

    def _gen_pred_map(self) -> None:
        if self._db_path is None:
            return
        self._pred_map_widget.set_busy(True)

        from terraf.pipeline.mapper import mapa_prediccion
        from terraf.gui.workers import SimpleWorker

        self._pred_map_worker = SimpleWorker(
            lambda: mapa_prediccion(self._db_path, abrir=False)
        )
        self._pred_map_worker.done_signal.connect(self._on_pred_map_done)
        self._pred_map_worker.error_signal.connect(self._on_pred_map_error)
        self._run(self._pred_map_worker)

    def _on_pred_map_done(self, path) -> None:
        self._pred_map_widget.load_path(path)
        self._log_step(f"Mapa ML generado: {path.name}")

    def _on_pred_map_error(self, msg: str) -> None:
        self._pred_map_widget.set_busy(False)
        self._log_err(f"Mapa ML: {msg}")

    def _on_predict_error(self, msg: str) -> None:
        self._pred_progress.setVisible(False)
        self._btn_predict.setEnabled(True)
        self._log_err(msg)
        self._status("Error en predicción")
        QMessageBox.critical(self, "Error al predecir", msg)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: MEJORAR (Active Learning)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_improve_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        lbl_info = QLabel(
            "El active learning selecciona los targets que más información aportarían "
            "al modelo si fueran validados en campo. Se priorizan los de mayor incertidumbre "
            "(probabilidad más cercana al 50%)."
        )
        lbl_info.setStyleSheet(f"color:{COLORES['text_muted']};font-size:12px;")
        lbl_info.setWordWrap(True)
        lay.addWidget(lbl_info)

        # Estado del ciclo
        self._improve_state_card = QWidget()
        self._improve_state_card.setVisible(False)
        state_lay = QVBoxLayout(self._improve_state_card)
        state_lay.setContentsMargins(0, 0, 0, 0)
        state_lay.setSpacing(4)
        self._improve_state_info = QVBoxLayout()
        state_lay.addLayout(self._improve_state_info)
        lay.addWidget(self._improve_state_card)

        btn_row = QHBoxLayout()
        self._btn_improve = QPushButton("🔍  Calcular sugerencias")
        self._btn_improve.setFixedWidth(220)
        self._btn_improve.clicked.connect(self._run_improve)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_improve)
        lay.addLayout(btn_row)

        # Tabla sugerencias
        lbl_sug = QLabel("SUGERENCIAS DE CAMPO")
        lbl_sug.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;margin-top:8px;"
        )
        lay.addWidget(lbl_sug)

        self._improve_table = QTableWidget(0, 5)
        self._improve_table.setHorizontalHeaderLabels(
            ["#", "Prob. ML", "Incertidumbre", "Prioridad", "Razón"]
        )
        self._improve_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._improve_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._improve_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._improve_table.verticalHeader().setVisible(False)
        lay.addWidget(self._improve_table)

        # Flujo de trabajo
        self._lbl_ciclo = QLabel("")
        self._lbl_ciclo.setStyleSheet(
            f"color:{COLORES['accent']};font-size:12px;padding-top:8px;"
        )
        self._lbl_ciclo.setWordWrap(True)
        lay.addWidget(self._lbl_ciclo)

        lay.addStretch()
        return w

    def on_db_ready(self) -> None:
        self._load_improve_state()

    def _load_improve_state(self) -> None:
        if self._db_path is None:
            return
        from terraf.pipeline.ml.active_learning import estado_active_learning
        from terraf.gui.workers import SimpleWorker

        self._state_worker = SimpleWorker(
            lambda: estado_active_learning(self._db_path)
        )
        self._state_worker.done_signal.connect(self._render_state)
        self._run(self._state_worker)

    def _render_state(self, st: dict) -> None:
        if not st:
            return
        # Limpiar
        while self._improve_state_info.count():
            item = self._improve_state_info.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        campos = [
            ("Targets totales:", str(st.get("n_targets", 0))),
            ("Validados:",
             f"{st.get('n_validados', 0)} "
             f"({st.get('n_positivos', 0)} pos, {st.get('n_negativos', 0)} neg)"),
            ("Sin validar:",    str(st.get("n_sin_validar", 0))),
            ("Con prob. ML:",   str(st.get("n_con_prob", 0))),
        ]
        if st.get("prob_media") is not None:
            campos.append(("Prob. media ML:", f"{st['prob_media']:.1%}"))

        for k, v in campos:
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_w.setLayout(self._kv_row(k, v))
            self._improve_state_info.addWidget(row_w)

        self._improve_state_card.setVisible(True)
        ciclo = st.get("ciclo_sugerido", "")
        self._lbl_ciclo.setText(f"💡  {ciclo}")

    def _run_improve(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo.")
            return

        self._btn_improve.setEnabled(False)
        self._improve_table.setRowCount(0)
        self._log("Calculando sugerencias de active learning…")
        self._status("Active learning…")

        from terraf.pipeline.ml.active_learning import sugerir_validaciones
        from terraf.gui.workers import SimpleWorker

        self._imp_worker = SimpleWorker(
            lambda: sugerir_validaciones(self._db_path, top_n=10)
        )
        self._imp_worker.done_signal.connect(self._on_improve_done)
        self._imp_worker.error_signal.connect(self._on_improve_error)
        self._run(self._imp_worker)

    def _on_improve_done(self, payload) -> None:
        sugerencias, resumen = payload
        self._btn_improve.setEnabled(True)

        self._improve_table.setRowCount(len(sugerencias))
        _PRIO_COLORS = {
            "ALTA":  COLORES["success"],
            "MEDIA": COLORES["warning"],
            "BAJA":  COLORES["text_muted"],
        }
        from PyQt5.QtGui import QColor

        for i, s in enumerate(sugerencias):
            prob_txt = f"{s.prob_positivo:.0%}" if s.prob_positivo is not None else "—"
            inc = s.incertidumbre
            vals = [
                s.nombre,
                prob_txt,
                f"{inc:.2f}",
                s.prioridad,
                s.razon,
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignCenter if j < 4 else Qt.AlignLeft))
                if j == 2:  # incertidumbre — rojo si muy incierto
                    color = COLORES["error"] if inc < 0.1 else (COLORES["warning"] if inc < 0.25 else COLORES["text_muted"])
                    item.setForeground(QColor(color))
                if j == 3:
                    color = _PRIO_COLORS.get(v, COLORES["text"])
                    item.setForeground(QColor(color))
                self._improve_table.setItem(i, j, item)

        self._lbl_ciclo.setText(f"💡  {resumen.proxima_accion}")
        self._log_ok(f"Sugerencias: {len(sugerencias)} targets recomendados para campo")
        self._status(f"Active learning: {len(sugerencias)} sugerencias  ·  ganancia {resumen.ganancia_esperada}")
        self._load_improve_state()

    def _on_improve_error(self, msg: str) -> None:
        self._btn_improve.setEnabled(True)
        self._log_err(msg)
        self._status("Error en active learning")
        QMessageBox.critical(self, "Error", msg)
