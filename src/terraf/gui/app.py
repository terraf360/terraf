"""
TerraF GUI — Entry point de la aplicación.

Uso:
    terraf-gui              (desde el entry point instalado)
    python -m terraf.gui.app
"""

from __future__ import annotations

import sys


def main() -> None:
    """Lanza la aplicación PyQt5 de TerraF."""
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
    except ImportError:
        print(
            "ERROR: PyQt5 no está instalado.\n"
            "  Instálalo con: pip install 'terraf[gui]'\n"
            "  o directamente: pip install PyQt5"
        )
        sys.exit(1)

    # Atributos de alta DPI y WebEngine (deben configurarse ANTES de crear QApplication)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Requerido por QWebEngineView para compartir contexto OpenGL entre widgets
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("TerraF")
    app.setOrganizationName("TerraF")
    app.setApplicationVersion("0.1.0")

    from PyQt5.QtGui import QFont
    app.setFont(QFont("Segoe UI", 10))

    # Paleta oscura vía QPalette (más eficiente que QSS global)
    from terraf.gui.style import apply_palette
    apply_palette(app)

    from terraf.gui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
