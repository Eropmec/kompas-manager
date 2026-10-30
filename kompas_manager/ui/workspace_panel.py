"""Левая панель: разделы (пути к папкам с проектами), внутри — заказчики, проекты, изделия."""
import json
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

KOMPAS_EXTS = (".a3d", ".m3d", ".cdw", ".spw")
COPY_IGNORE = shutil.ignore_patterns("_backup", "_old", "~*", "_tmp_*")
PATH_ROLE = Qt.UserRole + 30
LOADED_ROLE = Qt.UserRole + 31
SECTION_ROLE = Qt.UserRole + 32


def has_kompas_files(path):
    try:
        return any(e.is_file() and os.path.splitext(e.name)[1].lower() in KOMPAS_EXTS for e in os.scandir(path))
    except OSError:
        return False


def is_project(path):
    """Папка проекта: в ней лежат изделия (папки с файлами КОМПАСа)."""
    return any(has_kompas_files(d) for d in subdirs(path))


def project_of(sections, path):
    """Папка проекта для изделия или его подпапки: раздел → заказчик → проект → изделие,
    то есть второй уровень от папки раздела. Вне разделов и выше проекта — сама папка."""
    full = os.path.normcase(os.path.abspath(path))
    best = None
    for s in sections:
        sec = os.path.normcase(os.path.abspath(s["path"]))
        if (full == sec or full.startswith(sec + os.sep)) and (best is None or len(sec) > len(best[0])):
            best = (sec, os.path.abspath(s["path"]))
    if best is None:
        return path
    parts = os.path.relpath(os.path.abspath(path), best[1]).split(os.sep)
    if parts == ["."] or len(parts) <= 2:
        return path
    return os.path.join(best[1], parts[0], parts[1])


def subdirs(path):
    try:
        return sorted((e.path for e in os.scandir(path)
                       if e.is_dir() and not e.name.startswith(("_", "."))), key=lambda p: os.path.basename(p).lower())
    except OSError:
        return []


def free_name(folder, name):
    candidate = os.path.join(folder, name)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{name} (копия)" if n == 1 else f"{name} (копия {n})")
        n += 1
    return candidate


def load_sections(q):
    try:
        data = json.loads(q.value("sections", "") or "[]")
        sections = [{"name": s["name"], "path": s["path"]} for s in data if s.get("path")]
    except (ValueError, TypeError, KeyError):
        sections = []
    if not sections:
        old = q.value("workspace_root", r"D:\Облако\YandexDisk\Progs\KMPS-PRJ")
        sections = [{"name": os.path.basename(old.rstrip("\\/")) or old, "path": old}]
    return sections


def save_sections(q, sections):
    q.setValue("sections", json.dumps(sections, ensure_ascii=False))


class SectionsDialog(QDialog):
    """Список разделов: название и путь к папке."""

    def __init__(self, sections, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Разделы")
        self.resize(760, 360)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Название", "Папка"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for s in sections:
            self._add_row(s["name"], s["path"])
        buttons = QHBoxLayout()
        for text, slot in (("Добавить папку…", self._add), ("Изменить путь…", self._change),
                           ("Удалить", self._remove), ("↑", lambda: self._move(-1)), ("↓", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        from kompas_manager.ui.dialogs import russian_buttons

        box = russian_buttons(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Каждый раздел — папка, где лежат заказчики и проекты. Название можно изменить "
                                "двойным щелчком. Файлы на диске не меняются."))
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(box)

    def _add_row(self, name, path, row=None):
        row = self.table.rowCount() if row is None else row
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        p = QTableWidgetItem(path)
        p.setFlags(p.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 1, p)

    def _add(self):
        path = QFileDialog.getExistingDirectory(self, "Папка раздела", os.path.expanduser("~"))
        if path:
            path = os.path.normpath(path)
            self._add_row(os.path.basename(path) or path, path)

    def _change(self):
        row = self.table.currentRow()
        if row < 0:
            return
        path = QFileDialog.getExistingDirectory(self, "Папка раздела", self.table.item(row, 1).text())
        if path:
            self.table.item(row, 1).setText(os.path.normpath(path))

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _move(self, step):
        row = self.table.currentRow()
        new = row + step
        if row < 0 or not 0 <= new < self.table.rowCount():
            return
        name, path = self.table.item(row, 0).text(), self.table.item(row, 1).text()
        self.table.removeRow(row)
        self._add_row(name, path, new)
        self.table.selectRow(new)

    def sections(self):
        out = []
        for r in range(self.table.rowCount()):
            path = self.table.item(r, 1).text().strip()
            if path:
                out.append({"name": self.table.item(r, 0).text().strip() or os.path.basename(path), "path": path})
        return out


class WorkspacePanel(QWidget):
    open_requested = Signal(str)  # папка изделия
    new_product_requested = Signal(str)  # родительская папка
    folder_copied = Signal(str, str)  # откуда, куда
    product_copied = Signal(dict)  # Ctrl+C на изделии: ссылка для вставки в сборку

    def __init__(self, parent=None, browse_only=False):
        super().__init__(parent)
        self.browse_only = browse_only  # окно-источник: только просмотр и открытие
        self.q = QSettings("KompasManager", "KompasManager")
        self.clipboard = None
        self.sections = load_sections(self.q)

        sections_btn = QPushButton("Разделы…")
        sections_btn.clicked.connect(self.edit_sections)
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self.reload)
        top = QHBoxLayout()
        top.addWidget(sections_btn)
        top.addWidget(refresh_btn)
        top.addStretch(1)

        from kompas_manager.ui.node_dnd import DragTree

        self.tree = DragTree(self._ref_for)
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemExpanded.connect(self._load_children)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._open(it))

        hint = QLabel("Раздел → заказчик → проект → изделие. " + (
            "Щелчок по изделию показывает его состав ниже." if browse_only else
            "Папка с файлами КОМПАСа открывается щелчком."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(hint)
        self.reload()

    # ---------- дерево ----------

    def _folder_item(self, path):
        item = QTreeWidgetItem([os.path.basename(path)])
        item.setData(0, PATH_ROLE, path)
        item.setToolTip(0, path)
        product = has_kompas_files(path)
        icon = (QStyle.SP_FileDialogDetailedView if product else
                QStyle.SP_DirHomeIcon if is_project(path) else QStyle.SP_DirIcon)
        item.setIcon(0, self.style().standardIcon(icon))
        if product:
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
        if subdirs(path):
            item.addChild(QTreeWidgetItem(["…"]))  # заглушка: раскрывается плюсиком, загружается при раскрытии
        return item

    def reload(self):
        expanded = self._expanded_paths()
        self.tree.clear()
        for s in self.sections:
            item = QTreeWidgetItem([s["name"]])
            item.setData(0, PATH_ROLE, s["path"])
            item.setData(0, SECTION_ROLE, True)
            item.setToolTip(0, s["path"])
            font = QFont(item.font(0))
            font.setBold(True)
            item.setFont(0, font)
            item.setIcon(0, self.style().standardIcon(QStyle.SP_DriveHDIcon))
            if not os.path.isdir(s["path"]):
                item.setText(0, f"{s['name']} (папка не найдена)")
                item.setDisabled(True)
            elif subdirs(s["path"]):
                item.addChild(QTreeWidgetItem(["…"]))
            self.tree.addTopLevelItem(item)
        self._restore_expanded(expanded)

    def _load_children(self, item):
        if item.data(0, LOADED_ROLE):
            return
        item.setData(0, LOADED_ROLE, True)
        item.takeChildren()
        for p in subdirs(item.data(0, PATH_ROLE)):
            item.addChild(self._folder_item(p))

    def _expanded_paths(self):
        out = set()

        def walk(it):
            if it.isExpanded():
                out.add(os.path.normcase(it.data(0, PATH_ROLE) or ""))
                for i in range(it.childCount()):
                    walk(it.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def _restore_expanded(self, paths):
        def walk(it):
            if os.path.normcase(it.data(0, PATH_ROLE) or "") in paths:
                it.setExpanded(True)
                for i in range(it.childCount()):
                    walk(it.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def current_folder(self):
        it = self.tree.currentItem()
        return it.data(0, PATH_ROLE) if it is not None else (self.sections[0]["path"] if self.sections else "")

    def select(self, path):
        """Раскрыть дерево до папки path и выделить её."""
        target = os.path.normcase(os.path.normpath(path))
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            root = os.path.normcase(os.path.normpath(it.data(0, PATH_ROLE)))
            if target == root or target.startswith(root + os.sep):
                while it is not None:
                    if os.path.normcase(os.path.normpath(it.data(0, PATH_ROLE))) == target:
                        self.tree.setCurrentItem(it)
                        self.tree.scrollToItem(it)
                        return
                    it.setExpanded(True)
                    self._load_children(it)
                    nxt = None
                    for j in range(it.childCount()):
                        c = it.child(j)
                        cp = os.path.normcase(os.path.normpath(c.data(0, PATH_ROLE) or ""))
                        if cp and (target == cp or target.startswith(cp + os.sep)):
                            nxt = c
                            break
                    it = nxt
                return

    def _refresh_item(self, item):
        if item is None:
            return
        item.setData(0, LOADED_ROLE, False)
        was = item.isExpanded()
        item.takeChildren()
        if subdirs(item.data(0, PATH_ROLE)):
            item.addChild(QTreeWidgetItem(["…"]))
        if was:
            item.setExpanded(False)
            item.setExpanded(True)

    # ---------- действия ----------

    def edit_sections(self):
        dlg = SectionsDialog(self.sections, self)
        if dlg.exec():
            self.sections = dlg.sections()
            save_sections(self.q, self.sections)
            self.reload()

    def _ref_for(self, item):
        """Изделие (папка с файлами КОМПАСа) перетаскивается в сборку как узел."""
        from kompas_manager.ui.node_dnd import product_ref

        path = item.data(0, PATH_ROLE) if item is not None else None
        if path and not item.data(0, SECTION_ROLE) and has_kompas_files(path):
            return product_ref(path)
        return None

    def copy_current(self):
        ref = self._ref_for(self.tree.currentItem())
        if ref:
            self.product_copied.emit(ref)
        return ref

    def project_of(self, path):
        return project_of(self.sections, path)

    def _clicked(self, item, _col):
        path = item.data(0, PATH_ROLE)
        if path and not item.data(0, SECTION_ROLE) and (has_kompas_files(path) or
                                                         (not self.browse_only and is_project(path))):
            self.open_requested.emit(path)

    def _open(self, item):
        path = item.data(0, PATH_ROLE)
        if path and not item.data(0, SECTION_ROLE):
            self.open_requested.emit(path)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            menu = QMenu(self)
            menu.addAction("Разделы…", self.edit_sections)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        path = item.data(0, PATH_ROLE)
        if not path or not os.path.isdir(path):
            return
        section = bool(item.data(0, SECTION_ROLE))
        menu = QMenu(self)
        if self.browse_only:
            if not section:
                menu.addAction("Показать состав", lambda: self.open_requested.emit(path))
                if self._ref_for(item):
                    menu.addAction("Копировать изделие для вставки в сборку\tCtrl+C", self.copy_current)
            menu.addAction("Обновить", lambda: self._refresh_item(item))
            menu.addAction("Показать в проводнике", lambda: self._explorer(path))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if not section:
            menu.addAction("Открыть проект" if is_project(path) else "Открыть (проект этого изделия)",
                           lambda: self.open_requested.emit(path))
            menu.addSeparator()
        menu.addAction("Новое изделие (структура)…", lambda: self.new_product_requested.emit(path))
        menu.addAction("Новая папка…", lambda: self._new_folder(item, path))
        if not section:
            menu.addAction("Переименовать…", lambda: self._rename(item, path))
            menu.addSeparator()
            menu.addAction("Копировать папку", lambda: setattr(self, "clipboard", path))
            if self._ref_for(item):
                menu.addAction("Копировать изделие для вставки в сборку\tCtrl+C", self.copy_current)
        paste = menu.addAction("Вставить папку" + (f" «{os.path.basename(self.clipboard)}»" if self.clipboard else ""),
                               lambda: self._paste(item, path))
        paste.setEnabled(bool(self.clipboard))
        menu.addSeparator()
        menu.addAction("Обновить", lambda: self._refresh_item(item))
        menu.addAction("Показать в проводнике", lambda: self._explorer(path))
        if section:
            menu.addAction("Разделы…", self.edit_sections)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_folder(self, item, parent):
        name, ok = QInputDialog.getText(self, "Новая папка", "Название (заказчик, проект или изделие):")
        if ok and name.strip():
            path = os.path.join(parent, name.strip())
            try:
                os.makedirs(path)
            except OSError as e:
                QMessageBox.warning(self, "Новая папка", str(e))
                return
            self._refresh_item(item)
            self.select(path)

    def _rename(self, item, path):
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое название:", text=os.path.basename(path))
        if not ok or not name.strip() or name.strip() == os.path.basename(path):
            return
        new = os.path.join(os.path.dirname(path), name.strip())
        if os.path.exists(new):
            QMessageBox.warning(self, "Переименовать", "Папка с таким названием уже есть.")
            return
        try:
            os.rename(path, new)
        except OSError as e:
            QMessageBox.warning(self, "Переименовать",
                                f"Не удалось переименовать (файлы открыты в КОМПАСе или синхронизируются?):\n{e}")
            return
        self._refresh_item(item.parent())
        self.select(new)

    def _paste(self, item, parent):
        src = self.clipboard
        if not src or not os.path.isdir(src):
            return
        if os.path.normcase(parent + os.sep).startswith(os.path.normcase(src + os.sep)):
            QMessageBox.warning(self, "Вставить", "Нельзя вставить папку внутрь неё самой.")
            return
        target = free_name(parent, os.path.basename(src))
        try:
            shutil.copytree(src, target, ignore=COPY_IGNORE)
        except OSError as e:
            QMessageBox.warning(self, "Вставить", f"Копирование не удалось:\n{e}")
            return
        self._refresh_item(item)
        self.select(target)
        self.folder_copied.emit(src, target)

    def _explorer(self, path):
        if sys.platform == "win32":
            subprocess.Popen(f'explorer "{path}"')
