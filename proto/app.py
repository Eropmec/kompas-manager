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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from naming import file_name

APP_TITLE = "КОМПАС: прототип"


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
            elif self.task.startswith("proj_"):
                import copy_test

                func = getattr(copy_test, "run_" + self.task[5:])
                report_path = func(on_line=self.line.emit, **self.kwargs)
            elif self.task.startswith("lib_"):
                import lib_test

                func = getattr(lib_test, "run_" + self.task[4:])
                report_path = func(on_line=self.line.emit, **self.kwargs)
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
        root_layout = QVBoxLayout(central)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)
        tab1 = QWidget()
        layout = QVBoxLayout(tab1)
        self.tabs.addTab(tab1, "Переобозначение")

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
        layout.addStretch(1)
        self.tabs.addTab(self._build_library_tab(), "Библиотека")
        self.tabs.addTab(self._build_projects_tab(), "Проекты")
        self.tabs.setCurrentIndex(2)
        layout = root_layout

        # --- Общая настройка
        self.show_kompas = QCheckBox(
            "Показывать окно КОМПАСа во время работы "
            "(если КОМПАС уже открыт, используется он и окно не прячется)"
        )
        self.show_kompas.setChecked(self.settings.value("show_kompas", False, type=bool))
        layout.addWidget(self.show_kompas)

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

    # ---------- вкладка «Библиотека» ----------

    def _path_row(self, grid, row, label, key, pick):
        edit = QLineEdit(self.settings.value(key, ""))
        btn = QPushButton("Обзор…")
        btn.clicked.connect(lambda: pick(edit))
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(edit, row, 1)
        grid.addWidget(btn, row, 2)
        return edit

    def _pick_dir(self, edit):
        path = QFileDialog.getExistingDirectory(self, "Папка", edit.text() or os.path.expanduser("~"))
        if path:
            edit.setText(os.path.normpath(path))

    def _pick_file(self, edit, flt):
        start = edit.text() or self.lib_dir.text() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Файл", start, flt)
        if path:
            edit.setText(os.path.normpath(path))

    def _build_library_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        g1 = QGroupBox("1. Модели библиотеки и их внешние переменные (только чтение)")
        l1 = QGridLayout(g1)
        self.lib_dir = self._path_row(l1, 0, "Папка библиотеки:", "lib_dir", self._pick_dir)
        if not self.lib_dir.text():
            self.lib_dir.setText(r"D:\Облако\YandexDisk\Progs\KMPS-SET-SMP\Lib")
        self.lib_scan_btn = QPushButton("Показать переменные моделей")
        self.lib_scan_btn.clicked.connect(self.run_lib_scan)
        l1.addWidget(self.lib_scan_btn, 1, 1)
        layout.addWidget(g1)

        g2 = QGroupBox("2. Вставка копии в проект с новыми значениями (оригинал не меняется)")
        l2 = QGridLayout(g2)
        self.lib_model = self._path_row(l2, 0, "Модель из библиотеки:", "lib_model",
                                        lambda e: self._pick_file(e, "Модели КОМПАС (*.m3d *.a3d)"))
        self.lib_target = self._path_row(l2, 1, "Папка проекта:", "lib_target", self._pick_dir)
        self.lib_values = QLineEdit(self.settings.value("lib_values", "D=800; s=8"))
        self.lib_des_tpl = QLineEdit(self.settings.value("lib_des_tpl", "BTEL.D{D}S{s}"))
        self.lib_name_tpl = QLineEdit(self.settings.value("lib_name_tpl", "Днище эллиптическое {ISP}-{D}-{s}"))
        self.lib_preview = QLabel()
        l2.addWidget(QLabel("Значения переменных:"), 2, 0)
        l2.addWidget(self.lib_values, 2, 1)
        l2.addWidget(QLabel("Шаблон обозначения:"), 3, 0)
        l2.addWidget(self.lib_des_tpl, 3, 1)
        l2.addWidget(QLabel("Шаблон наименования:"), 4, 0)
        l2.addWidget(self.lib_name_tpl, 4, 1)
        hint = QLabel("В шаблонах {Имя} заменяется значением переменной. Пустой шаблон — свойство не меняется.")
        hint.setWordWrap(True)
        l2.addWidget(hint, 5, 1)
        self.lib_insert_btn = QPushButton("Вставить копию в проект")
        self.lib_insert_btn.clicked.connect(self.run_lib_insert)
        l2.addWidget(self.lib_insert_btn, 6, 1)
        layout.addWidget(g2)

        g3 = QGroupBox("3. Переменные, изменённые в сборке на уровне вхождения (только чтение)")
        l3 = QGridLayout(g3)
        self.lib_asm = self._path_row(l3, 0, "Сборка (.a3d):", "lib_asm",
                                      lambda e: self._pick_file(e, "Сборки КОМПАС (*.a3d)"))
        self.lib_inst_btn = QPushButton("Сравнить переменные вхождений")
        self.lib_inst_btn.clicked.connect(self.run_lib_instances)
        l3.addWidget(self.lib_inst_btn, 1, 1)
        layout.addWidget(g3)
        layout.addStretch(1)
        return tab

    def _build_projects_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        g1 = QGroupBox("1. Копирование папки проекта: куда ведут ссылки копии и перепривязка (оригинал не меняется)")
        l1 = QGridLayout(g1)
        self.proj_copy_src = self._path_row(l1, 0, "Папка тестового проекта:", "proj_copy_src", self._pick_dir)
        note = QLabel("Рядом создаётся копия папки с суффиксом _copytest и датой. Все проверки и перепривязка — только в копии.")
        note.setWordWrap(True)
        l1.addWidget(note, 1, 1)
        self.proj_copy_btn = QPushButton("Скопировать и проверить ссылки")
        self.proj_copy_btn.clicked.connect(self.run_proj_copy)
        l1.addWidget(self.proj_copy_btn, 2, 1)
        layout.addWidget(g1)

        g2 = QGroupBox("2. Создание структуры: сборка и две детали, вставка компонентов")
        l2 = QGridLayout(g2)
        self.proj_struct_dir = self._path_row(l2, 0, "Папка для теста:", "proj_struct_dir", self._pick_dir)
        self.proj_part_tpl = self._path_row(l2, 1, "Шаблон детали (необяз.):", "proj_part_tpl",
                                            lambda e: self._pick_file(e, "Детали КОМПАС (*.m3d)"))
        self.proj_asm_tpl = self._path_row(l2, 2, "Шаблон сборки (необяз.):", "proj_asm_tpl",
                                           lambda e: self._pick_file(e, "Сборки КОМПАС (*.a3d)"))
        note2 = QLabel("Без шаблонов создаются стандартные пустые документы КОМПАСа. "
                       "Тест создаёт подпапку «Структура» с датой и файлами ТЕСТ.000.00 - Сборка, ТЕСТ.000.01 - Корпус, ТЕСТ.000.02 - Крышка.")
        note2.setWordWrap(True)
        l2.addWidget(note2, 3, 1)
        self.proj_struct_btn = QPushButton("Создать структуру")
        self.proj_struct_btn.clicked.connect(self.run_proj_structure)
        l2.addWidget(self.proj_struct_btn, 4, 1)
        layout.addWidget(g2)
        layout.addStretch(1)
        return tab

    def run_proj_copy(self):
        src = self.proj_copy_src.text().strip()
        if not os.path.isdir(src):
            QMessageBox.warning(self, APP_TITLE, "Укажите существующую папку тестового проекта.")
            return
        self.save_settings()
        self.start("proj_copy", {"project": src, "show": self.show_kompas.isChecked()}, "Копирование проекта")

    def run_proj_structure(self):
        folder = self.proj_struct_dir.text().strip()
        if not os.path.isdir(folder):
            QMessageBox.warning(self, APP_TITLE, "Укажите существующую папку для теста.")
            return
        for edit in (self.proj_part_tpl, self.proj_asm_tpl):
            if edit.text().strip() and not os.path.isfile(edit.text().strip()):
                QMessageBox.warning(self, APP_TITLE, f"Файл шаблона не найден:\n{edit.text()}")
                return
        self.save_settings()
        self.start("proj_structure", {"folder": folder, "part_template": self.proj_part_tpl.text().strip(),
                                      "asm_template": self.proj_asm_tpl.text().strip(),
                                      "show": self.show_kompas.isChecked()}, "Создание структуры")

    def run_lib_scan(self):
        folder = self.lib_dir.text().strip()
        if not os.path.isdir(folder):
            QMessageBox.warning(self, APP_TITLE, "Укажите существующую папку библиотеки.")
            return
        self.save_settings()
        self.start("lib_scan", {"folder": folder, "verbose": self.verbose.isChecked(),
                                "show": self.show_kompas.isChecked()}, "Переменные библиотеки")

    def run_lib_insert(self):
        model, target = self.lib_model.text().strip(), self.lib_target.text().strip()
        if not os.path.isfile(model):
            QMessageBox.warning(self, APP_TITLE, "Выберите модель из библиотеки.")
            return
        if not os.path.isdir(target):
            QMessageBox.warning(self, APP_TITLE, "Укажите существующую папку проекта.")
            return
        if os.path.normcase(os.path.dirname(os.path.abspath(model))) == os.path.normcase(os.path.abspath(target)):
            QMessageBox.warning(self, APP_TITLE, "Папка проекта не должна совпадать с папкой модели в библиотеке.")
            return
        try:
            from naming import parse_values

            parse_values(self.lib_values.text())
        except ValueError as e:
            QMessageBox.warning(self, APP_TITLE, str(e))
            return
        self.save_settings()
        self.start("lib_insert", {
            "model": model, "target_dir": target, "values_text": self.lib_values.text(),
            "des_template": self.lib_des_tpl.text().strip(), "name_template": self.lib_name_tpl.text().strip(),
            "show": self.show_kompas.isChecked()}, "Вставка копии")

    def run_lib_instances(self):
        asm = self.lib_asm.text().strip()
        if not os.path.isfile(asm) or not asm.lower().endswith(".a3d"):
            QMessageBox.warning(self, APP_TITLE, "Выберите файл сборки (.a3d).")
            return
        self.save_settings()
        self.start("lib_instances", {"assembly": asm, "show": self.show_kompas.isChecked()}, "Переменные вхождений")

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
        self.start("probe", {"target": project, "verbose": self.verbose.isChecked(), "show": self.show_kompas.isChecked()}, "Разведка")

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
            {
                "project": project,
                "part": part,
                "designation": des,
                "name": name,
                "show": self.show_kompas.isChecked(),
            },
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
        for btn in (self.probe_btn, self.rename_btn, self.lib_scan_btn, self.lib_insert_btn, self.lib_inst_btn,
                    self.proj_copy_btn, self.proj_struct_btn):
            btn.setEnabled(not busy)

    def open_report_folder(self):
        if self.last_report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.last_report)))

    def save_settings(self):
        self.settings.setValue("project", self.project_edit.text())
        self.settings.setValue("part", self.part_edit.text())
        self.settings.setValue("designation", self.des_edit.text())
        self.settings.setValue("name", self.name_edit.text())
        self.settings.setValue("show_kompas", self.show_kompas.isChecked())
        self.settings.setValue("tab", self.tabs.currentIndex())
        for key in ("lib_dir", "lib_model", "lib_target", "lib_values", "lib_des_tpl", "lib_name_tpl", "lib_asm",
                    "proj_copy_src", "proj_struct_dir", "proj_part_tpl", "proj_asm_tpl"):
            self.settings.setValue(key, getattr(self, key).text())

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
