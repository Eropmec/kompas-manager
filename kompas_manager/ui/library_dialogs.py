"""Диалоги библиотеки: паспорт элемента, вставка в проект, вынос вхождений."""
import html
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kompas_manager.core.library import KINDS, Passport, plan_insert, resolve_names, save_passport
from kompas_manager.core.naming import format_number
from kompas_manager.ui.dialogs import russian_buttons


def _ro(text):
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


class PassportDialog(QDialog):
    """Паспорт элемента: тип, шаблоны, таблица типоразмеров, переменные модели."""

    def __init__(self, element, variables, model_props, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Паспорт элемента — {element.title}")
        self.resize(760, 560)
        self.element = element
        self.variables = variables
        self.reread = False
        p = element.passport or Passport()

        self.kind = QComboBox()
        for key, title in KINDS.items():
            self.kind.addItem(title, key)
        self.kind.setCurrentIndex(max(0, list(KINDS).index(p.kind) if p.kind in KINDS else 0))
        self.des_tpl = QLineEdit(p.designation_template)
        self.name_tpl = QLineEdit(p.name_template)
        des0, name0 = model_props
        if not p.designation_template and not p.name_template:
            self.des_tpl.setPlaceholderText(f"например, по модели: {des0}" if des0 else "")
            self.name_tpl.setPlaceholderText(f"например, по модели: {name0}" if name0 else "")
        self._last_tpl = self.name_tpl
        for edit in (self.des_tpl, self.name_tpl):
            edit.textChanged.connect(self._update_preview)
            edit.installEventFilter(self)
        self.table = QLineEdit(p.table)
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._pick_table)
        trow = QHBoxLayout()
        trow.addWidget(self.table, 1)
        trow.addWidget(browse)

        self.vars = QTableWidget(len(variables), 3)
        self.vars.setHorizontalHeaderLabels(["Переменная", "Значение в модели", "Комментарий"])
        self.vars.verticalHeader().setVisible(False)
        self.vars.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.vars.setSelectionBehavior(QAbstractItemView.SelectRows)
        for r, v in enumerate(variables):
            self.vars.setItem(r, 0, _ro(v.name))
            self.vars.setItem(r, 1, _ro(format_number(v.value)))
            self.vars.setItem(r, 2, _ro("вычисляемая" if v.info else (v.note or "")))
        self.vars.resizeColumnsToContents()
        self.vars.horizontalHeader().setStretchLastSection(True)
        self.vars.cellDoubleClicked.connect(self._insert_field)
        self.preview = QLabel()
        self.preview.setWordWrap(True)

        self.kind_hint = QLabel()
        self.kind_hint.setWordWrap(True)
        self.kind_hint.setStyleSheet("color: #06c;")
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

        form = QFormLayout()
        form.addRow("Тип элемента:", self.kind)
        form.addRow("", self.kind_hint)
        form.addRow("Шаблон обозначения:", self.des_tpl)
        form.addRow("Шаблон наименования:", self.name_tpl)
        form.addRow("Таблица типоразмеров:", trow)
        hint = QLabel("В шаблонах {Имя} заменяется значением переменной. Двойной щелчок по переменной "
                      "вставляет её в шаблон. Пустой шаблон — свойство остаётся как в модели. "
                      "Таблица: .xlsx, первая строка — имена переменных, далее строки типоразмеров.")
        hint.setWordWrap(True)

        reread = QPushButton("Перечитать переменные из модели")
        reread.clicked.connect(self._reread)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        russian_buttons(buttons)
        buttons.addButton(reread, QDialogButtonBox.ResetRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(QLabel("Внешние переменные модели:"))
        layout.addWidget(self.vars, 1)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self._update_preview()

    KIND_HINTS = {
        "standard": "Копия в изделии — без обозначения (если шаблон обозначения пуст), файл называется по "
                    "наименованию. Включите в шаблон наименования все размеры, которыми различаются типоразмеры, "
                    "и стандарт: «Фланец 1-{Dn}-{Pn} ГОСТ 33259».",
        "purchased": "Копия — без обозначения, файл по наименованию. В наименование включите марку или артикул "
                     "и параметры исполнения: «Кран шаровой {Dn} PN{Pn}».",
        "like_standard": "Обозначение копии — по схеме изделия: следующий свободный номер в сборке, куда вставляется "
                         "(оставьте шаблон обозначения пустым). Наименование — по шаблону: «Патрубок {D}x{s}».",
        "part": "Обозначение копии — по схеме изделия: следующий свободный номер в сборке. "
                "Шаблон обозначения оставьте пустым.",
    }

    def _kind_changed(self, *_):
        self.kind_hint.setText(self.KIND_HINTS.get(self.kind.currentData(), ""))

    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusIn and obj in (self.des_tpl, self.name_tpl):
            self._last_tpl = obj
        return False

    def _insert_field(self, row, _col):
        self._last_tpl.insert("{" + self.variables[row].name + "}")
        self._last_tpl.setFocus()

    def _pick_table(self):
        start = os.path.dirname(self.element.path)
        path, _ = QFileDialog.getOpenFileName(self, "Таблица типоразмеров", start, "Excel (*.xlsx)")
        if path:
            self.table.setText(os.path.relpath(path, start))

    def passport(self):
        return Passport(self.kind.currentData(), self.des_tpl.text().strip(), self.name_tpl.text().strip(),
                        self.table.text().strip(), list(self.variables))

    def _update_preview(self):
        from kompas_manager.core.library import Element

        des, name, problems = resolve_names(Element(self.element.path, self.passport()), {})
        text = f"Со значениями по умолчанию: <b>{html.escape(des or '—')}</b> &nbsp; <b>{html.escape(name or '—')}</b>"
        if problems:
            text += "<br><span style='color:#b00'>" + "<br>".join(html.escape(p) for p in problems) + "</span>"
        self.preview.setText(text)

    def _reread(self):
        self.reread = True
        self.reject()

    def _save(self):
        p = self.passport()
        _d, _n, problems = resolve_names(type(self.element)(self.element.path, p), {})
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        try:
            save_passport(self.element.path, p)
        except OSError as e:
            QMessageBox.warning(self, self.windowTitle(), f"Не удалось сохранить паспорт:\n{e}")
            return
        self.element.passport = p
        self.accept()


class InsertDialog(QDialog):
    """Значения переменных (вручную или строкой таблицы), папка проекта, предпросмотр."""

    def __init__(self, element, project_root, table=None, model_props=("", ""), parent=None,
                 initial_folder=".", target_title="", project_designation=""):
        super().__init__(parent)
        self.setWindowTitle(f"Вставка в проект — {element.title}")
        self.resize(980, 640)
        self.element = element
        self.project_root = project_root
        self.model_props = model_props
        self.project_designation = project_designation
        self.plan = None
        p = element.passport or Passport()
        self.vars = p.editable_variables()

        self.folder = QComboBox()
        self.folder.setEditable(True)
        self.folder.addItem(".")
        for dirpath, dirs, _files in os.walk(project_root):
            dirs[:] = sorted(d for d in dirs if not d.startswith(("_", ".")))
            if dirpath != project_root:
                self.folder.addItem(os.path.relpath(dirpath, project_root))
        self.folder.setCurrentText(initial_folder)
        self.folder.currentTextChanged.connect(self._update)
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._pick_folder)
        frow = QHBoxLayout()
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)

        self.values = QTableWidget(len(self.vars), 4)
        self.values.setHorizontalHeaderLabels(["Переменная", "Значение", "В модели", "Комментарий"])
        self.values.verticalHeader().setVisible(False)
        self.values.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for r, v in enumerate(self.vars):
            self.values.setItem(r, 0, _ro(v.name))
            self.values.setItem(r, 1, QTableWidgetItem(""))
            self.values.setItem(r, 2, _ro(format_number(v.value)))
            self.values.setItem(r, 3, _ro(v.note or ""))
        self.values.itemChanged.connect(self._update)

        self.rows_widget = None
        self.table_rows = []
        if table:
            header, rows = table
            self.table_rows = rows
            self.rows_filter = QLineEdit()
            self.rows_filter.setPlaceholderText("Фильтр строк таблицы")
            self.rows_filter.setClearButtonEnabled(True)
            self.rows_filter.textChanged.connect(self._filter_rows)
            self.rows = QTableWidget(len(rows), len(header))
            self.rows.setHorizontalHeaderLabels(header)
            self.rows.verticalHeader().setVisible(False)
            self.rows.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.rows.setSelectionMode(QAbstractItemView.SingleSelection)
            self.rows.setEditTriggers(QAbstractItemView.NoEditTriggers)
            for r, row in enumerate(rows):
                for c, h in enumerate(header):
                    self.rows.setItem(r, c, QTableWidgetItem(format_number(row.get(h)) if row.get(h) is not None else ""))
            self.rows.resizeColumnsToContents()
            self.rows.horizontalHeader().setStretchLastSection(True)
            self.rows.itemSelectionChanged.connect(self._row_selected)
            self.rows_widget = QWidget()
            rl = QVBoxLayout(self.rows_widget)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(QLabel("Типоразмер из таблицы:"))
            rl.addWidget(self.rows_filter)
            rl.addWidget(self.rows, 1)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)

        values_box = QWidget()
        vl = QVBoxLayout(values_box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(QLabel("Значения переменных (пусто — как в модели):"))
        vl.addWidget(self.values, 1)
        if self.rows_widget is not None:
            split = QSplitter(Qt.Vertical)
            split.addWidget(self.rows_widget)
            split.addWidget(values_box)
            split.setStretchFactor(0, 3)
            split.setStretchFactor(1, 2)
            middle = split
        else:
            middle = values_box

        form = QFormLayout()
        if target_title:
            form.addRow("Вставить в сборку:", QLabel(f"<b>{html.escape(target_title)}</b>"))
        form.addRow("Папка в проекте:", frow)
        from PySide6.QtWidgets import QSpinBox

        self.count = QSpinBox()
        self.count.setRange(1, 999)
        if target_title:
            form.addRow("Количество:", self.count)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        russian_buttons(buttons)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        self.ok.setText("Вставить")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(middle, 1)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self._update()

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Папка в проекте", self.project_root)
        if path:
            rel = os.path.relpath(path, self.project_root)
            if rel.startswith(".."):
                QMessageBox.warning(self, self.windowTitle(), "Папка должна быть внутри проекта.")
                return
            self.folder.setCurrentText(rel)

    def _filter_rows(self, text):
        text = text.strip().lower()
        for r in range(self.rows.rowCount()):
            cells = " ".join(self.rows.item(r, c).text() for c in range(self.rows.columnCount())).lower()
            self.rows.setRowHidden(r, bool(text) and text not in cells)

    def _row_selected(self):
        sel = self.rows.selectionModel().selectedRows()
        if not sel:
            return
        row = self.table_rows[sel[0].row()]
        self.values.blockSignals(True)
        for r, v in enumerate(self.vars):
            if v.name in row and row[v.name] is not None:
                self.values.item(r, 1).setText(format_number(row[v.name]))
        self.values.blockSignals(False)
        self._update()

    def entered_values(self):
        return {v.name: self.values.item(r, 1).text().strip()
                for r, v in enumerate(self.vars) if self.values.item(r, 1).text().strip()}

    def target_dir(self):
        rel = self.folder.currentText().strip() or "."
        return os.path.normpath(os.path.join(self.project_root, rel))

    def _update(self, *_):
        self.plan = plan_insert(self.element, self.entered_values(), self.target_dir(), *self.model_props,
                                project_designation=self.project_designation)
        p = self.plan
        lines = [
            f"Обозначение: <b>{html.escape(p.designation or '—')}</b> &nbsp; Наименование: <b>{html.escape(p.name or '—')}</b>",
            f"Файл: <b>{html.escape(os.path.relpath(p.target, self.project_root))}</b>",
        ]
        if p.reuse:
            lines.append("<span style='color:#06c'>Такой файл уже есть в проекте — копия не создаётся, используется он.</span>")
        if p.problems:
            lines.append("<span style='color:#b00'>" + "<br>".join(html.escape(x) for x in p.problems) + "</span>")
        self.preview.setText("<br>".join(lines))
        blocking = [x for x in p.problems if x.startswith(("Нет внешней", "Копия совпадает"))]
        inside = not os.path.relpath(self.target_dir(), self.project_root).startswith("..")
        self.ok.setEnabled(not blocking and inside)

    def _accept(self):
        if not os.path.isdir(self.target_dir()):
            answer = QMessageBox.question(self, self.windowTitle(), f"Папки нет. Создать?\n{self.target_dir()}")
            if answer != QMessageBox.Yes:
                return
            os.makedirs(self.target_dir())
            self._update()
        self.accept()


class ExtractDialog(QDialog):
    def __init__(self, groups, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вынос вхождений в отдельные файлы")
        self.resize(980, 420)
        tree = QTreeWidget()
        tree.setRootIsDecorated(False)
        tree.setHeaderLabels(["Исходный файл", "Изменено в сборке", "Вхождений", "Новый файл"])
        for g in groups:
            values = ", ".join(f"{k}={format_number(v)}" for k, v in g.values.items())
            target = os.path.basename(g.target) + (" (уже есть)" if g.reuse else "")
            tree.addTopLevelItem(QTreeWidgetItem([os.path.basename(g.source), values, str(len(g.instances)), target]))
        for c in range(4):
            tree.resizeColumnToContents(c)
        note = QLabel(
            "Для каждого набора значений создаётся копия модели в папке сборки с этими значениями "
            "в переменных самой копии, и вхождения перепривязываются к ней. После этого по копиям можно "
            "делать чертежи. Сборка перед изменением копируется в _backup."
        )
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        russian_buttons(buttons)
        buttons.button(QDialogButtonBox.Ok).setText("Вынести")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tree, 1)
        layout.addWidget(note)
        layout.addWidget(buttons)
