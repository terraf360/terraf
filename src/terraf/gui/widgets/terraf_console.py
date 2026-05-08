"""
TerraF GUI — Consola TerraF (ventana flotante).

Permite ejecutar subcomandos de TerraF directamente desde la GUI,
con salida en tiempo real via QProcess. Equivalente a abrir una terminal
y escribir:  python -m terraf SUBCOMANDO [args...]

Uso:
    console = TerrafConsole(parent=main_window)
    console.set_db_path(db_path)
    console.show()
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QProcess, QTimer, Qt
from PyQt5.QtGui import QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.style import C

# Subcomandos disponibles (en orden de uso típico)
_SUBCOMANDOS = [
    "status",
    "load",
    "indices",
    "analyze",
    "validate",
    "train",
    "predict",
    "improve",
    "export",
    "report",
    "geology",
    "config",
]


class TerrafConsole(QDialog):
    """
    Ventana flotante con consola para ejecutar comandos de TerraF.

    Permanece en memoria entre usos (no se destruye al cerrar, solo se oculta).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, False)   # no destruir al cerrar
        self.setWindowTitle("Consola TerraF")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.resize(900, 560)

        self._db_path: Optional[Path] = None
        self._process: Optional[QProcess] = None
        self._history: list[str] = []
        self._history_idx: int = -1

        self._build_ui()

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"QDialog{{background:{C['bg']};color:{C['text']};}}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # ── Título + ayuda ─────────────────────────────────────────────────────
        lbl_info = QLabel(
            "Ejecuta subcomandos de TerraF. "
            "El proceso corre en el directorio del proyecto activo."
        )
        lbl_info.setStyleSheet(f"color:{C['text_dim']};font-size:11px;")
        root.addWidget(lbl_info)

        # ── Barra de comando ───────────────────────────────────────────────────
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)

        lbl_cmd = QLabel("python -m terraf")
        lbl_cmd.setStyleSheet(
            f"color:{C['accent']};font-family:monospace;font-size:12px;"
            f"padding:4px 8px;background:{C['bg_input']};"
            f"border:1px solid {C['border']};border-radius:4px;"
        )
        cmd_row.addWidget(lbl_cmd)

        self._combo_sub = QComboBox()
        self._combo_sub.addItems(_SUBCOMANDOS)
        self._combo_sub.setFixedWidth(130)
        self._combo_sub.currentIndexChanged.connect(self._update_hint)
        cmd_row.addWidget(self._combo_sub)

        self._input_args = QLineEdit()
        self._input_args.setPlaceholderText("argumentos extras (ej: --umbral-ior 1.3)")
        self._input_args.setStyleSheet(
            f"font-family:monospace;font-size:12px;"
        )
        self._input_args.returnPressed.connect(self._run_command)
        self._input_args.installEventFilter(self)   # for up/down arrow history
        cmd_row.addWidget(self._input_args, 1)

        self._btn_run = QPushButton("▶  Ejecutar")
        self._btn_run.setFixedWidth(110)
        self._btn_run.clicked.connect(self._run_command)
        cmd_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton("■  Detener")
        self._btn_stop.setProperty("secondary", "1")
        self._btn_stop.setFixedWidth(100)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_command)
        cmd_row.addWidget(self._btn_stop)

        root.addLayout(cmd_row)

        # ── Hint de subcomando ─────────────────────────────────────────────────
        self._lbl_hint = QLabel("")
        self._lbl_hint.setStyleSheet(f"color:{C['text_dim']};font-size:11px;")
        root.addWidget(self._lbl_hint)
        self._update_hint()

        # ── Área de salida ─────────────────────────────────────────────────────
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("log_console")
        self._output.setFont(QFont("Consolas", 10))
        self._output.setStyleSheet(
            f"background:#11111b;color:#a6adc8;"
            f"border:1px solid {C['border']};border-radius:4px;"
        )
        self._output.setMaximumBlockCount(2000)
        root.addWidget(self._output)

        # ── Barra de estado + botones de utilidad ──────────────────────────────
        bot_row = QHBoxLayout()

        self._lbl_status = QLabel("Listo")
        self._lbl_status.setStyleSheet(f"color:{C['text_dim']};font-size:11px;")
        bot_row.addWidget(self._lbl_status)
        bot_row.addStretch()

        btn_clear = QPushButton("Limpiar")
        btn_clear.setProperty("secondary", "1")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._output.clear)
        bot_row.addWidget(btn_clear)

        btn_shell = QPushButton("Abrir PowerShell")
        btn_shell.setProperty("secondary", "1")
        btn_shell.setFixedWidth(140)
        btn_shell.clicked.connect(self._open_shell)
        btn_shell.setToolTip("Abre una ventana de PowerShell en el directorio del proyecto")
        bot_row.addWidget(btn_shell)

        root.addLayout(bot_row)

    # ── API pública ───────────────────────────────────────────────────────────

    def set_db_path(self, path: Path) -> None:
        self._db_path = path
        self._print_system(
            f"Proyecto: {path.parent.name}  ({path})"
        )

    # ── Ejecución de comandos ──────────────────────────────────────────────────

    def _run_command(self) -> None:
        if self._process and self._process.state() != QProcess.NotRunning:
            return

        subcmd = self._combo_sub.currentText()
        args_txt = self._input_args.text().strip()
        extra_args = args_txt.split() if args_txt else []

        # Historial
        cmd_str = subcmd + (" " + args_txt if args_txt else "")
        if not self._history or self._history[-1] != cmd_str:
            self._history.append(cmd_str)
        self._history_idx = -1

        self._print_system(f"$ python -m terraf {subcmd} {args_txt}")

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)

        if self._db_path:
            self._process.setWorkingDirectory(str(self._db_path.parent))

        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_proc_error)

        program = sys.executable
        argv = ["-m", "terraf", subcmd] + extra_args
        self._process.start(program, argv)

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lbl_status.setText("Ejecutando…")

    def _stop_command(self) -> None:
        if self._process:
            self._process.terminate()
            QTimer.singleShot(3000, self._force_kill)

    def _force_kill(self) -> None:
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()

    def _on_output(self) -> None:
        raw = bytes(self._process.readAllStandardOutput())
        text = raw.decode("utf-8", errors="replace")
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _on_finished(self, exit_code: int, _status) -> None:
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        ok = exit_code == 0
        msg = "OK" if ok else f"Error (código {exit_code})"
        self._print_system(f"[Proceso terminado: {msg}]")
        self._lbl_status.setText(msg)

    def _on_proc_error(self, error) -> None:
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._print_system(f"[Error de proceso: {error}]")
        self._lbl_status.setText("Error de proceso")

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _print_system(self, msg: str) -> None:
        """Inserta una línea de sistema con color distinto."""
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor(C["text_dim"]))
        cursor.insertText(msg + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _update_hint(self) -> None:
        _HINTS = {
            "status":   "Muestra el estado del proyecto activo",
            "load":     "--ruta /ruta/a/escena/  Carga imagen Landsat",
            "indices":  "--indices ior clay ndvi  Calcula índices espectrales",
            "analyze":  "--umbral-ior 1.0 --umbral-clay 1.0  Detecta targets",
            "validate": "T001 positivo --metodo campo  Registra validación",
            "train":    "--tipo porfido_cu --sinteticos 100  Entrena modelo ML",
            "predict":  "--top 10 --mapa  Predice probabilidades",
            "improve":  "--top 5  Sugerencias de active learning",
            "export":   "--formato csv  Exporta resultados",
            "report":   "Genera reporte PDF/HTML",
            "geology":  "--archivo datos.shp  Vincula geología",
            "config":   "Muestra o edita la configuración",
        }
        sub = self._combo_sub.currentText()
        self._lbl_hint.setText(_HINTS.get(sub, ""))

    def _open_shell(self) -> None:
        """Abre PowerShell en el directorio del proyecto."""
        import subprocess
        cwd = str(self._db_path.parent) if self._db_path else "."
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command",
                 f"Set-Location '{cwd}'; Write-Host 'TerraF — Directorio: {cwd}' -ForegroundColor Cyan"],
                creationflags=0x00000010,  # CREATE_NEW_CONSOLE
            )
        except FileNotFoundError:
            subprocess.Popen(
                ["cmd.exe", "/K", f"cd /d {cwd}"],
                creationflags=0x00000010,
            )

    # ── Historial con flechas ──────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QKeyEvent
        if obj is self._input_args and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                if self._history:
                    self._history_idx = max(0, len(self._history) - 1
                                            if self._history_idx < 0
                                            else self._history_idx - 1)
                    # split off subcommand
                    entry = self._history[self._history_idx]
                    parts = entry.split(" ", 1)
                    sub = parts[0]
                    args = parts[1] if len(parts) > 1 else ""
                    idx = self._combo_sub.findText(sub)
                    if idx >= 0:
                        self._combo_sub.setCurrentIndex(idx)
                    self._input_args.setText(args)
                return True
            elif key == Qt.Key_Down:
                if self._history and self._history_idx >= 0:
                    self._history_idx += 1
                    if self._history_idx >= len(self._history):
                        self._history_idx = -1
                        self._input_args.clear()
                    else:
                        entry = self._history[self._history_idx]
                        parts = entry.split(" ", 1)
                        self._input_args.setText(parts[1] if len(parts) > 1 else "")
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        """Ocultar en vez de destruir."""
        self.hide()
        event.ignore()
