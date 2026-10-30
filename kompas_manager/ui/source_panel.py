"""Правое окно — источник: изделия из разделов и библиотека. Отсюда элементы вставляются
в выделенную сборку текущего изделия (левое окно)."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QStyle,
    QTabWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kompas_manager.core.model import KIND_TITLES
from kompas_manager.ui.node_dnd import DragTree, node_ref
from kompas_manager.ui.workspace_panel import WorkspacePanel

KEY_ROLE = Qt.UserRole + 40


class SourcePanel(QWidget):
    load_requested = Signal(str)  # открыть изделие-источник (папку)
    paste_requested = Signal(object, str)  # проект-источник, ключ узла
    copy_requested = Signal(dict)  # Ctrl+C: ссылка на узел

    def __init__(self, library_panel, parent=None):
        super().__init__(parent)
        self.project = None

        # --- Изделия
        self.browser = WorkspacePanel(browse_only=True)
        self.browser.open_requested.connect(self.load_requested.emit)
        self.title = QLabel("Выберите изделие в разделах выше")
        self.title.setWordWrap(True)
        self.tree = DragTree(self._ref_for)
        self.tree.setToolTip("Перетащите сборку или деталь в дерево изделия слева или нажмите Ctrl+C, "
                             "затем Ctrl+V на нужной сборке слева")
        self.tree.setHeaderLabels(["Обозначение", "Наименование", "Тип"])
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self._paste())
        self.tree.itemExpanded.connect(lambda *_: self.tree.resizeColumnToContents(0))
        self.target_label = QLabel()
        self.target_label.setStyleSheet("color: #06c;")
        self.target_label.setWordWrap(True)
        self.paste_btn = QPushButton("← Вставить в выделенную сборку")
        self.paste_btn.clicked.connect(self._paste)
        self.paste_btn.setEnabled(False)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.title)
        bl.addWidget(self.tree, 1)
        bl.addWidget(self.target_label)
        bl.addWidget(self.paste_btn)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.browser)
        split.addWidget(bottom)
        split.setSizes([260, 400])

        products = QWidget()
        pl = QVBoxLayout(products)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(split)

        # --- Библиотека
        self.library = library_panel
        self.library.insert_btn.setText("← Вставить в выделенную сборку…")

        self.tabs = QTabWidget()
        self.tabs.addTab(products, "Изделия")
        self.tabs.addTab(self.library, "Библиотека")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Источник</b>: что вставить в текущее изделие"))
        layout.addWidget(self.tabs, 1)

    def show_project(self, project):
        self.project = project
        self.tree.clear()
        self.title.setText(f"<b>{os.path.basename(project.root)}</b> — выделите сборку или деталь и нажмите «Вставить»")
        style = self.style()

        def item_for(key, count=1):
            d = project.doc(key)
            if d is None:
                return None
            text = d.name + (f"  ×{count}" if count > 1 else "")
            it = QTreeWidgetItem([d.designation, text, KIND_TITLES.get(d.kind, d.kind)])
            it.setData(0, KEY_ROLE, key)
            it.setIcon(0, style.standardIcon(QStyle.SP_DirIcon if d.kind == "assembly" else QStyle.SP_FileIcon))
            return it

        def add_children(parent, key, stack):
            for child, count in project.components.get(key, []):
                it = item_for(child, count)
                if it is None:
                    continue
                parent.addChild(it)
                if child not in stack:
                    add_children(it, child, stack | {child})

        for key in project.roots():
            it = item_for(key)
            self.tree.addTopLevelItem(it)
            add_children(it, key, {key})
        loose = project.loose_parts()
        if loose:
            group = QTreeWidgetItem([f"Детали вне сборок ({len(loose)})"])
            self.tree.addTopLevelItem(group)
            for key in loose:
                group.addChild(item_for(key))
        self.tree.expandToDepth(0)
        for c in (0, 2):
            self.tree.resizeColumnToContents(c)

    def set_target(self, text):
        self.target_label.setText(f"Куда: {text}" if text else "Откройте изделие слева — туда будет вставка")
        self.library.insert_btn.setToolTip(f"Вставить в {text}" if text else "")

    def _ref_for(self, item):
        key = item.data(0, KEY_ROLE) if item is not None else None
        return node_ref(self.project.root, key) if key and self.project is not None else None

    def copy_current(self):
        ref = self._ref_for(self.tree.currentItem())
        if ref:
            self.copy_requested.emit(ref)
        return ref

    def _current_key(self):
        it = self.tree.currentItem()
        return it.data(0, KEY_ROLE) if it is not None else None

    def _selection(self):
        self.paste_btn.setEnabled(bool(self._current_key()))

    def _paste(self):
        key = self._current_key()
        if key and self.project is not None:
            self.paste_requested.emit(self.project, key)
