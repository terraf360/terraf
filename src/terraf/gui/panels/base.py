"""
Panel base — clase abstracta para todos los paneles de TerraF GUI.
Provee helpers de layout, estilos y comunicación con la consola de log.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.style import COLORES


class BasePanel(QWidget):
    """Panel base. Todos los paneles heredan de aquí."""

    # Señal para enviar mensajes a la consola de log de la ventana principal
    log_signal = pyqtSignal(str)
    # Señal para actualizar la barra de estado
    status_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path = None
        self._workers: set = set()   # keeps QThread workers alive until finished
        self._setup_ui()

    def _run(self, worker) -> None:
        """Start a worker and keep it alive until the OS thread finishes."""
        self._workers.add(worker)
        worker.finished.connect(lambda: self._workers.discard(worker))
        worker.start()

    def set_db_path(self, path) -> None:
        """Llamado por la ventana principal cuando se conoce la DB."""
        self._db_path = path
        self.on_db_ready()

    def on_db_ready(self) -> None:
        """Sobrescribir para reaccionar cuando la DB está disponible."""

    def refresh(self) -> None:
        """Sobrescribir para actualizar el panel con datos frescos."""

    def _setup_ui(self) -> None:
        """Sobrescribir para construir el UI del panel."""

    # ── Helpers de layout ─────────────────────────────────────────────────────

    def _make_title(self, titulo: str, descripcion: str) -> QVBoxLayout:
        """Crea el encabezado estándar de panel."""
        lay = QVBoxLayout()
        lay.setSpacing(2)

        lbl_t = QLabel(titulo)
        lbl_t.setObjectName("panel_title")
        lay.addWidget(lbl_t)

        lbl_d = QLabel(descripcion)
        lbl_d.setObjectName("panel_desc")
        lbl_d.setWordWrap(True)
        lay.addWidget(lbl_d)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{COLORES['border']};max-height:1px;margin:10px 0;")
        lay.addWidget(sep)

        return lay

    def _make_card(self, layout: QVBoxLayout | QHBoxLayout | None = None) -> QFrame:
        """Devuelve un QFrame con estilo 'card'."""
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            f"QFrame#card{{"
            f"background:{COLORES['bg_card']};"
            f"border:1px solid {COLORES['border']};"
            f"border-radius:10px;"
            f"padding:12px;"
            f"}}"
        )
        if layout is not None:
            card.setLayout(layout)
        return card

    def _make_btn(
        self,
        texto: str,
        estilo: str = "primary",
        ancho: int | None = None,
    ) -> QPushButton:
        """Crea un botón estilizado."""
        btn = QPushButton(texto)
        btn.setProperty("class", estilo)
        btn.setStyleSheet(btn.styleSheet())  # trigger re-polish
        if ancho:
            btn.setFixedWidth(ancho)
        return btn

    def _kv_row(self, clave: str, valor: str) -> QHBoxLayout:
        """Fila clave:valor para grids de información."""
        row = QHBoxLayout()
        lbl_k = QLabel(clave)
        lbl_k.setProperty("class", "label_key")
        lbl_k.setFixedWidth(150)
        lbl_v = QLabel(valor)
        lbl_v.setProperty("class", "label_val")
        lbl_v.setWordWrap(True)
        row.addWidget(lbl_k)
        row.addWidget(lbl_v)
        row.addStretch()
        return row

    # ── Helpers de log ─────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        self.log_signal.emit(msg)

    def _status(self, msg: str) -> None:
        self.status_signal.emit(msg)

    def _log_ok(self, msg: str) -> None:
        self.log_signal.emit(f"✓  {msg}")

    def _log_err(self, msg: str) -> None:
        self.log_signal.emit(f"✗  {msg}")

    def _log_step(self, msg: str) -> None:
        self.log_signal.emit(f"   {msg}")
