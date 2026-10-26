"""Панель рабочей папки: заказчики → проекты → изделия (обычные папки на диске)."""
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QDir, QSettings, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFileSystemModel,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

KOMPAS_EXTS = (".a3d", ".m3d", ".cdw", ".spw")
COPY_IGNORE = shutil.ignore_patterns("_backup", "_old", "~*", "_tmp_*")


def has_kompas_files(path):
    try:
        return any(e.is_file() and os.path.splitext(e.name)[1].lower() in KOMPAS_EXTS for e in os.scandir(path))
    except OSError:
        return False


def free_name(folder, name):
    candidate, n = os.path.join(folder, name), 1
    while os.path.exists(candidate):
        n += 1
        candidate = os.path.join(folder, f"{name} (копия {n - 1})" if n > 2 else f"{name} (копия)")
    return candidate


class _HideService(QSortFilterProxyModel):
    """Скрыть служебные папки (_backup, _old, .git …)."""

    def filterAcceptsRow(self, row, parent):
        index = self.sourceModel().index(row, 0, parent)
        name = self.sourceModel().fileName(index)
        return not name.startswith(("_", "."))


class WorkspacePanel(QWidget):
    open_requested = Signal(str)  # папка изделия
    new_product_requested = Signal(str)  # родительская папка
    folder_copied = Signal(str, str)  # откуда, куда

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("KompasManager", "KompasManager")
        self.clipboard = None

        self.root_edit = QLineEdit(self.settings.value("workspace_root", r"D:\Облако\YandexDisk\Progs\KMPS-PRJ"))
        self.root_edit.editingFinished.connect(self.set_root)
        browse = QPushButton("…")
        browse.setFixedWidth(28)
        browse.clicked.connect(self._browse)
        top = QHBoxLayout()
        top.addWidget(self.root_edit, 1)
        top.addWidget(browse)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Dirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.model.setReadOnly(True)
        self.proxy = _HideService(self)
        self.proxy.setSourceModel(self.model)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.clicked.connect(self._clicked)
        self.tree.doubleClicked.connect(lambda i: self.open_requested.emit(self.path_at(i)))

        hint = QLabel("Заказчик → проект → изделие. Папка с файлами КОМПАСа открывается щелчком.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Рабочая папка:"))
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(hint)
        self.set_root()

    # ---------- корень ----------

    def root(self):
        return self.root_edit.text().strip()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Рабочая папка", self.root() or os.path.expanduser("~"))
        if path:
            self.root_edit.setText(os.path.normpath(path))
            self.set_root()

    def set_root(self):
        root = self.root()
        self.settings.setValue("workspace_root", root)
        if os.path.isdir(root):
            index = self.model.setRootPath(root)
            self.tree.setRootIndex(self.proxy.mapFromSource(index))

    def path_at(self, proxy_index):
        return os.path.normpath(self.model.filePath(self.proxy.mapToSource(proxy_index)))

    def select(self, path):
        index = self.proxy.mapFromSource(self.model.index(path))
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)

    # ---------- действия ----------

    def _clicked(self, index):
        path = self.path_at(index)
        if has_kompas_files(path):
            self.open_requested.emit(path)

    def _menu(self, pos):
        index = self.tree.indexAt(pos)
        path = self.path_at(index) if index.isValid() else self.root()
        if not os.path.isdir(path):
            return
        menu = QMenu(self)
        menu.addAction("Открыть как изделие", lambda: self.open_requested.emit(path)).setEnabled(index.isValid())
        menu.addSeparator()
        menu.addAction("Новое изделие (структура)…", lambda: self.new_product_requested.emit(path))
        menu.addAction("Новая папка…", lambda: self._new_folder(path))
        if index.isValid():
            menu.addAction("Переименовать…", lambda: self._rename(path))
            menu.addSeparator()
            menu.addAction("Копировать папку", lambda: self._copy(path))
        paste = menu.addAction("Вставить папку" + (f" «{os.path.basename(self.clipboard)}»" if self.clipboard else ""),
                               lambda: self._paste(path))
        paste.setEnabled(bool(self.clipboard))
        menu.addSeparator()
        menu.addAction("Показать в проводнике", lambda: self._explorer(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_folder(self, parent):
        name, ok = QInputDialog.getText(self, "Новая папка", "Название (заказчик, проект или изделие):")
        if ok and name.strip():
            path = os.path.join(parent, name.strip())
            try:
                os.makedirs(path)
            except OSError as e:
                QMessageBox.warning(self, "Новая папка", str(e))
                return
            self.tree.expand(self.proxy.mapFromSource(self.model.index(parent)))
            self.select(path)

    def _rename(self, path):
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
        self.select(new)

    def _copy(self, path):
        self.clipboard = path

    def _paste(self, parent):
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
        self.tree.expand(self.proxy.mapFromSource(self.model.index(parent)))
        self.select(target)
        self.folder_copied.emit(src, target)

    def _explorer(self, path):
        if sys.platform == "win32":
            subprocess.Popen(f'explorer "{path}"')
