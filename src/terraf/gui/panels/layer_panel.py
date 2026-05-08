"""
TerraF GUI — Panel de Capas (izquierda).

Muestra el contenido del proyecto activo en un árbol:
  - Imágenes satelitales cargadas
  - Índices espectrales calculados
  - Targets de análisis (agrupados por prioridad)
  - Estado de validaciones
  - Modelos ML entrenados

Se auto-actualiza después de que cualquier operación de pipeline termina con éxito
(detecta el prefijo ✓ en el log).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from terraf.gui.style import C


class LayerPanel(QWidget):
    """Panel izquierdo tipo QGIS — muestra capas y contenido del proyecto."""

    status_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path: Optional[Path] = None
        self._workers: set = set()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(600)   # debounce 600 ms
        self._refresh_timer.timeout.connect(self.refresh)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Cabecera: nombre del proyecto + botón refrescar
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['bg_alt']};border-bottom:1px solid {C['border']};"
        )
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(10, 8, 8, 8)
        hdr_lay.setSpacing(6)

        self._lbl_proyecto = QLabel("Sin proyecto")
        self._lbl_proyecto.setStyleSheet(
            f"color:{C['text_dim']};font-size:10px;font-weight:bold;"
            f"letter-spacing:1px;background:transparent;border:none;"
        )
        self._lbl_proyecto.setWordWrap(True)
        hdr_lay.addWidget(self._lbl_proyecto, 1)

        btn_refresh = QPushButton("⟳")
        btn_refresh.setFixedSize(24, 24)
        btn_refresh.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['text_dim']};"
            f"border:none;font-size:14px;padding:0;}}"
            f"QPushButton:hover{{color:{C['accent']};}}"
        )
        btn_refresh.setToolTip("Actualizar capas")
        btn_refresh.clicked.connect(self.refresh)
        hdr_lay.addWidget(btn_refresh)

        lay.addWidget(hdr)

        # Árbol de capas
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(14)
        self._tree.setRootIsDecorated(True)
        self._tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._tree.setStyleSheet("QTreeWidget{border:none;}")
        lay.addWidget(self._tree)

        # Placeholder inicial
        self._show_placeholder("Sin proyecto activo.\nAbre o crea un proyecto.")

    # ── API pública ───────────────────────────────────────────────────────────

    def set_db_path(self, path: Path) -> None:
        self._db_path = path
        self._lbl_proyecto.setText(path.parent.name)
        self.refresh()

    def schedule_refresh(self, msg: str) -> None:
        """Slot conectado al log_signal de los paneles.
        Solo refresca si la operación terminó con éxito (prefijo ✓)."""
        if msg.startswith("✓") or msg.startswith("OK"):
            if not self._refresh_timer.isActive():
                self._refresh_timer.start()

    def refresh(self) -> None:
        if self._db_path is None:
            return
        from terraf.gui.workers import SimpleWorker
        w = SimpleWorker(self._load_data)
        w.done_signal.connect(self._populate)
        w.error_signal.connect(lambda e: self.status_signal.emit(f"Capas: {e}"))
        self._run(w)

    # ── Carga de datos (hilo secundario) ──────────────────────────────────────

    def _load_data(self) -> dict:
        """Lee el estado del proyecto de la DB. Devuelve solo tipos primitivos
        (str, int, list de dicts) para evitar acceso cross-thread a ORM."""
        from sqlalchemy import text
        from terraf.db.session import make_engine

        engine = make_engine(self._db_path)
        d: dict = {
            "imagenes": [], "indices": [], "analisis": [],
            "validaciones": {}, "modelos": [],
        }

        with engine.connect() as conn:
            def q(sql):
                try:
                    return conn.execute(text(sql))
                except Exception:
                    return None

            # Imágenes
            r = q("SELECT id, scene_id, sensor, fecha_adquisicion FROM imagenes ORDER BY id")
            if r:
                d["imagenes"] = [
                    {"id": row[0], "scene_id": row[1] or "—",
                     "sensor": row[2] or "—", "fecha": str(row[3] or "—")}
                    for row in r
                ]

            # Índices (por nombre, con cuenta)
            r = q(
                "SELECT nombre_indice, COUNT(*) as n FROM indices_espectrales "
                "GROUP BY nombre_indice ORDER BY nombre_indice"
            )
            if r:
                d["indices"] = [{"nombre": row[0], "n": row[1]} for row in r]

            # Análisis + targets por prioridad
            r = q("SELECT id, fecha_analisis FROM analisis ORDER BY id DESC LIMIT 5")
            if r:
                for row in r:
                    aid = row[0]
                    fecha = str(row[1] or "—")[:10]
                    ta = q(
                        f"SELECT prioridad, COUNT(*) FROM targets "
                        f"WHERE analisis_id={aid} GROUP BY prioridad"
                    )
                    prio = {p: c for p, c in (ta or [])}
                    d["analisis"].append({
                        "id": aid, "fecha": fecha,
                        "alta": prio.get("ALTA", 0),
                        "media": prio.get("MEDIA", 0),
                        "baja": prio.get("BAJA", 0),
                    })

            # Validaciones (último análisis)
            r = q(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN resultado='positivo' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN resultado='negativo' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN resultado IS NULL OR resultado='pendiente' THEN 1 ELSE 0 END) "
                "FROM targets"
            )
            if r:
                row = r.fetchone()
                if row and row[0]:
                    d["validaciones"] = {
                        "total": row[0] or 0,
                        "positivos": row[1] or 0,
                        "negativos": row[2] or 0,
                        "pendientes": row[3] or 0,
                    }

        # Modelos ML (archivos en disco)
        modelos_dir = self._db_path.parent / "modelos"
        if modelos_dir.exists():
            d["modelos"] = [
                {"nombre": p.stem}
                for p in sorted(modelos_dir.glob("*.pkl"), reverse=True)[:5]
            ]

        return d

    # ── Poblar árbol (hilo principal) ──────────────────────────────────────────

    def _populate(self, data: dict) -> None:
        self._tree.clear()

        def _top(label: str, icon: str = "") -> QTreeWidgetItem:
            item = QTreeWidgetItem([f"{icon}  {label}" if icon else label])
            item.setForeground(0, QColor(C["text_dim"]))
            item.setFlags(Qt.ItemIsEnabled)
            font = item.font(0)
            font.setPointSize(9)
            font.setBold(True)
            item.setFont(0, font)
            self._tree.addTopLevelItem(item)
            item.setExpanded(True)
            return item

        def _child(parent: QTreeWidgetItem, label: str,
                   color: str = C["text"]) -> QTreeWidgetItem:
            child = QTreeWidgetItem([label])
            child.setForeground(0, QColor(color))
            parent.addChild(child)
            return child

        # ── Imágenes ──────────────────────────────────────────────────────────
        imgs = data.get("imagenes", [])
        t_img = _top(f"IMAGENES  ({len(imgs)})", "")
        if imgs:
            for img in imgs:
                txt = f"{img['scene_id'][:28]}  ·  {img['fecha'][:10]}"
                _child(t_img, txt, C["text"])
        else:
            _child(t_img, "Sin imágenes cargadas", C["text_dim"])

        # ── Índices espectrales ───────────────────────────────────────────────
        indices = data.get("indices", [])
        t_idx = _top(f"INDICES  ({len(indices)})", "")
        if indices:
            for idx in indices:
                _child(t_idx, f"{idx['nombre'].upper()}   ×{idx['n']}", C["accent"])
        else:
            _child(t_idx, "Sin índices calculados", C["text_dim"])

        # ── Análisis y Targets ────────────────────────────────────────────────
        analisis = data.get("analisis", [])
        total_tgt = sum(a["alta"] + a["media"] + a["baja"] for a in analisis)
        t_ana = _top(f"ANALISIS  ({total_tgt} targets)", "")
        if analisis:
            for a in analisis:
                t_a = QTreeWidgetItem([f"Análisis #{a['id']}  —  {a['fecha']}"])
                t_a.setForeground(0, QColor(C["text"]))
                t_ana.addChild(t_a)
                if a["alta"]:
                    _child(t_a, f"ALTA   ×{a['alta']}", C["success"])
                if a["media"]:
                    _child(t_a, f"MEDIA  ×{a['media']}", C["warning"])
                if a["baja"]:
                    _child(t_a, f"BAJA   ×{a['baja']}", C["text_dim"])
                t_a.setExpanded(True)
        else:
            _child(t_ana, "Sin análisis ejecutados", C["text_dim"])

        # ── Validaciones ──────────────────────────────────────────────────────
        val = data.get("validaciones", {})
        if val:
            pct = round((val["total"] - val["pendientes"]) / max(val["total"], 1) * 100)
            t_val = _top(f"VALIDACIONES  ({pct}%)", "")
            _child(t_val, f"✓ Positivos:  {val['positivos']}", C["success"])
            _child(t_val, f"✗ Negativos:  {val['negativos']}", C["error"])
            _child(t_val, f"○ Pendientes: {val['pendientes']}", C["text_dim"])
        else:
            t_val = _top("VALIDACIONES", "")
            _child(t_val, "Sin validaciones registradas", C["text_dim"])

        # ── Modelos ML ────────────────────────────────────────────────────────
        modelos = data.get("modelos", [])
        t_ml = _top(f"MODELOS ML  ({len(modelos)})", "")
        if modelos:
            for m in modelos:
                _child(t_ml, m["nombre"], C["accent"])
        else:
            _child(t_ml, "Sin modelos entrenados", C["text_dim"])

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _run(self, worker) -> None:
        """Inicia el worker manteniéndolo vivo hasta que termine."""
        self._workers.add(worker)
        worker.finished.connect(lambda: self._workers.discard(worker))
        worker.start()

    def _show_placeholder(self, msg: str) -> None:
        self._tree.clear()
        item = QTreeWidgetItem([msg])
        item.setForeground(0, QColor(C["text_dim"]))
        self._tree.addTopLevelItem(item)
