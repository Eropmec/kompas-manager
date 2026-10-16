"""Модель дерева проекта для QTreeView."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle

from kompas_manager.core.model import ERROR, INFO, KIND_TITLES, SEVERITY_TITLES, WARNING

COLUMNS = ["Обозначение", "Наименование", "Тип", "Кол.", "Документы", "Файл", "Состояние"]
COL_STATE = 6

KEY_ROLE = Qt.UserRole + 1

SEVERITY_ICONS = {
    ERROR: QStyle.SP_MessageBoxCritical,
    WARNING: QStyle.SP_MessageBoxWarning,
    INFO: QStyle.SP_MessageBoxInformation,
}


def severity_icon(style, severity):
    return style.standardIcon(SEVERITY_ICONS[severity])


class ProjectTreeBuilder:
    def __init__(self, project, style):
        self.project = project
        self.style = style
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.items_by_key = {}  # ключ файла -> первые ячейки строк, где он показан

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
            cells[0].setText(d.designation)
            cells[1].setText(d.name)
            cells[2].setText(KIND_TITLES.get(d.kind, d.kind))
            cells[4].setText(self._documents_text(key))
            issues = p.issues_by_key.get(key, [])
            if issues:
                worst = p.worst_severity(key)
                cells[COL_STATE].setIcon(severity_icon(self.style, worst))
                cells[COL_STATE].setText(SEVERITY_TITLES[worst].lower() + (f" (+{len(issues) - 1})" if len(issues) > 1 else ""))
                tip = "\n".join(f"• {i.message}" for i in issues)
                for cell in cells:
                    cell.setToolTip(tip)

        self.items_by_key.setdefault(key, []).append(cells[0])
        return cells

    def _documents_text(self, key):
        parts = []
        drawings = self.project.drawings_of.get(key, [])
        specs = self.project.specs_of.get(key, [])
        if drawings:
            parts.append("чертёж" + (f" ×{len(drawings)}" if len(drawings) > 1 else ""))
        if specs:
            parts.append("спецификация" + (f" ×{len(specs)}" if len(specs) > 1 else ""))
        return ", ".join(parts)
