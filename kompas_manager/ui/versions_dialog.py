"""Окно версий узла: сохранить текущую, восстановить сохранённую."""
import os
import subprocess
import sys

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from kompas_manager.core.versions import list_versions, plan_restore, related, save_version


class VersionsDialog(QDialog):
    """Результат: self.restore_plan (если выбрано восстановление) и self.move_orphans."""

    def __init__(self, project, key, parent=None):
        super().__init__(parent)
        self.project, self.key = project, key
        d = project.doc(key)
        self.setWindowTitle(f"Версии узла — {d.designation} {d.name}")
        self.resize(900, 460)
        self.restore_plan = None
        self.move_orphans = True

        self.only_this = QCheckBox("Только версии этого узла")
        self.only_this.setChecked(True)
        self.only_this.toggled.connect(self._fill)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(["Дата", "Узел", "Комментарий", "Файлов"])
        self.table.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._selection)
        self.orphans = QCheckBox("Файлы текущего узла, которых нет в восстанавливаемой версии, убрать в _old")
        self.orphans.setChecked(True)

        save_btn = QPushButton("Сохранить текущую версию…")
        save_btn.clicked.connect(self._save)
        self.restore_btn = QPushButton("Восстановить выбранную…")
        self.restore_btn.clicked.connect(self._restore)
        folder_btn = QPushButton("Папка версий")
        folder_btn.clicked.connect(self._folder)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(save_btn)
        buttons.addWidget(self.restore_btn)
        buttons.addWidget(folder_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        note = QLabel("Версия — архив узла со всем составом, чертежами и спецификациями в папке _versions изделия. "
                      "Перед восстановлением текущее состояние сохраняется как версия автоматически, "
                      "родительские сборки перепривязываются на восстановленный узел.")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.only_this)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.orphans)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self._fill()

    def _fill(self):
        self.table.clear()
        self.versions = [v for v in list_versions(self.project.root)
                         if not self.only_this.isChecked() or related(v, self.project, self.key)]
        for v in self.versions:
            self.table.addTopLevelItem(QTreeWidgetItem([v.time, v.title, v.comment, str(len(v.files))]))
        for c in (0, 1, 3):
            self.table.resizeColumnToContents(c)
        self.table.setColumnWidth(0, max(self.table.columnWidth(0) + 16, 130))
        self._selection()

    def _selection(self):
        self.restore_btn.setEnabled(bool(self.table.selectedItems()))

    def _save(self):
        comment, ok = QInputDialog.getText(self, "Сохранить версию", "Комментарий (что это за версия):")
        if not ok:
            return
        try:
            v = save_version(self.project, self.key, comment.strip())
        except OSError as e:
            QMessageBox.warning(self, self.windowTitle(), f"Не удалось сохранить версию:\n{e}")
            return
        self._fill()
        QMessageBox.information(self, self.windowTitle(), f"Версия сохранена: {os.path.basename(v.path)}")

    def _restore(self):
        items = self.table.selectedItems()
        if not items:
            return
        v = self.versions[self.table.indexOfTopLevelItem(items[0])]
        plan = plan_restore(self.project, v, self.key)
        text = (f"Восстановить версию «{v.title}» от {v.time}?\n\n"
                f"Будет распаковано файлов: {len(v.files)}.\n"
                "Текущее состояние узла сначала сохранится как версия.")
        if plan.parents:
            text += "\nПерепривязываются сборки: " + ", ".join(os.path.basename(p) for p in plan.parents)
        if plan.orphans and self.orphans.isChecked():
            text += f"\nВ _old уйдут файлы, которых нет в версии: {len(plan.orphans)}"
        text += "\n\nФайлы узла должны быть закрыты в КОМПАСе."
        if QMessageBox.question(self, self.windowTitle(), text) != QMessageBox.Yes:
            return
        self.restore_plan = plan
        self.move_orphans = self.orphans.isChecked()
        self.accept()

    def _folder(self):
        folder = os.path.join(self.project.root, "_versions")
        os.makedirs(folder, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(f'explorer "{folder}"')
