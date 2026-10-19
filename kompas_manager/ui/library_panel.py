"""Вкладка «Библиотека»: дерево папок и элементов, сведения об элементе."""
import html
import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kompas_manager.core.library import KINDS, SPEC_SECTIONS, resolve_names, scan_library
from kompas_manager.core.naming import format_number

ELEMENT_ROLE = Qt.UserRole + 10


class LibraryPanel(QWidget):
    insert_requested = Signal(object)  # Element
    passport_requested = Signal(object)  # Element

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("KompasManager", "KompasManager")
        self.elements = []

        self.path_edit = QLineEdit(self.settings.value("library_root", r"D:\Облако\YandexDisk\Progs\KMPS-SET-SMP\Lib"))
        self.path_edit.editingFinished.connect(self.reload)
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        reload_btn = QPushButton("Обновить")
        reload_btn.clicked.connect(self.reload)
        top = QHBoxLayout()
        top.addWidget(QLabel("Папка библиотеки:"))
        top.addWidget(self.path_edit, 1)
        top.addWidget(browse)
        top.addWidget(reload_btn)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Поиск по названию элемента")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Элемент", "Тип", "Паспорт"])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.currentItemChanged.connect(self._show_details)
        self.tree.itemDoubleClicked.connect(self._double_clicked)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.filter_edit)
        lv.addWidget(self.tree, 1)

        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.details.setTextFormat(Qt.RichText)
        self.passport_btn = QPushButton("Паспорт элемента…")
        self.passport_btn.clicked.connect(lambda: self._emit(self.passport_requested))
        self.insert_btn = QPushButton("Вставить в проект…")
        self.insert_btn.setDefault(True)
        self.insert_btn.clicked.connect(lambda: self._emit(self.insert_requested))
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.passport_btn)
        buttons.addWidget(self.insert_btn)
        rv.addLayout(buttons)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        self._show_details(None, None)

    # ---------- данные ----------

    def root(self):
        return self.path_edit.text().strip()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Папка библиотеки", self.root() or os.path.expanduser("~"))
        if path:
            self.path_edit.setText(os.path.normpath(path))
            self.reload()

    def reload(self):
        root = self.root()
        self.settings.setValue("library_root", root)
        current = self.current_element()
        current_path = current.path if current else None
        self.tree.clear()
        self.elements = []
        if not os.path.isdir(root):
            self.details.setText(f"<i>Папка библиотеки не найдена:</i><br>{html.escape(root)}")
            return
        lib = scan_library(root)
        style = self.style()

        def add(parent, folder):
            for sub in folder.folders:
                item = QTreeWidgetItem([f"{sub.title} ({sub.count()})"])
                item.setIcon(0, style.standardIcon(QStyle.SP_DirIcon))
                parent.addChild(item) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(item)
                add(item, sub)
            for el in folder.elements:
                p = el.passport
                item = QTreeWidgetItem([el.title, KINDS.get(p.kind, "") if p else "", "есть" if p else "нет"])
                item.setIcon(0, style.standardIcon(QStyle.SP_FileIcon))
                item.setData(0, ELEMENT_ROLE, len(self.elements))
                self.elements.append(el)
                parent.addChild(item) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(item)
                if el.path == current_path:
                    self.tree.setCurrentItem(item)

        add(self.tree, lib)
        self.tree.expandToDepth(0)
        self.tree.resizeColumnToContents(1)
        self._apply_filter(self.filter_edit.text())

    def current_element(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        idx = item.data(0, ELEMENT_ROLE)
        return self.elements[idx] if idx is not None else None

    def _emit(self, signal):
        el = self.current_element()
        if el is not None:
            signal.emit(el)

    def _double_clicked(self, item, _col):
        if item.data(0, ELEMENT_ROLE) is not None:
            self._emit(self.insert_requested)

    def _apply_filter(self, text):
        text = text.strip().lower()

        def visit(item):
            if item.data(0, ELEMENT_ROLE) is not None:
                visible = not text or text in item.text(0).lower()
            else:
                visible = False
                for i in range(item.childCount()):
                    visible = visit(item.child(i)) or visible
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))
        if text:
            self.tree.expandAll()

    def _show_details(self, current, _prev):
        el = self.current_element()
        self.passport_btn.setEnabled(el is not None)
        self.insert_btn.setEnabled(el is not None)
        if el is None:
            self.details.setText("<i>Выберите элемент библиотеки.</i>")
            return
        p = el.passport
        lines = [f"<b>{html.escape(el.title)}</b>",
                 f"<span style='color:gray'>{html.escape(os.path.relpath(el.path, self.root()))}</span><br>"]
        if p is None:
            lines.append("Паспорта нет. Откройте «Паспорт элемента», чтобы прочитать переменные модели "
                         "и задать шаблоны обозначения и наименования.<br>"
                         "Без паспорта элемент вставляется копией со значениями по умолчанию из модели.")
        else:
            des, name, _ = resolve_names(el, {})
            lines.append(f"Тип: {KINDS.get(p.kind, p.kind)} (раздел спецификации «{SPEC_SECTIONS.get(p.kind, '')}»)")
            if p.designation_template:
                lines.append(f"Шаблон обозначения: <code>{html.escape(p.designation_template)}</code>")
            if p.name_template:
                lines.append(f"Шаблон наименования: <code>{html.escape(p.name_template)}</code>")
            if des or name:
                lines.append(f"По умолчанию: {html.escape(des)} {html.escape(name)}")
            if p.table:
                exists = os.path.exists(el.table_path())
                lines.append(f"Таблица типоразмеров: {html.escape(p.table)}" + ("" if exists else " <b>(не найдена)</b>"))
            if p.variables:
                rows = "".join(
                    f"<tr><td>{html.escape(v.name)}</td><td align='right'>{html.escape(format_number(v.value))}</td>"
                    f"<td style='color:gray'>{'вычисляемая' if v.info else html.escape(v.note or '')}</td></tr>"
                    for v in p.variables)
                lines.append(f"<br>Переменные:<table cellspacing='6'>{rows}</table>")
        self.details.setText("<br>".join(lines))
