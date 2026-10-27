"""Диалоги переобозначения: схемы, поиск и замена, план изменений."""
import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from kompas_manager.core.model import ERROR, KIND_TITLES, SEVERITY_TITLES
from kompas_manager.core.schemes import Scheme, load_library, save_library

TEMPLATE_HELP = (
    "Поля шаблона: <b>{код}</b> — постоянная часть из настроек проекта; "
    "<b>{сборка:3}</b> — номер сборки, дополняется нулями до 3 знаков; "
    "<b>{деталь:2}</b> — номер детали в сборке, до 2 знаков. "
    "Остальной текст (точки, дефисы, буквы) переносится как есть."
)


def scheme_examples(scheme, code):
    if scheme.validate():
        return "—"
    return (
        f"головная сборка: {scheme.format(code, 0, 0)}<br>"
        f"подсборка: {scheme.format(code, 1, 0)}<br>"
        f"деталь в подсборке: {scheme.format(code, 1, 1)}<br>"
        f"деталь в головной сборке: {scheme.format(code, 0, 1)}"
    )


def russian_buttons(box):
    names = {
        QDialogButtonBox.Ok: "ОК",
        QDialogButtonBox.Cancel: "Отмена",
        QDialogButtonBox.Save: "Сохранить",
    }
    for role, text in names.items():
        button = box.button(role)
        if button is not None and button.text() in ("OK", "Cancel", "Save", "&OK", "&Cancel", "&Save"):
            button.setText(text)
    return box


class SchemeLibraryDialog(QDialog):
    """Библиотека схем: общая для всех проектов."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Библиотека схем обозначения")
        self.resize(720, 380)
        self.schemes = [copy.copy(s) for s in load_library()]

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        add = QPushButton("Добавить")
        add.clicked.connect(self._add)
        remove = QPushButton("Удалить")
        remove.clicked.connect(self._remove)

        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        btns = QHBoxLayout()
        btns.addWidget(add)
        btns.addWidget(remove)
        left.addLayout(btns)

        self.name = QLineEdit()
        self.template = QLineEdit()
        self.name.textEdited.connect(self._edited)
        self.template.textEdited.connect(self._edited)
        help_label = QLabel(TEMPLATE_HELP)
        help_label.setWordWrap(True)
        self.preview = QLabel()
        self.errors = QLabel()
        self.errors.setStyleSheet("color: #b00;")

        form = QFormLayout()
        form.addRow("Название:", self.name)
        form.addRow("Шаблон:", self.template)
        form.addRow("", help_label)
        form.addRow("Пример (код АБВГ):", self.preview)
        form.addRow("", self.errors)

        top = QHBoxLayout()
        top.addLayout(left, 1)
        top.addLayout(form, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)

        russian_buttons(buttons)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(buttons)
        self._fill()

    def _fill(self, row=0):
        self.list.clear()
        for s in self.schemes:
            self.list.addItem(s.name or "(без названия)")
        self.list.setCurrentRow(min(row, len(self.schemes) - 1))

    def _select(self, row):
        enabled = 0 <= row < len(self.schemes)
        self.name.setEnabled(enabled)
        self.template.setEnabled(enabled)
        if enabled:
            s = self.schemes[row]
            self.name.setText(s.name)
            self.template.setText(s.template)
        self._update_preview()

    def _edited(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.schemes):
            self.schemes[row] = Scheme(self.name.text(), self.template.text())
            self.list.item(row).setText(self.name.text() or "(без названия)")
        self._update_preview()

    def _update_preview(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self.schemes)):
            self.preview.setText("")
            self.errors.setText("")
            return
        s = self.schemes[row]
        self.preview.setText(scheme_examples(s, "АБВГ"))
        self.errors.setText("<br>".join(s.validate()))

    def _add(self):
        self.schemes.append(Scheme("Новая схема", "{код}.{сборка:3}.{деталь:2}"))
        self._fill(len(self.schemes) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.schemes) and len(self.schemes) > 1:
            del self.schemes[row]
            self._fill(row)

    def _save(self):
        for s in self.schemes:
            errors = s.validate()
            if errors:
                QMessageBox.warning(self, self.windowTitle(), f"Схема «{s.name}»:\n" + "\n".join(errors))
                return
        save_library(self.schemes)
        self.accept()


class ProjectSchemeDialog(QDialog):
    """Схема обозначения и код для текущего проекта."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Схема обозначения проекта")
        self.resize(640, 300)
        self.settings = settings

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._update_preview)
        lib_btn = QPushButton("Библиотека схем…")
        lib_btn.clicked.connect(self._edit_library)
        row = QHBoxLayout()
        row.addWidget(self.combo, 1)
        row.addWidget(lib_btn)

        self.code = QLineEdit(settings.code)
        self.code.textEdited.connect(self._update_preview)
        self.template_label = QLabel()
        self.preview = QLabel()

        form = QFormLayout()
        form.addRow("Схема:", row)
        form.addRow("Шаблон:", self.template_label)
        form.addRow("Код проекта {код}:", self.code)
        form.addRow("Пример:", self.preview)
        note = QLabel(
            "Номера сборок и деталей программа рассчитывает по дереву проекта. "
            "Отдельный номер можно закрепить через правую кнопку мыши в дереве."
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        russian_buttons(buttons)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch(1)
        layout.addWidget(buttons)
        self._fill_combo()

    def _fill_combo(self):
        self.schemes = load_library()
        current = self.settings.scheme
        if not any(s.template == current.template for s in self.schemes):
            self.schemes.insert(0, Scheme(f"{current.name} (из проекта)", current.template))
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in self.schemes:
            self.combo.addItem(s.name)
        idx = next((i for i, s in enumerate(self.schemes) if s.template == current.template), 0)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self._update_preview()

    def _scheme(self):
        return self.schemes[self.combo.currentIndex()]

    def _update_preview(self):
        s = self._scheme()
        self.template_label.setText(s.template)
        self.preview.setText(scheme_examples(s, self.code.text().strip()))

    def _edit_library(self):
        if SchemeLibraryDialog(self).exec():
            self._fill_combo()

    def _accept(self):
        s = self._scheme()
        if s.validate():
            QMessageBox.warning(self, self.windowTitle(), "\n".join(s.validate()))
            return
        if "{код" in s.template and not self.code.text().strip():
            QMessageBox.warning(self, self.windowTitle(), "Укажите код проекта.")
            return
        self.settings.scheme = Scheme(s.name.replace(" (из проекта)", ""), s.template)
        self.settings.code = self.code.text().strip()
        self.accept()


class FindReplaceDialog(QDialog):
    def __init__(self, has_selection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Найти и заменить")
        self.field = QComboBox()
        self.field.addItem("Наименование", "name")
        self.field.addItem("Обозначение", "designation")
        self.find = QLineEdit()
        self.repl = QLineEdit()
        self.case = QCheckBox("Учитывать регистр")
        self.scope_all = QRadioButton("Во всём проекте")
        self.scope_sel = QRadioButton("В выделенной сборке и её составе")
        self.scope_all.setChecked(True)
        self.scope_sel.setEnabled(has_selection)

        form = QFormLayout()
        form.addRow("Где:", self.field)
        form.addRow("Найти:", self.find)
        form.addRow("Заменить на:", self.repl)
        form.addRow("", self.case)
        form.addRow("Область:", self.scope_all)
        form.addRow("", self.scope_sel)
        note = QLabel("Изменения попадут в список ожидающих; в файлы они запишутся при переобозначении.")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        russian_buttons(buttons)
        buttons.button(QDialogButtonBox.Ok).setText("Заменить")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.find.text():
            QMessageBox.warning(self, self.windowTitle(), "Введите текст для поиска.")
            return
        self.accept()

    def values(self):
        return {
            "field": self.field.currentData(),
            "find": self.find.text(),
            "repl": self.repl.text(),
            "case": self.case.isChecked(),
            "selection": self.scope_sel.isChecked(),
        }


class PlanDialog(QDialog):
    """Таблица «было → стало» и проверки перед переобозначением."""

    def __init__(self, plan, project, style, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Переобозначение: проверьте изменения")
        self.resize(1200, 620)
        renamed = sum(1 for o in plan.ops if o.renamed)
        relinked = sum(1 for o in plan.ops if o.relink)

        summary = QLabel(
            f"Затронуто файлов: <b>{len(plan.ops)}</b>; переименовывается: <b>{renamed}</b>; "
            f"обновляются ссылки в <b>{relinked}</b>."
        )

        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setHeaderLabels([
            "Тип", "Обозначение: было", "стало", "Наименование: было", "стало",
            "Файл: было", "стало", "Обновить ссылки",
        ])
        for op in plan.ops:
            changed = op.retitle
            item = QTreeWidgetItem([
                KIND_TITLES.get(op.kind, op.kind),
                op.old_designation,
                op.new_designation if changed else "",
                op.old_name,
                op.new_name if changed else "",
                project.display_path(op.key),
                os.path.basename(op.new_path) if op.renamed else "",
                str(len(op.relink)) if op.relink else "",
            ])
            for col, before in ((2, 1), (4, 3), (6, 5)):
                if item.text(col) and item.text(col) != os.path.basename(item.text(before)):
                    font = item.font(col)
                    font.setBold(True)
                    item.setFont(col, font)
            self.table.addTopLevelItem(item)
        for col in range(8):
            self.table.resizeColumnToContents(col)
        self.table.header().setSectionResizeMode(QHeaderView.Interactive)

        self.issues = QTreeWidget()
        self.issues.setRootIsDecorated(False)
        self.issues.setHeaderLabels(["Уровень", "Проблема", "Файл"])
        self.issues.header().setSectionResizeMode(1, QHeaderView.Stretch)
        from kompas_manager.ui.project_tree import severity_icon

        for i in plan.issues:
            item = QTreeWidgetItem([SEVERITY_TITLES[i.severity], i.message, project.display_path(i.key)])
            item.setIcon(0, severity_icon(style, i.severity))
            self.issues.addTopLevelItem(item)
        self.issues.setVisible(bool(plan.issues))
        self.issues.setMaximumHeight(160)

        note = QLabel(
            "Перед изменениями все затронутые файлы копируются в папку <b>_backup</b> проекта; "
            "откат — «Обозначения → Откатить последнее переобозначение». "
            "Закройте эти файлы в КОМПАСе. Если проект в облачной папке, "
            "на время переобозначения лучше приостановить синхронизацию."
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        russian_buttons(buttons)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText("Переобозначить")
        errors = [i for i in plan.issues if i.severity == ERROR]
        ok.setEnabled(not errors and bool(plan.ops))
        if errors:
            note.setText(f"<span style='color:#b00'>Есть ошибки ({len(errors)}): исправьте их, "
                         "иначе переобозначение невозможно.</span><br>" + note.text())
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.issues)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.table.setFocus(Qt.OtherFocusReason)


class SettingsDialog(QDialog):
    """Общие настройки: шаблоны новых деталей и сборок."""

    def __init__(self, qsettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.resize(640, 180)
        self.q = qsettings
        self.edits = {}
        form = QFormLayout()
        for key, label, flt in (("template_part", "Шаблон детали:", "Детали КОМПАС (*.m3d)"),
                                ("template_asm", "Шаблон сборки:", "Сборки КОМПАС (*.a3d)")):
            edit = QLineEdit(self.q.value(key, ""))
            edit.setPlaceholderText("пусто — стандартный пустой документ КОМПАСа")
            btn = QPushButton("Обзор…")
            btn.clicked.connect(lambda _=False, e=edit, f=flt: self._pick(e, f))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(btn)
            form.addRow(label, row)
            self.edits[key] = edit
        note = QLabel("Шаблоны используются при создании файлов новой структуры изделия. "
                      "Обозначение и наименование программа задаёт сама.")
        note.setWordWrap(True)
        buttons = russian_buttons(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _pick(self, edit, flt):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "Шаблон", edit.text() or os.path.expanduser("~"), flt)
        if path:
            edit.setText(os.path.normpath(path))

    def _save(self):
        for key, edit in self.edits.items():
            path = edit.text().strip()
            if path and not os.path.isfile(path):
                QMessageBox.warning(self, self.windowTitle(), f"Файл не найден:\n{path}")
                return
            self.q.setValue(key, path)
        self.accept()


class LevelUpDialog(QDialog):
    """Обозначение и наименование новой головной сборки над изделием."""

    def __init__(self, head_doc, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать уровень выше")
        self.resize(520, 200)
        self.des = QLineEdit()
        self.name = QLineEdit()
        self.des.setPlaceholderText("например, " + settings.scheme.format(settings.code, 100, 0)
                                    if not settings.scheme.validate() else "")
        form = QFormLayout()
        form.addRow("Обозначение новой сборки:", self.des)
        form.addRow("Наименование:", self.name)
        note = QLabel(f"Будет создана новая головная сборка, в неё вставляется «{head_doc.designation} "
                      f"{head_doc.name}» без изменений. Файл — в папке изделия.")
        note.setWordWrap(True)
        buttons = russian_buttons(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        buttons.button(QDialogButtonBox.Ok).setText("Создать")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.des.text().strip() or not self.name.text().strip():
            QMessageBox.warning(self, self.windowTitle(), "Заполните обозначение и наименование.")
            return
        self.accept()

    def values(self):
        return self.des.text().strip(), self.name.text().strip()


class GroupEditDialog(QDialog):
    """Изменить наименования и обозначения нескольких выделенных элементов сразу."""

    MODES = [("keep", "Не менять"), ("replace", "Заменить текст"), ("prefix", "Добавить в начало"),
             ("suffix", "Добавить в конец"), ("set", "Задать одинаковое")]

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Изменить выделенные ({len(values)})")
        self.resize(760, 520)
        self.values = values
        self.mode = QComboBox()
        for key, title in self.MODES:
            self.mode.addItem(title, key)
        self.name_find = QLineEdit()
        self.name_find.setPlaceholderText("что заменить")
        self.name_text = QLineEdit()
        self.name_text.setPlaceholderText("новый текст")
        self.des_find = QLineEdit()
        self.des_find.setPlaceholderText("что заменить в обозначении")
        self.des_repl = QLineEdit()
        self.des_repl.setPlaceholderText("на что")
        self.case = QCheckBox("Учитывать регистр")
        form = QFormLayout()
        form.addRow("Наименование:", self.mode)
        form.addRow("Найти:", self.name_find)
        form.addRow("Текст:", self.name_text)
        form.addRow("Обозначение — найти:", self.des_find)
        form.addRow("Обозначение — заменить на:", self.des_repl)
        form.addRow("", self.case)
        self.preview = QTreeWidget()
        self.preview.setRootIsDecorated(False)
        self.preview.setHeaderLabels(["Обозначение", "Наименование", "Станет: обозначение", "Станет: наименование"])
        for w in (self.mode, self.name_find, self.name_text, self.des_find, self.des_repl, self.case):
            (w.currentIndexChanged if isinstance(w, QComboBox) else
             w.toggled if isinstance(w, QCheckBox) else w.textChanged).connect(self._update)
        buttons = russian_buttons(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        buttons.button(QDialogButtonBox.Ok).setText("Применить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview, 1)
        note = QLabel("Изменения попадут в ожидающие (синим); в файлы они запишутся при «Переобозначить».")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self._update()

    def result_values(self):
        from kompas_manager.core.bulk import group_edit

        return group_edit(self.values, self.mode.currentData(), self.name_text.text(), self.name_find.text(),
                          self.des_find.text(), self.des_repl.text(), self.case.isChecked())

    def _update(self, *_):
        mode = self.mode.currentData()
        self.name_find.setEnabled(mode == "replace")
        self.name_text.setEnabled(mode != "keep")
        self.preview.clear()
        new = self.result_values()
        for k, (des, name) in self.values.items():
            nd, nn = new[k]
            it = QTreeWidgetItem([des, name, nd if nd != des else "", nn if nn != name else ""])
            for c in (2, 3):
                f = it.font(c)
                f.setBold(True)
                it.setFont(c, f)
            self.preview.addTopLevelItem(it)
        for c in range(4):
            self.preview.resizeColumnToContents(c)
