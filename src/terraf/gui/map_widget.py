"""
TerraF GUI — MapWidget: visor de mapas Folium integrado.

Si PyQtWebEngine está instalado  →  renderiza el HTML inline en el panel.
Si no está                       →  muestra el nombre del archivo +
                                    botón "Abrir en navegador".

Instalación del visor inline:
    pip install PyQtWebEngine
    (o: pip install 'terraf[gui-full]' cuando exista ese extra)

Uso básico:
    mw = MapWidget("MAPA DE TARGETS")
    mw.generate_clicked.connect(self._generar_mapa)
    parent_layout.addWidget(mw)
    # Cuando el archivo HTML esté listo:
    mw.load_path(path_al_html)
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

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

from terraf.gui.style import C

# ── Detección de QWebEngineView (dependencia opcional) ────────────────────────
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    from PyQt5.QtCore import QUrl
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False


# ── Plantillas HTML mínimas para el visor inline ──────────────────────────────

def _html_placeholder() -> str:
    return (
        f'<!DOCTYPE html><html><body style="margin:0;background:{C["bg_alt"]};'
        f'color:{C["text_dim"]};font-family:sans-serif;font-size:13px;'
        f'display:flex;align-items:center;justify-content:center;height:100vh;">'
        f'<div style="text-align:center;">Haz clic en <b>Generar mapa</b>'
        f'<br>para visualizar los datos espacialmente.</div></body></html>'
    )


def _html_loading() -> str:
    return (
        f'<!DOCTYPE html><html><body style="margin:0;background:{C["bg_alt"]};'
        f'color:{C["text_dim"]};font-family:sans-serif;font-size:13px;'
        f'display:flex;align-items:center;justify-content:center;height:100vh;">'
        f'<div>Generando mapa…</div></body></html>'
    )


# ── Widget principal ──────────────────────────────────────────────────────────

class MapWidget(QWidget):
    """
    Widget reutilizable para mostrar un mapa Folium HTML dentro de un panel.

    Señales:
        generate_clicked — el usuario quiere generar/regenerar el mapa.
                           El panel debe responder generando el HTML y llamando
                           a load_path() con la ruta resultante.
    """

    generate_clicked = pyqtSignal()

    def __init__(self, titulo: str = "MAPA", parent=None):
        super().__init__(parent)
        self._path: Path | None = None
        self._titulo = titulo
        self._build_ui()

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)

        # Cabecera: título + botones
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        lbl = QLabel(self._titulo)
        lbl.setStyleSheet(
            f"color:{C['text_dim']};font-size:10px;font-weight:bold;"
            f"letter-spacing:1px;border:none;background:transparent;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()

        self._btn_gen = QPushButton("Generar mapa")
        self._btn_gen.setProperty("secondary", "1")
        self._btn_gen.setFixedWidth(130)
        self._btn_gen.clicked.connect(self.generate_clicked)
        hdr.addWidget(self._btn_gen)

        self._btn_browser = QPushButton("Abrir en navegador")
        self._btn_browser.setProperty("secondary", "1")
        self._btn_browser.setFixedWidth(158)
        self._btn_browser.setEnabled(False)
        self._btn_browser.clicked.connect(self._abrir_browser)
        hdr.addWidget(self._btn_browser)

        lay.addLayout(hdr)

        # Área del mapa
        if _HAS_WEBENGINE:
            self._view = QWebEngineView()
            self._view.setMinimumHeight(300)
            self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._view.setHtml(_html_placeholder())
            lay.addWidget(self._view)
        else:
            # Fallback sin QtWebEngine
            frame = QFrame()
            frame.setStyleSheet(
                f"QFrame{{background:{C['bg_alt']};border:1px solid {C['border']};"
                f"border-radius:4px;}}"
            )
            frame.setFixedHeight(72)
            fb = QHBoxLayout(frame)
            fb.setContentsMargins(16, 8, 16, 8)
            fb.setSpacing(16)
            self._lbl_status = QLabel(
                "Haz clic en «Generar mapa» para crear el HTML.   "
                "Para verlo aquí: pip install PyQtWebEngine"
            )
            self._lbl_status.setStyleSheet(
                f"color:{C['text_dim']};font-size:11px;background:transparent;border:none;"
            )
            fb.addWidget(self._lbl_status, 1)
            lay.addWidget(frame)

    # ── API pública ───────────────────────────────────────────────────────────

    def load_path(self, path: Path) -> None:
        """Carga el HTML generado en el visor (o actualiza el estado del fallback)."""
        self._path = path
        self._btn_browser.setEnabled(True)
        self._btn_gen.setEnabled(True)
        self._btn_gen.setText("Regenerar")

        if _HAS_WEBENGINE:
            self._view.load(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self._lbl_status.setText(
                f"Mapa listo: {path.name}   "
                "→ haz clic en «Abrir en navegador» para verlo."
            )

    def set_busy(self, busy: bool) -> None:
        """Muestra/oculta el estado de carga mientras se genera el mapa."""
        self._btn_gen.setEnabled(not busy)
        if busy:
            self._btn_gen.setText("Generando…")
            if _HAS_WEBENGINE:
                self._view.setHtml(_html_loading())
            else:
                self._lbl_status.setText("Generando mapa…")
        else:
            self._btn_gen.setText("Regenerar" if self._path else "Generar mapa")

    def has_map(self) -> bool:
        return self._path is not None

    # ── Privado ───────────────────────────────────────────────────────────────

    def _abrir_browser(self) -> None:
        if self._path:
            webbrowser.open(self._path.resolve().as_uri())
