"""Модель дерева проекта для QTreeView.

Обозначение и наименование моделей можно править прямо в дереве. Изменения не пишутся
в файлы сразу, а копятся в «ожидающих изменениях» (pending) и показываются выделенными.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle

from kompas_manager.core.model import ERROR, INFO, KIND_TITLES, SEVERITY_TITLES, WARNING

COLUMNS = ["Обозначение", "Наименование", "Тип", "Кол.", "Документы", "Файл", "Состояние"]
COL_DES, COL_NAME, COL_STATE = 0, 1, 6

KEY_ROLE = Qt.UserRole + 1

SEVERITY_ICONS = {
    ERROR: QStyle.SP_MessageBoxCritical,
    WARNING: QStyle.SP_MessageBoxWarning,
    INFO: QStyle.SP_MessageBoxInformation,
}

CHANGED_COLOR = QColor(20, 90, 200)
MUTED_COLOR = QColor(130, 130, 130)


def severity_icon(style, severity):
    return style.standardIcon(SEVERITY_ICONS[severity])


class ProjectTreeBuilder:
    def __init__(self, project, style, pending=None, settings=None):
        self.project = project
        self.style = style
        self.pending = pending if pending is not None else {}
        self.settings = settings
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.items_by_key = {}  # ключ -> первые ячейки строк
        self.rows_by_key = {}  # ключ -> все строки (списки ячеек), где показан файл

    def editable(self, key):
        d = self.project.doc(key)
        return d is not None and d.kind in ("part", "assembly") and self.project.inside(key) and not d.error

    def build(self):
        p = self.project
        root = self.model.invisibleRootItem()
        for key in p.roots():
            row = self._row(key, 1)
            root.appendRow(row)
            self._add_children(row[0], key, {key})

        loose = p.loose_parts()
        if loose:
            group = self._group(f"Детали вне сборок ({len(loose)})")
            root.appendRow(group)
            for key in loose:
                group[0].appendRow(self._row(key, 1))

        unlinked = p.unlinked_documents()
        if unlinked:
            group = self._group(f"Чертежи и спецификации без модели в проекте ({len(unlinked)})")
            root.appendRow(group)
            for key in unlinked:
                group[0].appendRow(self._row(key, 1))
        return self.model

    def _add_children(self, parent, key, stack):
        for child, count in self.project.components.get(key, []):
            row = self._row(child, count)
            parent.appendRow(row)
            if child in stack:
                row[COL_STATE].setText("циклическая ссылка")
                continue
            d = self.project.doc(child)
            if d is not None and d.kind == "assembly":
                self._add_children(row[0], child, stack | {child})

    def _group(self, title):
        item = QStandardItem(title)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        row = [item] + [QStandardItem("") for _ in COLUMNS[1:]]
        for cell in row:
            cell.setEditable(False)
        return row

    def _row(self, key, count):
        p = self.project
        d = p.doc(key)
        cells = [QStandardItem("") for _ in COLUMNS]
        for cell in cells:
            cell.setEditable(False)
        cells[0].setData(key, KEY_ROLE)
        cells[3].setText(str(count) if count > 1 else "")
        cells[3].setTextAlignment(Qt.AlignCenter)
        cells[5].setText(p.display_path(key))

        if d is None:
            cells[1].setText(os.path.basename(p.raw_paths.get(key, key)))
            cells[2].setText("—")
            cells[COL_STATE].setText("файл не найден")
            cells[COL_STATE].setIcon(severity_icon(self.style, ERROR))
            red = QBrush(QColor(190, 30, 30))
            for cell in cells:
                cell.setForeground(red)
        else:
            cells[2].setText(KIND_TITLES.get(d.kind, d.kind))
            cells[4].setText(self._documents_text(key))
            if self.editable(key):
                cells[COL_DES].setEditable(True)
                cells[COL_NAME].setEditable(True)
            if not p.inside(key):
                for cell in cells:
                    cell.setForeground(QBrush(MUTED_COLOR))

        self.items_by_key.setdefault(key, []).append(cells[0])
        self.rows_by_key.setdefault(key, []).append(cells)
        self.refresh_row(cells, key)
        return cells

    def refresh_row(self, cells, key):
        """Показать значения с учётом ожидающих изменений и состояние строки."""
        p = self.project
        d = p.doc(key)
        if d is None:
            return
        des, name = self.pending.get(key, (d.designation, d.name))
        cells[COL_DES].setText(des)
        cells[COL_NAME].setText(name)
        for col, new, old in ((COL_DES, des, d.designation), (COL_NAME, name, d.name)):
            font = cells[col].font()
            changed = new != old
            font.setBold(changed)
            cells[col].setFont(font)
            if changed:
                cells[col].setForeground(QBrush(CHANGED_COLOR))
                cells[col].setToolTip(f"Было: {old or '—'}")
            elif p.inside(key):
                cells[col].setData(None, Qt.ForegroundRole)
                cells[col].setToolTip("")

        notes = []
        if self.settings is not None and d.kind in ("part", "assembly"):
            if self.settings.is_excluded(p.root, key):
                notes.append("не нумеруется")
            pin = self.settings.pin(p.root, key)
            if pin:
                field, value = next(iter(pin.items()))
                notes.append(f"№ {field} {value} закреплён")
        issues = p.issues_by_key.get(key, [])
        state = cells[COL_STATE]
        if key in self.pending:
            state.setIcon(self.style.standardIcon(QStyle.SP_FileDialogDetailedView))
            text = "изменено"
        elif issues:
            worst = p.worst_severity(key)
            state.setIcon(severity_icon(self.style, worst))
            text = SEVERITY_TITLES[worst].lower() + (f" (+{len(issues) - 1})" if len(issues) > 1 else "")
        else:
            state.setIcon(QIcon())
            text = ""
        state.setText("; ".join([t for t in [text] + notes if t]))
        tip = "\n".join(f"• {i.message}" for i in issues)
        for col in (2, 3, 4, 5, COL_STATE):
            cells[col].setToolTip(tip)

    def refresh_key(self, key):
        for cells in self.rows_by_key.get(key, []):
            self.refresh_row(cells, key)

    def _documents_text(self, key):
        parts = []
        drawings = self.project.drawings_of.get(key, [])
        specs = self.project.specs_of.get(key, [])
        if drawings:
            parts.append("чертёж" + (f" ×{len(drawings)}" if len(drawings) > 1 else ""))
        if specs:
            parts.append("спецификация" + (f" ×{len(specs)}" if len(specs) > 1 else ""))
        return ", ".join(parts)
