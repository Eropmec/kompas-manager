"""Перетаскивание и Ctrl+C / Ctrl+V узлов и изделий между окнами.

Ссылка на узел — словарь:
- {"root": папка изделия, "key": ключ модели} — сборка или деталь изделия;
- {"product": папка изделия} — изделие целиком (его головная сборка).
"""
import json
import os

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QTreeView, QTreeWidget

MIME = "application/x-kompas-node"


def node_ref(root, key):
    return {"root": root, "key": key}


def product_ref(folder):
    return {"product": folder}


def ref_title(ref):
    if not ref:
        return ""
    if "product" in ref:
        return f"изделие «{os.path.basename(os.path.normpath(ref['product']))}»"
    return f"узел «{os.path.splitext(os.path.basename(ref['key']))[0]}»"


def to_mime(ref):
    data = QMimeData()
    data.setData(MIME, json.dumps(ref, ensure_ascii=False).encode("utf-8"))
    data.setText(ref.get("product") or ref.get("key", ""))
    return data


def from_mime(data):
    if data is None or not data.hasFormat(MIME):
        return None
    try:
        ref = json.loads(bytes(data.data(MIME)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(ref, dict) and (ref.get("product") or (ref.get("root") and ref.get("key"))):
        return ref
    return None


class DragTree(QTreeWidget):
    """QTreeWidget, элементы которого перетаскиваются как ссылки на узлы.
    ref_for(item) -> ссылка или None (такой элемент не тащится)."""

    def __init__(self, ref_for, parent=None):
        super().__init__(parent)
        self.ref_for = ref_for
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def startDrag(self, _actions):
        it = self.currentItem()
        ref = self.ref_for(it) if it is not None else None
        if not ref:
            return
        drag = QDrag(self)
        drag.setMimeData(to_mime(ref))
        drag.exec(Qt.CopyAction)


class NodeTreeView(QTreeView):
    """Дерево текущего изделия: принимает перетаскиваемые узлы и само может их отдавать.
    ref_at(index) -> ссылка на узел под индексом; accepts(index) -> можно ли бросить сюда."""

    node_dropped = Signal(dict, object)  # ссылка, индекс (QModelIndex) под курсором

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ref_at = lambda index: None
        self.accepts = lambda index: False
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)

    def startDrag(self, _actions):
        ref = self.ref_at(self.currentIndex())
        if not ref:
            return
        drag = QDrag(self)
        drag.setMimeData(to_mime(ref))
        drag.exec(Qt.CopyAction)

    def _index(self, event):
        return self.indexAt(event.position().toPoint())

    def dragEnterEvent(self, event):
        if from_mime(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if from_mime(event.mimeData()) and self.accepts(self._index(event)):
            index = self._index(event)
            if index.isValid():
                self.setCurrentIndex(index)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        ref = from_mime(event.mimeData())
        if not ref:
            event.ignore()
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.node_dropped.emit(ref, self._index(event))
