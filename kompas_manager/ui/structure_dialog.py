"""Редактор новой структуры изделия: дерево сборок и деталей до создания файлов."""
import html
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from kompas_manager.core.schemes import load_library
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.core.structure import Node, designate, plan_files
from kompas_manager.ui.dialogs import russian_buttons

KIND_ROLE = Qt.UserRole + 20
COL_NAME, COL_COUNT, COL_DES = 0, 1, 2


class StructureDialog(QDialog):
    def __init__(self, parent_folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новое изделие")
        self.resize(820, 640)
        self.parent_folder = parent_folder
        self.items = []
        self.problems = []
        self.settings = ProjectSettings.load(parent_folder)  # схема ближайшего проекта, если есть

        self.product = QLineEdit("Изделие")
        self.product.textChanged.connect(self._root_name_changed)
        self.in_place = QCheckBox("Создать файлы прямо в выбранной папке, без новой подпапки")
        self.in_place.toggled.connect(self._update)
        self.scheme = QComboBox()
        self.schemes = load_library()
        for s in self.schemes:
            self.scheme.addItem(f"{s.name}  —  {s.template}")
        idx = next((i for i, s in enumerate(self.schemes) if s.template == self.settings.scheme.template), 0)
        self.scheme.setCurrentIndex(idx)
        self.scheme.currentIndexChanged.connect(self._update)
        self.code = QLineEdit(self.settings.code)
        self.code.textChanged.connect(self._update)

        form = QFormLayout()
        form.addRow("Наименование изделия:", self.product)
        form.addRow("", self.in_place)
        form.addRow("Схема обозначения:", self.scheme)
        form.addRow("Код {код}:", self.code)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Наименование", "Кол.", "Обозначение (по схеме)"])
        self.tree.header().setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.SelectedClicked)
        self.tree.itemChanged.connect(lambda *_: self._update())
        self.root_item = self._make_item("assembly", "Изделие")
        self.tree.addTopLevelItem(self.root_item)

        buttons_row = QHBoxLayout()
        for text, slot in (("+ Сборка", lambda: self._add("assembly")), ("+ Деталь", lambda: self._add("part")),
                           ("Удалить", self._remove), ("↑", lambda: self._move(-1)), ("↓", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons_row.addWidget(b)
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setPrefix("Кол.: ")
        self.count.valueChanged.connect(self._set_count)
        buttons_row.addWidget(self.count)
        buttons_row.addStretch(1)
        self.tree.currentItemChanged.connect(self._selected)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)

        q = QSettings("KompasManager", "KompasManager")
        tpl = [t for t in (q.value("template_part", ""), q.value("template_asm", "")) if t]
        tpl_note = QLabel("Шаблоны: " + (", ".join(os.path.basename(t) for t in tpl) if tpl else
                                         "стандартные пустые документы КОМПАСа (свои — «Сервис → Настройки»)"))
        tpl_note.setStyleSheet("color: gray;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        russian_buttons(buttons)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        self.ok.setText("Создать файлы")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Состав (двойной щелчок — переименовать; детали и подсборки добавляются в выделенную сборку):"))
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons_row)
        layout.addWidget(self.preview)
        layout.addWidget(tpl_note)
        layout.addWidget(buttons)
        self.tree.setCurrentItem(self.root_item)
        self._update()

    # ---------- дерево ----------

    def _make_item(self, kind, name, count=1):
        item = QTreeWidgetItem([name, str(count), ""])
        item.setData(0, KIND_ROLE, kind)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        icon = QStyle.SP_DirIcon if kind == "assembly" else QStyle.SP_FileIcon
        item.setIcon(0, self.style().standardIcon(icon))
        item.setTextAlignment(COL_COUNT, Qt.AlignCenter)
        return item

    def _target_assembly(self):
        item = self.tree.currentItem() or self.root_item
        while item is not None and item.data(0, KIND_ROLE) != "assembly":
            item = item.parent()
        return item or self.root_item

    def _add(self, kind):
        parent = self._target_assembly()
        n = parent.childCount() + 1
        item = self._make_item(kind, "Сборка" if kind == "assembly" else f"Деталь {n}")
        parent.addChild(item)
        parent.setExpanded(True)
        self.tree.setCurrentItem(item)
        self.tree.editItem(item, COL_NAME)
        self._update()

    def _remove(self):
        item = self.tree.currentItem()
        if item is None or item is self.root_item:
            return
        item.parent().removeChild(item)
        self._update()

    def _move(self, step):
        item = self.tree.currentItem()
        if item is None or item is self.root_item:
            return
        parent = item.parent()
        i = parent.indexOfChild(item)
        j = i + step
        if 0 <= j < parent.childCount():
            expanded = item.isExpanded()
            parent.takeChild(i)
            parent.insertChild(j, item)
            item.setExpanded(expanded)
            self.tree.setCurrentItem(item)
            self._update()

    def _selected(self, current, _prev):
        self.count.blockSignals(True)
        self.count.setEnabled(current is not None and current is not self.root_item)
        if current is not None:
            try:
                self.count.setValue(int(current.text(COL_COUNT) or 1))
            except ValueError:
                self.count.setValue(1)
        self.count.blockSignals(False)

    def _set_count(self, value):
        item = self.tree.currentItem()
        if item is not None and item is not self.root_item:
            item.setText(COL_COUNT, str(value))

    def _root_name_changed(self, text):
        self.root_item.setText(COL_NAME, text)

    # ---------- расчёт ----------

    def build_nodes(self):
        def node(item):
            try:
                count = max(1, int(item.text(COL_COUNT) or 1))
            except ValueError:
                count = 1
            n = Node(item.data(0, KIND_ROLE), item.text(COL_NAME).strip(), count=count)
            n.children = [node(item.child(i)) for i in range(item.childCount())]
            n._item = item
            return n

        return node(self.root_item)

    def folder(self):
        if self.in_place.isChecked():
            return self.parent_folder
        return os.path.join(self.parent_folder, self.product.text().strip() or "Изделие")

    def project_settings(self):
        s = ProjectSettings.load(self.parent_folder)
        s.scheme = self.schemes[self.scheme.currentIndex()]
        s.code = self.code.text().strip()
        return s

    def _update(self):
        self.tree.blockSignals(True)
        root = self.build_nodes()
        settings = self.project_settings()
        designations, _w = designate(root, self.folder(), settings)
        for n in root.walk():
            n._item.setText(COL_DES, designations.get(id(n), ""))
        self.tree.blockSignals(False)
        self.root_node = root
        self.items, self.problems = plan_files(root, self.folder(), settings)
        if self.product.text() != root.name:
            self.product.blockSignals(True)
            self.product.setText(root.name)
            self.product.blockSignals(False)
        parts = sum(1 for i in self.items if i.node.kind == "part")
        text = (f"Будет создано: сборок {len(self.items) - parts}, деталей {parts} в папке "
                f"<b>{html.escape(self.folder())}</b>")
        if self.problems:
            text += "<br><span style='color:#b00'>" + "<br>".join(html.escape(p) for p in self.problems) + "</span>"
        self.preview.setText(text)
        self.ok.setEnabled(not self.problems)

    def _accept(self):
        if not self.in_place.isChecked() and os.path.exists(self.folder()):
            QMessageBox.warning(self, self.windowTitle(), "Папка изделия уже существует. Измените наименование "
                                "или отметьте «Создать файлы прямо в выбранной папке».")
            return
        self.accept()
