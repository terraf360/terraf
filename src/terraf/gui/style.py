"""
TerraF GUI — Tema eficiente con QPalette + QSS mínimo.

QPalette opera en C++ puro (sin parseo CSS).
El QSS residual solo cubre lo que QPalette no puede: bordes, radios, placeholder.
Sin emojis en constantes (se declaran en el código que los usa si se desean).
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

# Paleta de colores — un solo lugar para cambiarlos todos
C = {
    "bg":        "#1e1e2e",
    "bg_alt":    "#181825",
    "bg_input":  "#313244",
    "border":    "#45475a",
    "accent":    "#89b4fa",
    "success":   "#a6e3a1",
    "warning":   "#f9e2af",
    "error":     "#f38ba8",
    "text":      "#cdd6f4",
    "text_dim":  "#6c7086",
}


def apply_palette(app: QApplication) -> None:
    """
    Aplica la paleta oscura a la aplicación usando QPalette.
    Es la forma más eficiente — no hay parsing de CSS en cada repintado.
    """
    app.setStyle("Fusion")   # Fusion es el estilo base más eficiente y portable

    pal = QPalette()

    bg       = QColor(C["bg"])
    bg_alt   = QColor(C["bg_alt"])
    bg_input = QColor(C["bg_input"])
    border   = QColor(C["border"])
    accent   = QColor(C["accent"])
    text     = QColor(C["text"])
    text_dim = QColor(C["text_dim"])
    error    = QColor(C["error"])

    # Fondo general
    pal.setColor(QPalette.Window,          bg)
    pal.setColor(QPalette.Base,            bg_input)
    pal.setColor(QPalette.AlternateBase,   bg_alt)

    # Texto
    pal.setColor(QPalette.WindowText,      text)
    pal.setColor(QPalette.Text,            text)
    pal.setColor(QPalette.BrightText,      Qt.white)
    pal.setColor(QPalette.PlaceholderText, text_dim)

    # Botones
    pal.setColor(QPalette.Button,          bg_input)
    pal.setColor(QPalette.ButtonText,      text)

    # Selección
    pal.setColor(QPalette.Highlight,       accent)
    pal.setColor(QPalette.HighlightedText, QColor(C["bg"]))

    # Elementos deshabilitados
    pal.setColor(QPalette.Disabled, QPalette.WindowText, text_dim)
    pal.setColor(QPalette.Disabled, QPalette.Text,       text_dim)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, text_dim)
    pal.setColor(QPalette.Disabled, QPalette.Button,     bg_alt)

    # Tooltips
    pal.setColor(QPalette.ToolTipBase, bg_alt)
    pal.setColor(QPalette.ToolTipText, text)

    # Links
    pal.setColor(QPalette.Link, accent)

    app.setPalette(pal)


# QSS mínimo — solo lo que QPalette no puede expresar
QSS_MIN = f"""
QWidget {{
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}}

/* Sidebar */
#sidebar {{
    background: {C['bg_alt']};
    border-right: 1px solid {C['border']};
}}

/* Botones del sidebar */
QPushButton[sidebar="1"] {{
    background: transparent;
    color: {C['text_dim']};
    border: none;
    border-radius: 5px;
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
    margin: 1px 6px;
}}
QPushButton[sidebar="1"]:hover {{
    background: {C['bg_input']};
    color: {C['text']};
}}
QPushButton[sidebar="1"][active="1"] {{
    background: {C['accent']};
    color: {C['bg']};
    font-weight: bold;
}}

/* Botón primario */
QPushButton {{
    background: {C['accent']};
    color: {C['bg']};
    border: none;
    border-radius: 5px;
    padding: 8px 20px;
    font-weight: bold;
}}
QPushButton:hover  {{ background: #7da8e8; }}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{
    background: {C['bg_input']};
    color: {C['text_dim']};
}}

/* Botón secundario */
QPushButton[secondary="1"] {{
    background: {C['bg_input']};
    color: {C['text']};
    border: 1px solid {C['border']};
}}
QPushButton[secondary="1"]:hover {{
    border-color: {C['accent']};
    color: {C['accent']};
}}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {C['bg_input']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    padding: 5px 8px;
    color: {C['text']};
    selection-background-color: {C['accent']};
}}
QLineEdit:focus, QTextEdit:focus {{
    border-color: {C['accent']};
}}

/* ComboBox */
QComboBox {{
    background: {C['bg_input']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    padding: 5px 8px;
    color: {C['text']};
    min-width: 120px;
}}
QComboBox:hover {{ border-color: {C['accent']}; }}
QComboBox QAbstractItemView {{
    background: {C['bg_alt']};
    border: 1px solid {C['border']};
    selection-background-color: {C['accent']};
    selection-color: {C['bg']};
    color: {C['text']};
}}

/* Tabla */
QTableWidget {{
    background: {C['bg_alt']};
    gridline-color: {C['border']};
    border: 1px solid {C['border']};
    border-radius: 4px;
}}
QTableWidget::item {{ padding: 5px 8px; }}
QTableWidget::item:hover {{ background: {C['bg_input']}; }}
QHeaderView::section {{
    background: {C['bg']};
    color: {C['text_dim']};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {C['border']};
    font-size: 11px;
    font-weight: bold;
}}

/* Progreso */
QProgressBar {{
    background: {C['bg_input']};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}

/* Log */
#log_console {{
    background: #11111b;
    color: #a6adc8;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    border: none;
    border-top: 1px solid {C['border']};
}}

/* Barra de estado */
QStatusBar {{
    background: {C['bg_alt']};
    color: {C['text_dim']};
    font-size: 11px;
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 0 4px 4px 4px;
    background: {C['bg_alt']};
}}
QTabBar::tab {{
    background: {C['bg']};
    color: {C['text_dim']};
    padding: 7px 18px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {C['bg_alt']}; color: {C['accent']}; font-weight: bold; }}
QTabBar::tab:hover {{ color: {C['text']}; }}

/* GroupBox */
QGroupBox {{
    border: 1px solid {C['border']};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    color: {C['accent']};
    font-size: 11px;
    font-weight: bold;
}}

/* Menú */
QMenuBar {{
    background: {C['bg_alt']};
    color: {C['text']};
    border-bottom: 1px solid {C['border']};
}}
QMenuBar::item:selected {{ background: {C['bg_input']}; border-radius: 3px; }}
QMenu {{
    background: {C['bg_alt']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    padding: 3px;
    color: {C['text']};
}}
QMenu::item {{ padding: 5px 20px 5px 10px; border-radius: 3px; }}
QMenu::item:selected {{ background: {C['accent']}; color: {C['bg']}; }}
QMenu::separator {{ height: 1px; background: {C['border']}; margin: 3px 6px; }}

/* Scrollbar delgada */
QScrollBar:vertical {{
    background: {C['bg_alt']};
    width: 7px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {C['border']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['text_dim']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['bg_alt']};
    height: 7px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border']};
    border-radius: 3px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Splitter */
QSplitter::handle:vertical {{ background: {C['border']}; height: 2px; }}

/* ── Toolbar ───────────────────────────────────────────────────────────────── */
QToolBar {{
    background: {C['bg_alt']};
    border: none;
    border-bottom: 1px solid {C['border']};
    spacing: 2px;
    padding: 2px 8px;
}}
QToolBar::separator {{
    background: {C['border']};
    width: 1px;
    margin: 4px 6px;
}}
QToolBar QToolButton {{
    background: transparent;
    color: {C['text_dim']};
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    font-size: 12px;
}}
QToolBar QToolButton:hover {{
    background: {C['bg_input']};
    color: {C['text']};
}}
QToolBar QToolButton:checked {{
    background: {C['accent']};
    color: {C['bg']};
    font-weight: bold;
}}
QToolBar QToolButton:pressed {{
    background: {C['border']};
}}

/* ── DockWidget ────────────────────────────────────────────────────────────── */
QDockWidget {{
    color: {C['text_dim']};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
}}
QDockWidget::title {{
    background: {C['bg_alt']};
    border-bottom: 1px solid {C['border']};
    padding: 5px 10px;
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
    border-radius: 3px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {C['bg_input']};
}}

/* ── TreeWidget (panel de capas) ───────────────────────────────────────────── */
QTreeWidget {{
    background: {C['bg_alt']};
    border: none;
    color: {C['text']};
    font-size: 12px;
    outline: 0;
}}
QTreeWidget::item {{
    padding: 3px 4px;
    border-radius: 3px;
}}
QTreeWidget::item:hover {{
    background: {C['bg_input']};
}}
QTreeWidget::item:selected {{
    background: {C['accent']};
    color: {C['bg']};
}}
QTreeWidget::branch {{
    background: {C['bg_alt']};
}}
"""

# Alias de compatibilidad — los paneles existentes importan COLORES
# Se mapea el dict C a las claves que usaban antes
COLORES = {
    "bg":           C["bg"],
    "bg_sidebar":   C["bg_alt"],
    "bg_panel":     C["bg"],
    "bg_card":      C["bg_alt"],
    "bg_input":     C["bg_input"],
    "bg_hover":     C["bg_input"],
    "border":       C["border"],
    "accent":       C["accent"],
    "accent_dark":  C["accent"],
    "success":      C["success"],
    "warning":      C["warning"],
    "error":        C["error"],
    "text":         C["text"],
    "text_muted":   C["text_dim"],
    "text_sidebar": C["text"],
    "gold":         C["warning"],
    "copper":       C["warning"],
}


def badge(texto: str, tipo: str = "normal") -> str:
    """HTML badge de color para QLabel con RichText."""
    _MAP = {
        "normal":  (C["bg_input"], C["text"]),
        "success": ("#1e3a2a",     C["success"]),
        "warning": ("#3a2e1e",     C["warning"]),
        "error":   ("#3a1e2a",     C["error"]),
        "accent":  ("#1e2a3a",     C["accent"]),
    }
    bg, fg = _MAP.get(tipo, _MAP["normal"])
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:bold;">{texto}</span>'
    )
