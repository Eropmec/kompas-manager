"""Окно прототипа: разведка Kompas API и тест переобозначения детали.

Работа с КОМПАСом идёт в отдельном потоке, чтобы окно не зависало.
"""
import gc
import os
import sys
import traceback

from PySide6.QtCore import QSettings, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from naming import file_name

APP_TITLE = "КОМПАС: прототип переобозначения"


class Worker(QThread):
    """Выполняет разведку или тест переобозначения в отдельном потоке."""

    line = Signal(str)
    done = Signal(str)  # путь к отчёту, пусто при критической ошибке

    def __init__(self, task, kwargs):
        super().__init__()
        self.task = task
        self.kwargs = kwargs

    def run(self):
        import pythoncom

        pythoncom.CoInitialize()
        report_path = ""
        try:
            if self.task == "probe":
                import probe

                report_path = probe.run(on_line=self.line.emit, **self.kwargs)
            else:
                import rename_test

                report_path = rename_test.run(on_line=self.line.emit, **self.kwargs)
        except Exception:
            self.line.emit("\nКРИТИЧЕСКАЯ ОШИБКА:\n" + traceback.format_exc())
        finally:
            gc.collect()  # освободить COM-объекты до CoUninitialize
            pythoncom.CoUninitialize()
        self.done.emit(report_path or "")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(940, 720)
        self.settings = QSettings("KompasManager", "Prototype")
        self.worker = None
        self.last_report = ""

        central = QWidget()
        layout = QVBoxLayout(central)

        # --- 1. Разведка
        g1 = QGroupBox("1. Разведка: что видит Kompas API (только чтение)")
        l1 = QGridLayout(g1)
        self.project_edit = QLineEdit(self.settings.value("project", ""))
        browse_project = QPushButton("Обзор…")
        browse_project.clicked.connect(self.pick_project)
        l1.addWidget(QLabel("Папка тестового проекта:"), 0, 0)
        l1.addWidget(self.project_edit, 0, 1)
        l1.addWidget(browse_project, 0, 2)
        self.verbose = QCheckBox("Подробно: выводить списки свойств интерфейсов API")
        l1.addWidget(self.verbose, 1, 1)
        self.probe_btn = QPushButton("Запустить разведку")
        self.probe_btn.clicked.connect(self.run_probe)
        l1.addWidget(self.probe_btn, 2, 1)
        layout.addWidget(g1)

        # --- 2. Тест переобозначения
        g2 = QGroupBox("2. Тест переобозначения детали (на копии проекта, оригинал не меняется)")
        l2 = QGridLayout(g2)
        self.part_edit = QLineEdit(self.settings.value("part", ""))
        browse_part = QPushButton("Обзор…")
        browse_part.clicked.connect(self.pick_part)
        self.des_edit = QLineEdit(self.settings.value("designation", "АБВГ.001.01"))
        self.name_edit = QLineEdit(self.settings.value("name", "Втулка"))
        self.preview = QLabel()
        l2.addWidget(QLabel("Деталь (.m3d):"), 0, 0)
        l2.addWidget(self.part_edit, 0, 1)
        l2.addWidget(browse_part, 0, 2)
        l2.addWidget(QLabel("Новое обозначение:"), 1, 0)
        l2.addWidget(self.des_edit, 1, 1)
        l2.addWidget(QLabel("Новое наименование:"), 2, 0)
        l2.addWidget(self.name_edit, 2, 1)
        l2.addWidget(QLabel("Новое имя файла:"), 3, 0)
        l2.addWidget(self.preview, 3, 1)
        self.rename_btn = QPushButton("Переобозначить на копии")
        self.rename_btn.clicked.connect(self.run_rename)
        l2.addWidget(self.rename_btn, 4, 1)
        layout.addWidget(g2)
        self.des_edit.textChanged.connect(self.update_preview)
        self.name_edit.textChanged.connect(self.update_preview)
        self.update_preview()

        # --- Журнал
        layout.addWidget(QLabel("Журнал:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        self.log.setFont(font)
        layout.addWidget(self.log, 1)

        buttons = QHBoxLayout()
        self.open_btn = QPushButton("Открыть папку отчёта")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_report_folder)
        clear_btn = QPushButton("Очистить журнал")
        clear_btn.clicked.connect(self.log.clear)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.setCentralWidget(central)

    # ---------- выбор файлов ----------

    def pick_project(self):
        start = self.project_edit.text() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Папка тестового проекта", start)
        if path:
            self.project_edit.setText(os.path.normpath(path))

    def pick_part(self):
        start = self.project_edit.text() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Деталь для переобозначения", start, "Детали КОМПАС (*.m3d)")
        if path:
            self.part_edit.setText(os.path.normpath(path))

    def update_preview(self):
        des, name = self.des_edit.text().strip(), self.name_edit.text().strip()
        self.preview.setText(file_name(des, name, ".m3d") if des and name else "—")

    # ---------- запуск ----------

    def project_dir(self):
        path = self.project_edit.text().strip()
        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, APP_TITLE, "Укажите существующую папку тестового проекта.")
            return None
        return os.path.abspath(path)

    def run_probe(self):
        project = self.project_dir()
        if project is None:
            return
        self.save_settings()
        self.start("probe", {"target": project, "verbose": self.verbose.isChecked()}, "Разведка")

    def run_rename(self):
        project = self.project_dir()
        if project is None:
            return
        part = os.path.abspath(self.part_edit.text().strip() or ".")
        des, name = self.des_edit.text().strip(), self.name_edit.text().strip()
        if not os.path.isfile(part) or not part.lower().endswith(".m3d"):
            QMessageBox.warning(self, APP_TITLE, "Выберите файл детали (.m3d).")
            return
        if os.path.relpath(part, project).startswith(".."):
            QMessageBox.warning(self, APP_TITLE, "Деталь должна лежать внутри папки тестового проекта.")
            return
        if not des or not name:
            QMessageBox.warning(self, APP_TITLE, "Заполните новое обозначение и наименование.")
            return
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            "Рядом с проектом будет создана его копия, все изменения пойдут в неё.\n"
            "Оригинал не изменится.\n\nФайлы проекта должны быть закрыты в КОМПАСе. Продолжить?",
        )
        if answer != QMessageBox.Yes:
            return
        self.save_settings()
        self.start(
            "rename",
            {"project": project, "part": part, "designation": des, "name": name},
            "Тест переобозначения",
        )

    def start(self, task, kwargs, title):
        self.set_busy(True)
        self.log.appendPlainText(f"\n########## {title} ##########")
        self.worker = Worker(task, kwargs)
        self.worker.line.connect(self.log.appendPlainText)
        self.worker.done.connect(self.finished)
        self.worker.start()

    def finished(self, report_path):
        self.set_busy(False)
        if report_path:
            self.last_report = report_path
            self.open_btn.setEnabled(True)
        self.log.appendPlainText("\nГотово.")

    def set_busy(self, busy):
        self.probe_btn.setEnabled(not busy)
        self.rename_btn.setEnabled(not busy)

    def open_report_folder(self):
        if self.last_report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.last_report)))

    def save_settings(self):
        self.settings.setValue("project", self.project_edit.text())
        self.settings.setValue("part", self.part_edit.text())
        self.settings.setValue("designation", self.des_edit.text())
        self.settings.setValue("name", self.name_edit.text())

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, APP_TITLE, "Дождитесь окончания операции.")
            event.ignore()
            return
        self.save_settings()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
