"""
TerraF GUI — Ventana principal estilo QGIS.

Layout:
  ┌─────────────────────────────────────────────────────────┐
  │ MenuBar                                                  │
  ├─────────────────────────────────────────────────────────┤
  │ ToolBar: [Proyecto] | [Cargar][Indices][Analizar]...     │
  ├─────────────┬───────────────────────────────────────────┤
  │ CAPAS       │  MAPA CENTRAL  (QWebEngineView / Folium)  │
  │ (left dock) │  con selector de tipo de mapa             │
  │             │                                           │
  │             ├───────────────────────────────────────────┤
  │             │ LOG  (bottom dock)                        │
  ├─────────────┴───────────────────────────────────────────┤
  │ StatusBar                                               │
  └─────────────────────────────────────────────────────────┘

Los paneles de pipeline (Cargar, Índices, Analizar, Validar, ML)
se abren como QDockWidgets en la derecha al hacer clic en la barra
de herramientas. Se cargan de forma perezosa.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.map_widget import MapWidget
from terraf.gui.panels.layer_panel import LayerPanel
from terraf.gui.style import C, QSS_MIN

# ── Definición de paneles del pipeline ────────────────────────────────────────
_PANEL_DEFS: dict[str, tuple[str, str, str]] = {
    "inicio":   ("Proyecto",      "terraf.gui.panels.home",          "HomePanel"),
    "cargar":   ("Cargar Imagen", "terraf.gui.panels.load_panel",    "LoadPanel"),
    "indices":  ("Indices",       "terraf.gui.panels.indices_panel", "IndicesPanel"),
    "analizar": ("Analizar",      "terraf.gui.panels.analyze_panel", "AnalyzePanel"),
    "validar":  ("Validar",       "terraf.gui.panels.validate_panel","ValidatePanel"),
    "ml":       ("ML / IA",       "terraf.gui.panels.ml_panel",      "MLPanel"),
}

# Sentinel en mensajes de log → ruta HTML del mapa generado por un panel
_RE_MAPA = re.compile(r"Mapa (?:generado|actualizado|ML generado):\s+(.+\.html)$")


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._db_path: Optional[Path] = None
        self._panel_cache: dict[str, QDockWidget] = {}  # nombre → QDockWidget
        self._toolbar_btns: dict[str, QToolButton] = {} # nombre → botón del toolbar
        self._console = None   # TerrafConsole — instanciada al primer uso

        self.setWindowTitle("TerraF — Exploración Minera")
        self.setMinimumSize(1100, 650)
        self.resize(1400, 820)
        self.setDockOptions(
            QMainWindow.AnimatedDocks |
            QMainWindow.AllowNestedDocks |
            QMainWindow.AllowTabbedDocks
        )
        self.setStyleSheet(QSS_MIN)

        self._build_central()
        self._build_left_dock()
        self._build_bottom_dock()
        self._build_toolbar()
        self._build_menu()
        self._build_statusbar()

        QTimer.singleShot(100, self._try_auto_open)

    # ══════════════════════════════════════════════════════════════════════════
    # Construcción de la UI
    # ══════════════════════════════════════════════════════════════════════════

    def _build_central(self) -> None:
        """Widget central: mapa Folium + selector de tipo de mapa."""
        wrapper = QWidget()
        wrapper.setStyleSheet(f"background:{C['bg']};")
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Barra de tipo de mapa
        map_bar = QWidget()
        map_bar.setStyleSheet(
            f"background:{C['bg_alt']};border-bottom:1px solid {C['border']};"
        )
        map_bar.setFixedHeight(38)
        bar_lay = QHBoxLayout(map_bar)
        bar_lay.setContentsMargins(10, 4, 10, 4)
        bar_lay.setSpacing(4)

        lbl_tipo = QLabel("Mapa:")
        lbl_tipo.setStyleSheet(
            f"color:{C['text_dim']};font-size:11px;font-weight:bold;"
            f"background:transparent;border:none;"
        )
        bar_lay.addWidget(lbl_tipo)

        self._map_type_btns: dict[str, QToolButton] = {}
        for key, label in [
            ("analisis",     "Análisis"),
            ("validaciones", "Validaciones"),
            ("prediccion",   "ML / Predicción"),
            ("geologia",     "Geología"),
        ]:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setStyleSheet(
                f"QToolButton{{background:transparent;color:{C['text_dim']};"
                f"border:1px solid transparent;border-radius:4px;padding:3px 10px;font-size:11px;}}"
                f"QToolButton:checked{{background:{C['accent']};color:{C['bg']};border-color:{C['accent']};}}"
                f"QToolButton:hover{{background:{C['bg_input']};color:{C['text']};}}"
            )
            btn.clicked.connect(lambda _, k=key: self._load_map(k))
            bar_lay.addWidget(btn)
            self._map_type_btns[key] = btn

        self._map_type_btns["analisis"].setChecked(True)
        self._current_map_type = "analisis"

        bar_lay.addStretch()

        btn_reload = QPushButton("⟳  Actualizar mapa")
        btn_reload.setProperty("secondary", "1")
        btn_reload.setFixedWidth(140)
        btn_reload.clicked.connect(lambda: self._load_map(self._current_map_type))
        bar_lay.addWidget(btn_reload)

        lay.addWidget(map_bar)

        # Mapa principal
        self._central_map = MapWidget("MAPA CENTRAL")
        self._central_map.generate_clicked.connect(
            lambda: self._load_map(self._current_map_type)
        )
        lay.addWidget(self._central_map, 1)

        self.setCentralWidget(wrapper)

    def _build_left_dock(self) -> None:
        """Dock izquierdo: panel de capas del proyecto."""
        dock = QDockWidget("CAPAS", self)
        dock.setObjectName("dock_capas")
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable
        )
        dock.setMinimumWidth(210)
        dock.setMaximumWidth(330)

        self._layer_panel = LayerPanel()
        self._layer_panel.status_signal.connect(self.statusBar().showMessage)
        dock.setWidget(self._layer_panel)

        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._left_dock = dock

    def _build_bottom_dock(self) -> None:
        """Dock inferior: pestaña de log."""
        dock = QDockWidget("CONSOLA", self)
        dock.setObjectName("dock_consola")
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable
        )

        self._log = QPlainTextEdit()
        self._log.setObjectName("log_console")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(800)
        self._log.setPlaceholderText("  Log de actividad…")
        self._log.setFont(QFont("Consolas", 10))

        dock.setWidget(self._log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        dock.setMaximumHeight(210)
        self._bottom_dock = dock

    def _build_toolbar(self) -> None:
        """Barra de herramientas principal."""
        tb = QToolBar("Principal", self)
        tb.setObjectName("toolbar_main")
        tb.setMovable(False)
        tb.setIconSize(__import__("PyQt5.QtCore", fromlist=["QSize"]).QSize(16, 16))
        self.addToolBar(tb)

        def _btn(key: str, label: str, tooltip: str = "") -> QToolButton:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setToolTip(tooltip or label)
            b.clicked.connect(lambda checked: self._toggle_panel(key, checked))
            tb.addWidget(b)
            self._toolbar_btns[key] = b
            return b

        _btn("inicio",   "Proyecto",  "Ver información del proyecto")
        tb.addSeparator()
        _btn("cargar",   "Cargar",    "Cargar imagen satelital")
        _btn("indices",  "Indices",   "Calcular índices espectrales")
        _btn("analizar", "Analizar",  "Detectar targets de exploración")
        _btn("validar",  "Validar",   "Registrar validaciones de campo")
        _btn("ml",       "ML / IA",   "Entrenar / Predecir / Active learning")
        tb.addSeparator()

        # Botón Capas (toggle del dock izquierdo)
        btn_capas = QToolButton()
        btn_capas.setText("Capas")
        btn_capas.setCheckable(True)
        btn_capas.setChecked(True)
        btn_capas.setToolTip("Mostrar/ocultar panel de capas")
        btn_capas.clicked.connect(
            lambda checked: (
                self._left_dock.show() if checked else self._left_dock.hide()
            )
        )
        self._left_dock.visibilityChanged.connect(btn_capas.setChecked)
        tb.addWidget(btn_capas)

        # Botón Log
        btn_log = QToolButton()
        btn_log.setText("Log")
        btn_log.setCheckable(True)
        btn_log.setChecked(True)
        btn_log.setToolTip("Mostrar/ocultar consola de log")
        btn_log.clicked.connect(
            lambda checked: (
                self._bottom_dock.show() if checked else self._bottom_dock.hide()
            )
        )
        self._bottom_dock.visibilityChanged.connect(btn_log.setChecked)
        tb.addWidget(btn_log)

        tb.addSeparator()

        # Botón Terminal TerraF
        btn_term = QToolButton()
        btn_term.setText("Terminal")
        btn_term.setToolTip("Abrir consola TerraF (ejecutar comandos)")
        btn_term.setCheckable(False)
        btn_term.clicked.connect(self._open_console)
        tb.addWidget(btn_term)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # ── Archivo ───────────────────────────────────────────────────────────
        m_file = mb.addMenu("Archivo")
        for txt, shortcut, fn in [
            ("Abrir proyecto (terraf.db)…",       "Ctrl+O",       self._open_db),
            ("Abrir directorio de proyecto…",      "Ctrl+Shift+O", self._open_project_dir),
        ]:
            a = QAction(txt, self)
            a.setShortcut(shortcut)
            a.triggered.connect(fn)
            m_file.addAction(a)
        m_file.addSeparator()
        a_quit = QAction("Salir", self)
        a_quit.setShortcut("Ctrl+Q")
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_quit)

        # ── Pipeline ──────────────────────────────────────────────────────────
        m_pipe = mb.addMenu("Pipeline")
        for name, (label, _, _) in _PANEL_DEFS.items():
            a = QAction(label, self)
            a.triggered.connect(lambda _, n=name: self._open_panel(n))
            m_pipe.addAction(a)

        # ── Mapa ──────────────────────────────────────────────────────────────
        m_map = mb.addMenu("Mapa")
        for key, label in [
            ("analisis",     "Mapa de Análisis"),
            ("validaciones", "Mapa de Validaciones"),
            ("prediccion",   "Mapa ML / Predicción"),
            ("geologia",     "Mapa Geológico"),
        ]:
            a = QAction(label, self)
            a.triggered.connect(lambda _, k=key: self._load_map(k))
            m_map.addAction(a)

        # ── Ver ───────────────────────────────────────────────────────────────
        m_view = mb.addMenu("Ver")
        a_capas = QAction("Panel de Capas  (Ctrl+1)", self)
        a_capas.setShortcut("Ctrl+1")
        a_capas.triggered.connect(lambda: (
            self._left_dock.show(), self._left_dock.raise_()
        ))
        m_view.addAction(a_capas)

        a_log = QAction("Consola / Log  (Ctrl+L)", self)
        a_log.setShortcut("Ctrl+L")
        a_log.triggered.connect(lambda: (
            self._bottom_dock.show(), self._bottom_dock.raise_()
        ))
        m_view.addAction(a_log)

        # ── Consola ───────────────────────────────────────────────────────────
        m_con = mb.addMenu("Consola")
        a_term = QAction("Consola TerraF…  (Ctrl+T)", self)
        a_term.setShortcut("Ctrl+T")
        a_term.triggered.connect(self._open_console)
        m_con.addAction(a_term)

        # ── Ayuda ─────────────────────────────────────────────────────────────
        m_help = mb.addMenu("Ayuda")
        a_about = QAction("Acerca de TerraF…", self)
        a_about.triggered.connect(self._about)
        m_help.addAction(a_about)

    def _build_statusbar(self) -> None:
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("TerraF listo")

    # ══════════════════════════════════════════════════════════════════════════
    # Navegación de paneles (lazy loading en docks derechos)
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_panel(self, name: str, checked: bool) -> None:
        if checked:
            self._open_panel(name)
        else:
            dock = self._panel_cache.get(name)
            if dock:
                dock.hide()

    def _open_panel(self, name: str) -> None:
        """Abre (o trae al frente) el panel de pipeline solicitado."""
        if name not in self._panel_cache:
            label, module_path, class_name = _PANEL_DEFS[name]
            import importlib
            mod   = importlib.import_module(module_path)
            klass = getattr(mod, class_name)
            panel = klass()

            # Señales
            panel.log_signal.connect(self._append_log)
            panel.status_signal.connect(self.statusBar().showMessage)
            panel.log_signal.connect(self._layer_panel.schedule_refresh)

            if self._db_path:
                panel.set_db_path(self._db_path)

            dock = QDockWidget(label, self)
            dock.setObjectName(f"dock_{name}")
            dock.setFeatures(
                QDockWidget.DockWidgetMovable |
                QDockWidget.DockWidgetClosable |
                QDockWidget.DockWidgetFloatable
            )
            dock.setMinimumWidth(420)
            dock.setWidget(panel)

            # Sincronizar botón del toolbar con visibilidad del dock
            if name in self._toolbar_btns:
                btn = self._toolbar_btns[name]
                dock.visibilityChanged.connect(btn.setChecked)

            # Tabificar con los docks derechos existentes
            existing_right = [
                d for n, d in self._panel_cache.items()
                if self.dockWidgetArea(d) == Qt.RightDockWidgetArea
            ]
            self.addDockWidget(Qt.RightDockWidgetArea, dock)
            if existing_right:
                self.tabifyDockWidget(existing_right[0], dock)

            self._panel_cache[name] = dock

        dock = self._panel_cache[name]
        dock.show()
        dock.raise_()

        # Asegurar que el botón quede marcado
        if name in self._toolbar_btns:
            self._toolbar_btns[name].setChecked(True)

        panel = dock.widget()
        panel.refresh()

    # ══════════════════════════════════════════════════════════════════════════
    # Mapa central
    # ══════════════════════════════════════════════════════════════════════════

    def _load_map(self, map_type: str) -> None:
        """Genera y carga en el mapa central el tipo de mapa solicitado."""
        if self._db_path is None:
            self._append_log("Sin proyecto — abre un proyecto primero.")
            return

        self._current_map_type = map_type
        for key, btn in self._map_type_btns.items():
            btn.setChecked(key == map_type)

        self._central_map.set_busy(True)

        from terraf.gui.workers import SimpleWorker

        fn_map = {
            "analisis":     self._gen_map_analisis,
            "validaciones": self._gen_map_validaciones,
            "prediccion":   self._gen_map_prediccion,
            "geologia":     self._gen_map_geologia,
        }.get(map_type, self._gen_map_analisis)

        w = SimpleWorker(fn_map)
        w.done_signal.connect(self._on_central_map_done)
        w.error_signal.connect(self._on_central_map_error)
        self._map_workers = getattr(self, "_map_workers", set())
        self._map_workers.add(w)
        w.finished.connect(lambda: self._map_workers.discard(w))
        w.start()

    def _gen_map_analisis(self):
        from terraf.pipeline.mapper import mapa_analisis
        return mapa_analisis(self._db_path, abrir=False)

    def _gen_map_validaciones(self):
        from terraf.pipeline.mapper import mapa_validaciones
        return mapa_validaciones(self._db_path, abrir=False)

    def _gen_map_prediccion(self):
        from terraf.pipeline.mapper import mapa_prediccion
        return mapa_prediccion(self._db_path, abrir=False)

    def _gen_map_geologia(self):
        from terraf.pipeline.mapper import mapa_geologia
        return mapa_geologia(self._db_path, abrir=False)

    def _on_central_map_done(self, path: Path) -> None:
        self._central_map.load_path(path)
        self.statusBar().showMessage(f"Mapa: {path.name}")

    def _on_central_map_error(self, msg: str) -> None:
        self._central_map.set_busy(False)
        self._append_log(f"✗  Mapa: {msg}")

    # ══════════════════════════════════════════════════════════════════════════
    # Log
    # ══════════════════════════════════════════════════════════════════════════

    def _append_log(self, msg: str) -> None:
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        if msg.startswith("✓") or msg[:4] == "OK  ":
            fmt.setForeground(QColor(C["success"]))
        elif msg.startswith("✗") or "Error" in msg[:8]:
            fmt.setForeground(QColor(C["error"]))
        elif msg.startswith("   "):
            fmt.setForeground(QColor(C["text_dim"]))
        else:
            fmt.setForeground(QColor(C["text"]))
        cursor.insertText(f"{msg}\n", fmt)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

        # Auto-detectar mapas generados por los paneles → actualizar mapa central
        m = _RE_MAPA.search(msg.strip())
        if m and self._db_path:
            filename = m.group(1)
            html_path = self._db_path.parent / "resultados" / "mapas" / filename
            if html_path.exists():
                self._central_map.load_path(html_path)
                self.statusBar().showMessage(f"Mapa actualizado: {filename}")

    # ══════════════════════════════════════════════════════════════════════════
    # Consola TerraF (ventana flotante)
    # ══════════════════════════════════════════════════════════════════════════

    def _open_console(self) -> None:
        if self._console is None:
            from terraf.gui.widgets.terraf_console import TerrafConsole
            self._console = TerrafConsole(parent=self)
        if self._db_path:
            self._console.set_db_path(self._db_path)
        self._console.show()
        self._console.raise_()
        self._console.activateWindow()

    # ══════════════════════════════════════════════════════════════════════════
    # Proyecto / DB
    # ══════════════════════════════════════════════════════════════════════════

    def _try_auto_open(self) -> None:
        try:
            from terraf.db.session import require_db
            self._set_db(require_db())
        except Exception:
            self._append_log("Sin proyecto. Archivo → Abrir proyecto")
            self.statusBar().showMessage("Sin proyecto activo")

    def _open_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir base de datos",
            filter="Base de datos (terraf.db);;Todos (*.*)"
        )
        if path:
            self._set_db(Path(path))

    def _open_project_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Abrir directorio de proyecto")
        if not d:
            return
        candidate = Path(d) / "terraf.db"
        if candidate.exists():
            self._set_db(candidate)
        else:
            QMessageBox.warning(self, "No encontrado", f"No hay terraf.db en:\n{d}")

    def _set_db(self, path: Path) -> None:
        self._db_path = path
        self._append_log(f"Proyecto: {path}")
        self.statusBar().showMessage(f"Proyecto: {path.parent.name}")

        # Propagar a panel de capas
        self._layer_panel.set_db_path(path)

        # Propagar a paneles ya abiertos
        for dock in self._panel_cache.values():
            panel = dock.widget()
            if hasattr(panel, "set_db_path"):
                panel.set_db_path(path)

        # Propagar a la consola si existe
        if self._console:
            self._console.set_db_path(path)

        # Cargar mapa inicial
        QTimer.singleShot(300, lambda: self._load_map("analisis"))

    # ══════════════════════════════════════════════════════════════════════════
    # Cierre
    # ══════════════════════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        # Terminar proceso de consola si corre
        if self._console and self._console._process:
            p = self._console._process
            if p.state() != __import__(
                "PyQt5.QtCore", fromlist=["QProcess"]
            ).QProcess.NotRunning:
                p.terminate()
                p.waitForFinished(2000)
        event.accept()

    # ══════════════════════════════════════════════════════════════════════════
    # Acerca de
    # ══════════════════════════════════════════════════════════════════════════

    def _about(self) -> None:
        QMessageBox.about(
            self, "Acerca de TerraF",
            "<b>TerraF v0.1</b><br>"
            "Herramienta de exploración minera asistida por IA.<br><br>"
            "Pipeline: Cargar → Indices → Analizar → Validar → ML<br>"
            "GUI estilo QGIS: mapa central + panel de capas + consola TerraF<br><br>"
            "Python · PyQt5 · SQLAlchemy · scikit-learn · Folium"
        )
