"""
Panel Cargar Imagen — Carga una imagen Landsat 9 al proyecto.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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


class LoadPanel(BasePanel):
    """Panel para cargar imagen satelital."""

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        for w in self._make_title(
            "📂  Cargar Imagen",
            "Carga una imagen Landsat 9 (archivo .TIF o directorio de escena). "
            "TerraF leerá los metadatos y la registrará en la base de datos.",
        ).children():
            if isinstance(w, QWidget):
                root.addWidget(w)

        root.addSpacing(16)

        # ── Selector de ruta ───────────────────────────────────────────────────
        grp_lay = QVBoxLayout()
        grp_lay.setSpacing(8)

        lbl_r = QLabel("Ruta de la imagen o directorio de escena:")
        lbl_r.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;font-weight:bold;")
        grp_lay.addWidget(lbl_r)

        row_path = QHBoxLayout()
        self._input_path = QLineEdit()
        self._input_path.setPlaceholderText("Ej: C:/datos/LC09_L2SP_001001_20240101/")
        row_path.addWidget(self._input_path)

        btn_browse_dir = QPushButton("Directorio…")
        btn_browse_dir.setProperty("class", "secondary")
        btn_browse_dir.clicked.connect(self._browse_dir)
        row_path.addWidget(btn_browse_dir)

        btn_browse_file = QPushButton("Archivo…")
        btn_browse_file.setProperty("class", "secondary")
        btn_browse_file.clicked.connect(self._browse_file)
        row_path.addWidget(btn_browse_file)

        grp_lay.addLayout(row_path)

        # Nota explicativa
        lbl_hint = QLabel(
            "💡  Puedes indicar el directorio completo de la escena Landsat "
            "(contiene los archivos _B2.TIF, _B3.TIF… y el MTL.txt) "
            "o seleccionar un archivo .TIF individual."
        )
        lbl_hint.setStyleSheet(f"color:{COLORES['text_muted']};font-size:11px;")
        lbl_hint.setWordWrap(True)
        grp_lay.addWidget(lbl_hint)

        card = self._make_card(grp_lay)
        root.addWidget(card)

        root.addSpacing(12)

        # ── Botón cargar ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_load = QPushButton("⬆  Cargar imagen")
        self._btn_load.setFixedWidth(200)
        self._btn_load.clicked.connect(self._run_load)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_load)
        root.addLayout(btn_row)

        root.addSpacing(16)

        # ── Progreso ───────────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminado
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        root.addWidget(self._progress)

        root.addSpacing(16)

        # ── Resultado ──────────────────────────────────────────────────────────
        self._result_card = QWidget()
        self._result_card.setVisible(False)
        self._result_lay = QVBoxLayout(self._result_card)
        self._result_lay.setSpacing(6)

        lbl_res_title = QLabel("METADATOS DETECTADOS")
        lbl_res_title.setStyleSheet(
            f"color:{COLORES['text_muted']};font-size:10px;font-weight:bold;letter-spacing:1px;"
        )
        self._result_lay.addWidget(lbl_res_title)
        self._result_content = QVBoxLayout()
        self._result_lay.addLayout(self._result_content)

        root.addWidget(self._result_card)
        root.addStretch()

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Seleccionar directorio de escena")
        if d:
            self._input_path.setText(d)

    def _browse_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar imagen",
            filter="Imágenes GeoTIFF (*.TIF *.tif *.tiff);;Todos (*.*)"
        )
        if f:
            self._input_path.setText(f)

    def _run_load(self) -> None:
        if self._db_path is None:
            QMessageBox.warning(self, "Sin proyecto", "No hay proyecto activo. Crea o abre uno primero.")
            return

        ruta = self._input_path.text().strip()
        if not ruta:
            QMessageBox.warning(self, "Ruta vacía", "Indica la ruta de la imagen o directorio.")
            return

        self._btn_load.setEnabled(False)
        self._progress.setVisible(True)
        self._result_card.setVisible(False)
        self._log(f"Cargando imagen desde: {ruta}")
        self._status("Cargando imagen…")

        from terraf.pipeline.loader import load_image_to_db
        from terraf.gui.workers import PipelineWorker

        self._worker = PipelineWorker(
            load_image_to_db,
            Path(ruta),
            self._db_path,
        )
        self._worker.step_signal.connect(self._log_step)
        self._worker.done_signal.connect(self._on_done)
        self._worker.error_signal.connect(self._on_error)
        self._run(self._worker)

    def _on_done(self, info) -> None:
        self._progress.setVisible(False)
        self._btn_load.setEnabled(True)

        # Limpiar resultado previo
        while self._result_content.count():
            item = self._result_content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Mostrar metadatos
        campos = [
            ("Scene ID",     info.scene_id),
            ("Sensor",       info.sensor),
            ("Fecha",        str(info.fecha_adquisicion or "—")),
            ("CRS",          str(info.crs or "—")),
            ("Dimensiones",  f"{info.ancho_px} × {info.alto_px} px"),
            ("Resolución",   f"{info.resolucion_m} m/px" if info.resolucion_m else "—"),
            ("Bandas",       str(len(info.bandas) if info.bandas else "—")),
            ("Estado",       "✓ Ya existía (omitido)" if info.ya_existia else "✓ Cargada"),
        ]
        for k, v in campos:
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_l = self._kv_row(k + ":", v)
            row_w.setLayout(row_l)
            self._result_content.addWidget(row_w)

        self._result_card.setVisible(True)
        self._log_ok(f"Imagen cargada: {info.scene_id}")
        self._status(f"Imagen: {info.scene_id}  ·  {info.sensor}")

    def _on_error(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._btn_load.setEnabled(True)
        self._log_err(msg)
        self._status("Error al cargar imagen")
        QMessageBox.critical(self, "Error al cargar", msg)
