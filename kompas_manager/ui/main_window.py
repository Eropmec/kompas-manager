"""Главное окно: дерево проекта, проверки и журнал."""
import os
import subprocess
import sys

from PySide6.QtCore import QSettings, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kompas_manager import __version__
from kompas_manager.core.model import ERROR, INFO, SEVERITY_TITLES, WARNING, norm
from kompas_manager.core.backup import Backup
from kompas_manager.core.bulk import bulk_replace
from kompas_manager.core.numbering import assign
from kompas_manager.core.project import Project
from kompas_manager.core.rename_plan import build_plan
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.ui.dialogs import FindReplaceDialog, PlanDialog, ProjectSchemeDialog
from kompas_manager.ui.library_panel import LibraryPanel
from kompas_manager.ui.workspace_panel import WorkspacePanel
from kompas_manager.ui.project_tree import COL_DES, COL_NAME, KEY_ROLE, ProjectTreeBuilder, severity_icon

APP_NAME = "Менеджер проектов КОМПАС"
MAX_RECENT = 8


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("KompasManager", "KompasManager")
        self.project = None
        self.project_root = None
        self.worker = None
        self.items_by_key = {}
        self.proj_settings = None  # настройки обозначения текущего проекта
        self.pending = {}  # ожидающие изменения: ключ модели -> (обозначение, наименование)
        self.builder = None
        self._updating = False

        self.resize(1200, 800)
        self._build_actions()
        self._build_ui()
        self._update_title()
        self._set_busy(False)
        self.statusBar().showMessage("Откройте папку проекта: Файл → Открыть папку проекта (Ctrl+O)")

    # ---------- построение интерфейса ----------

    def _build_actions(self):
        style = self.style()
        self.act_open = QAction(style.standardIcon(QStyle.SP_DirOpenIcon), "Открыть папку проекта…", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.choose_project)

        self.act_refresh = QAction(style.standardIcon(QStyle.SP_BrowserReload), "Обновить", self)
        self.act_refresh.setShortcut(QKeySequence.Refresh)
        self.act_refresh.setToolTip("Перечитать изменённые файлы (F5)")
        self.act_refresh.triggered.connect(lambda: self.scan(force=False))

        self.act_rescan = QAction("Перечитать все файлы", self)
        self.act_rescan.setToolTip("Прочитать все файлы заново, без кэша")
        self.act_rescan.triggered.connect(lambda: self.scan(force=True))

        self.act_expand = QAction("Развернуть всё", self)
        self.act_expand.triggered.connect(lambda: self.tree.expandAll())
        self.act_collapse = QAction("Свернуть всё", self)
        self.act_collapse.triggered.connect(lambda: self.tree.collapseAll())

        self.act_show_kompas = QAction("Показывать окно КОМПАСа при сканировании", self)
        self.act_show_kompas.setCheckable(True)
        self.act_show_kompas.setChecked(self.settings.value("show_kompas", False, type=bool))
        self.act_show_kompas.toggled.connect(lambda v: self.settings.setValue("show_kompas", v))

        self.act_settings = QAction("Настройки…", self)
        self.act_settings.triggered.connect(self.edit_settings)
        self.act_clear_cache = QAction("Очистить кэш сканирования", self)
        self.act_clear_cache.triggered.connect(self.clear_cache)

        self.act_scheme = QAction("Схема обозначения…", self)
        self.act_scheme.triggered.connect(self.edit_scheme)
        self.act_apply_scheme = QAction(style.standardIcon(QStyle.SP_ArrowRight), "Применить схему", self)
        self.act_apply_scheme.setToolTip("Рассчитать обозначения всех элементов по схеме проекта")
        self.act_apply_scheme.triggered.connect(self.apply_scheme)
        self.act_find = QAction("Найти и заменить…", self)
        self.act_find.setShortcut(QKeySequence.Replace)
        self.act_find.triggered.connect(self.find_replace)
        self.act_reset = QAction(style.standardIcon(QStyle.SP_DialogResetButton), "Сбросить изменения", self)
        self.act_reset.triggered.connect(self.reset_pending)
        self.act_rename = QAction(style.standardIcon(QStyle.SP_DialogApplyButton), "Переобозначить…", self)
        self.act_rename.setShortcut("Ctrl+Return")
        self.act_rename.triggered.connect(lambda: self.rename())
        self.act_rollback = QAction("Откатить последнее переобозначение…", self)
        self.act_rollback.triggered.connect(self.rollback)

        self.act_new_product = QAction(style.standardIcon(QStyle.SP_FileDialogNewFolder), "Новое изделие…", self)
        self.act_new_product.setShortcut(QKeySequence.New)
        self.act_new_product.triggered.connect(self._new_product_here)

        self.act_exit = QAction("Выход", self)
        self.act_exit.triggered.connect(self.close)

        self.act_about = QAction("О программе", self)
        self.act_about.triggered.connect(self.about)

        menu = self.menuBar()
        m_file = menu.addMenu("Файл")
        m_file.addAction(self.act_new_product)
        m_file.addAction(self.act_open)
        self.menu_recent = m_file.addMenu("Недавние проекты")
        m_file.addSeparator()
        m_file.addAction(self.act_exit)
        self._fill_recent_menu()

        m_project = menu.addMenu("Проект")
        m_project.addAction(self.act_refresh)
        m_project.addAction(self.act_rescan)
        m_project.addSeparator()
        m_project.addAction(self.act_expand)
        m_project.addAction(self.act_collapse)
        m_project.addSeparator()
        m_project.addAction("Сделать изделие автономным…", self.make_autonomous)
        m_project.addAction("Архивировать изделие…", self.archive_product)

        m_des = menu.addMenu("Обозначения")
        m_des.addAction(self.act_scheme)
        m_des.addAction(self.act_apply_scheme)
        m_des.addAction(self.act_find)
        m_des.addSeparator()
        m_des.addAction(self.act_reset)
        m_des.addAction(self.act_rename)
        m_des.addSeparator()
        m_des.addAction(self.act_rollback)

        m_tools = menu.addMenu("Сервис")
        m_tools.addAction(self.act_settings)
        m_tools.addAction(self.act_show_kompas)
        m_tools.addAction(self.act_clear_cache)

        m_help = menu.addMenu("Справка")
        m_help.addAction(self.act_about)

        toolbar = QToolBar("Основная")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.addAction(self.act_new_product)
        toolbar.addAction(self.act_open)
        toolbar.addAction(self.act_refresh)
        toolbar.addSeparator()
        toolbar.addAction(self.act_expand)
        toolbar.addAction(self.act_collapse)
        toolbar.addSeparator()
        toolbar.addAction(self.act_apply_scheme)
        toolbar.addAction(self.act_reset)
        toolbar.addAction(self.act_rename)
        self.addToolBar(toolbar)

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Фильтр: обозначение, наименование или имя файла")
        self.filter_edit.setClearButtonEnabled(True)
        layout.addWidget(self.filter_edit)

        splitter = QSplitter(Qt.Vertical)

        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.doubleClicked.connect(self._tree_double_clicked)
        self.tree.expanded.connect(lambda _i: self.tree.resizeColumnToContents(COL_DES))
        splitter.addWidget(self.tree)

        self.tabs = QTabWidget()
        self.issues = QTreeWidget()
        self.issues.setHeaderLabels(["Уровень", "Проблема", "Файл"])
        self.issues.setRootIsDecorated(False)
        self.issues.setAlternatingRowColors(True)
        self.issues.itemActivated.connect(self._issue_activated)
        self.issues.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabs.addTab(self.issues, "Проверки")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, "Журнал")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        from kompas_manager.ui.source_panel import SourcePanel

        self.library = LibraryPanel()
        self.library.insert_requested.connect(self.insert_element)
        self.library.passport_requested.connect(self.edit_passport)
        self.source = SourcePanel(self.library)
        self.source.load_requested.connect(self.load_source)
        self.source.paste_requested.connect(self.paste_from_source)
        self.main_tabs = central
        self.workspace = WorkspacePanel()
        self.workspace.open_requested.connect(self.open_project)
        self.workspace.new_product_requested.connect(self.new_product)
        self.workspace.folder_copied.connect(self.check_copied_folder)
        outer = QSplitter(Qt.Horizontal)
        outer.addWidget(self.workspace)
        outer.addWidget(self.main_tabs)
        outer.addWidget(self.source)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 3)
        outer.setStretchFactor(2, 2)
        outer.setSizes([260, 760, 460])
        self._after_scan = None
        self.tree.selectionModel().currentChanged.connect(lambda *_: self._update_target_label())
        self._update_target_label()
        self.setCentralWidget(outer)
        self.library.reload()

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setTextVisible(True)
        self.cancel_btn = QPushButton("Остановить")
        self.cancel_btn.clicked.connect(self._cancel_scan)
        self.counts_label = QLabel()
        self.statusBar().addPermanentWidget(self.counts_label)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)

    # ---------- проект ----------

    def choose_project(self):
        start = self.project_root or self.settings.value("last_dir", os.path.expanduser("~"))
        path = QFileDialog.getExistingDirectory(self, "Папка проекта", start)
        if path:
            self.open_project(os.path.normpath(path))

    def open_project(self, path):
        if not os.path.isdir(path):
            QMessageBox.warning(self, APP_NAME, f"Папка не найдена:\n{path}")
            self._remove_recent(path)
            return
        if self.worker is not None:
            return
        if self.pending and os.path.normcase(path) != os.path.normcase(self.project_root or ""):
            if not self._confirm_discard():
                return
            self.pending = {}
        self.project_root = path
        self.proj_settings = ProjectSettings.load(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        self._add_recent(path)
        self._update_title()
        self.scan(force=False)

    def scan(self, force=False):
        if not self.project_root or self.worker is not None:
            return
        from kompas_manager.ui.workers import ScanWorker

        self.log.appendPlainText(f"\n=== Сканирование: {self.project_root}")
        self._set_busy(True)
        self.worker = ScanWorker(self.project_root, show=self.act_show_kompas.isChecked(), force=force)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_scan_done)
        self.worker.start()

    def _cancel_scan(self):
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, done, total, name):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done} из {total}")
        if name:
            self.statusBar().showMessage(f"Чтение: {name}")

    def _on_scan_done(self, docs, complete):
        self.worker.wait()
        self.worker = None
        self._set_busy(False)
        self.show_project(Project(self.project_root, docs))
        note = "" if complete else " (сканирование прервано, показаны не все файлы)"
        self.statusBar().showMessage("Готово" + note, 8000)
        hook, self._after_scan = self._after_scan, None
        if hook is not None:
            hook()

    def show_project(self, project):
        """Показать проект в дереве и на вкладке проверок."""
        first = self.project is None or self.project.root != project.root
        self.project = project
        self.project_root = project.root
        if self.proj_settings is None:
            self.proj_settings = ProjectSettings.load(project.root)
        self.pending = {k: v for k, v in self.pending.items() if project.doc(k) is not None}
        self._rebuild_tree(expand_default=first)
        self._fill_issues()
        self._update_counts()
        self._update_title()
        self._apply_filter(self.filter_edit.text())

    def _rebuild_tree(self, expand_default=False):
        expanded = None if expand_default else self._expanded_keys()
        self._updating = True
        self.builder = ProjectTreeBuilder(self.project, self.style(), self.pending, self.proj_settings)
        model = self.builder.build()
        self.items_by_key = self.builder.items_by_key
        self.proxy.setSourceModel(model)
        model.itemChanged.connect(self._on_item_changed)
        self._updating = False
        if expanded is None:
            self.tree.expandToDepth(1)
            for col in range(model.columnCount()):
                self.tree.resizeColumnToContents(col)
            self.tree.header().setStretchLastSection(True)
        else:
            self._restore_expanded(expanded)
        for col in (COL_DES, COL_NAME):
            self.tree.resizeColumnToContents(col)
        busy = self.worker is not None
        for act in (self.act_scheme, self.act_apply_scheme, self.act_find, self.act_rollback):
            act.setEnabled(not busy)
        self._update_pending_actions()
        self._update_target_label()

    def _expanded_keys(self):
        result = set()

        def walk(parent):
            for row in range(self.proxy.rowCount(parent)):
                index = self.proxy.index(row, 0, parent)
                if self.tree.isExpanded(index):
                    result.add(index.data(KEY_ROLE) or index.data())
                    walk(index)

        walk(self.tree.rootIndex())
        return result

    def _restore_expanded(self, keys):
        def walk(parent):
            for row in range(self.proxy.rowCount(parent)):
                index = self.proxy.index(row, 0, parent)
                if (index.data(KEY_ROLE) or index.data()) in keys:
                    self.tree.expand(index)
                    walk(index)

        walk(self.tree.rootIndex())

    def _fill_issues(self):
        self.issues.clear()
        p = self.project
        for issue in p.issues:
            item = QTreeWidgetItem([SEVERITY_TITLES[issue.severity], issue.message, p.display_path(issue.key)])
            item.setIcon(0, severity_icon(self.style(), issue.severity))
            item.setData(0, KEY_ROLE, issue.key)
            item.setToolTip(1, issue.message)
            self.issues.addTopLevelItem(item)
        self.issues.resizeColumnToContents(0)
        c = p.counts()
        self.tabs.setTabText(0, f"Проверки: ошибок {c[ERROR]}, предупреждений {c[WARNING]}, замечаний {c[INFO]}")

    def _update_counts(self):
        c = self.project.counts()
        self.counts_label.setText(
            f"сборок: {c['assembly']} · деталей: {c['part']} · чертежей: {c['drawing']} · "
            f"спецификаций: {c['spec']} · ошибок: {c[ERROR]} · предупреждений: {c[WARNING]}"
        )

    def _apply_filter(self, text):
        self.proxy.setFilterFixedString(text.strip())
        if text.strip():
            self.tree.expandAll()

    # ---------- действия с файлами ----------

    def _key_at(self, proxy_index):
        if not proxy_index.isValid():
            return None
        source = self.proxy.mapToSource(proxy_index.siblingAtColumn(0))
        return source.data(KEY_ROLE)

    def _path(self, key):
        return self.project.raw_paths.get(key, key) if self.project else key

    def _tree_double_clicked(self, index):
        if index.column() in (COL_DES, COL_NAME) and self.proxy.flags(index) & Qt.ItemIsEditable:
            return  # двойной щелчок по обозначению или наименованию — правка
        key = self._key_at(index)
        if key:
            self.open_in_kompas(key)

    def selected_keys(self):
        keys = []
        for index in self.tree.selectionModel().selectedRows(0):
            k = self._key_at(index)
            d = self.project.doc(k) if (k and self.project) else None
            if d is not None and k not in keys:
                keys.append(k)
        return keys

    def selected_branches(self):
        """Выделенные элементы вместе со всем составом выделенных сборок."""
        out, stack = set(), list(self.selected_keys())
        while stack:
            k = stack.pop()
            if k in out:
                continue
            out.add(k)
            stack.extend(c for c, _ in self.project.components.get(k, []))
        return out

    def _tree_menu(self, pos):
        key = self._key_at(self.tree.indexAt(pos))
        if not key or self.project is None:
            return
        p = self.project
        d = p.doc(key)
        selected = self.selected_keys()
        if len(selected) > 1 and key in selected:
            menu = QMenu(self)
            editable = [k for k in selected if self.builder.editable(k)]
            menu.addAction(f"Изменить выделенные ({len(editable)})…", lambda: self.group_edit(editable)).setEnabled(
                bool(editable) and self.worker is None)
            act = menu.addAction("Переобозначить выделенные ветки…", lambda: self.rename(self.selected_branches()))
            act.setEnabled(bool(self.pending) and self.worker is None)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        menu = QMenu(self)
        exists = os.path.exists(self._path(key))
        act = menu.addAction("Открыть в КОМПАСе", lambda: self.open_in_kompas(key))
        act.setEnabled(exists)
        for drw in p.drawings_of.get(key, []):
            menu.addAction(f"Открыть чертёж: {os.path.basename(self._path(drw))}", lambda k=drw: self.open_in_kompas(k))
        for spec in p.specs_of.get(key, []):
            menu.addAction(f"Открыть спецификацию: {os.path.basename(self._path(spec))}", lambda k=spec: self.open_in_kompas(k))
        menu.addSeparator()
        act = menu.addAction("Показать в проводнике", lambda: self.show_in_explorer(key))
        act.setEnabled(exists)
        if d is not None and d.designation:
            menu.addAction("Копировать обозначение", lambda: QApplication.clipboard().setText(d.designation))
        if self.builder is not None and self.builder.editable(key) and self.worker is None:
            menu.addSeparator()
            if key in self.pending:
                menu.addAction("Отменить изменение", lambda: self._set_pending(key, None))
            field = "сборка" if d.kind == "assembly" else "деталь"
            pin = self.proj_settings.pin(self.project.root, key)
            menu.addAction(f"Закрепить номер ({field})…", lambda: self._pin_number(key, field))
            if pin:
                menu.addAction("Снять закреплённый номер", lambda: self._unpin(key))
            act = menu.addAction("Не нумеровать (стандартное или покупное изделие)")
            act.setCheckable(True)
            act.setChecked(self.proj_settings.is_excluded(self.project.root, key))
            act.toggled.connect(lambda v: self._set_excluded(key, v))
        if d is not None and d.kind in ("part", "assembly") and p.inside(key) and self.worker is None:
            menu.addSeparator()
            if d.kind == "assembly":
                menu.addAction("Добавить детали и сборки…", lambda: self.append_items(key))
            parent_key = self._parent_key_at(self.tree.indexAt(pos))
            if parent_key:
                menu.addAction("Удалить из сборки…", lambda: self.delete_from_assembly(parent_key, key))
            menu.addAction("Версии узла…", lambda: self.node_versions(key))
            if self.pending and d.kind == "assembly":
                menu.addAction("Переобозначить только эту ветку…", lambda: self.rename(self.selected_branches() | {key}))
        if d is not None and d.kind == "assembly" and p.inside(key) and self.worker is None:
            if not parent_key and key in p.roots():
                menu.addAction("Создать уровень выше…", lambda: self.level_up(key))
            menu.addAction("Вынести изменённые в сборке вхождения в файлы…", lambda: self.extract_instances(key))
        issues = p.issues_by_key.get(key, [])
        if issues:
            menu.addSeparator()
            sub = menu.addMenu(f"Проблемы ({len(issues)})")
            for i in issues:
                sub.addAction(severity_icon(self.style(), i.severity), i.message).setEnabled(False)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def open_in_kompas(self, key):
        path = self._path(key)
        if not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, f"Файл не найден:\n{path}")
            return
        if hasattr(os, "startfile"):
            os.startfile(path)  # открывается в КОМПАСе, связанном с типом файла

    def show_in_explorer(self, key):
        path = self._path(key)
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{path}"')

    def _issue_activated(self, item, _column):
        key = item.data(0, KEY_ROLE)
        items = self.items_by_key.get(key)
        if not items:
            # Чертёж или спецификация: показать модель, к которой документ относится
            d = self.project.doc(key) if self.project else None
            for ref in (d.refs if d else []):
                items = self.items_by_key.get(norm(ref))
                if items:
                    break
        if not items:
            self.statusBar().showMessage("Этого файла нет в дереве проекта", 5000)
            return
        if self.filter_edit.text():
            self.filter_edit.clear()
        index = self.proxy.mapFromSource(items[0].index())
        parent = index.parent()
        while parent.isValid():
            self.tree.expand(parent)
            parent = parent.parent()
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index, QAbstractItemView.PositionAtCenter)
        self.tree.setFocus()

    # ---------- обозначения ----------

    def _on_item_changed(self, item):
        if self._updating or item.column() not in (COL_DES, COL_NAME):
            return
        key = item.index().siblingAtColumn(0).data(KEY_ROLE)
        d = self.project.doc(key) if key else None
        if d is None:
            return
        des, name = self.pending.get(key, (d.designation, d.name))
        text = item.text().strip()
        if item.column() == COL_DES:
            des = text
        else:
            name = text
        self._set_pending(key, (des, name))

    def _set_pending(self, key, value):
        d = self.project.doc(key)
        if value is None or tuple(value) == (d.designation, d.name):
            self.pending.pop(key, None)
        else:
            self.pending[key] = tuple(value)
        self._updating = True
        self.builder.refresh_key(key)
        self._updating = False
        self._update_pending_actions()

    def _update_pending_actions(self):
        n = len(self.pending)
        busy = self.worker is not None
        self.act_reset.setEnabled(bool(n) and not busy)
        self.act_rename.setEnabled(bool(n) and not busy)
        self.act_rename.setText(f"Переобозначить ({n})…" if n else "Переобозначить…")

    def _confirm_discard(self):
        answer = QMessageBox.question(
            self, APP_NAME,
            f"Есть непримененные изменения обозначений ({len(self.pending)}). Отказаться от них?",
        )
        return answer == QMessageBox.Yes

    def _save_settings(self):
        try:
            self.proj_settings.save(self.project.root)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Не удалось сохранить настройки проекта:\n{e}")

    def edit_scheme(self):
        if self.project is None:
            return
        if ProjectSchemeDialog(self.proj_settings, self).exec():
            self._save_settings()
            self.statusBar().showMessage(
                f"Схема проекта: {self.proj_settings.scheme.template}, код {self.proj_settings.code}. "
                "«Применить схему» рассчитает обозначения.", 8000)

    def apply_scheme(self):
        if self.project is None:
            return
        result, warnings = assign(self.project, self.proj_settings)
        changed = 0
        for key, des in result.items():
            d = self.project.doc(key)
            name = self.pending.get(key, (d.designation, d.name))[1]
            if (des, name) != (d.designation, d.name):
                self.pending[key] = (des, name)
                changed += 1
            else:
                self.pending.pop(key, None)
        self._rebuild_tree()
        for w in warnings:
            self.log.appendPlainText(f"Схема: {self.project.display_path(w.key)}: {w.message}")
        msg = f"По схеме изменится обозначений: {changed}. Проверьте выделенные значения и нажмите «Переобозначить»."
        if warnings:
            msg += f"\n\nПредупреждений: {len(warnings)} (см. вкладку «Журнал»)."
            self.tabs.setCurrentWidget(self.log)
        QMessageBox.information(self, APP_NAME, msg)

    def _subtree_keys(self, key):
        out, stack = [], [key]
        while stack:
            k = stack.pop()
            if k in out:
                continue
            out.append(k)
            stack.extend(c for c, _ in self.project.components.get(k, []))
        return out

    def find_replace(self):
        if self.project is None:
            return
        current = self._key_at(self.tree.currentIndex())
        dlg = FindReplaceDialog(bool(current), self)
        if not dlg.exec():
            return
        v = dlg.values()
        keys = self._subtree_keys(current) if v["selection"] and current else list(self.project.docs)
        values = {}
        for k in keys:
            if self.builder.editable(k):
                d = self.project.doc(k)
                values[k] = self.pending.get(k, (d.designation, d.name))
        changes = bulk_replace(values, v["field"], v["find"], v["repl"], v["case"])
        for k, pair in changes.items():
            d = self.project.doc(k)
            if pair == (d.designation, d.name):
                self.pending.pop(k, None)
            else:
                self.pending[k] = pair
        self._rebuild_tree()
        self.statusBar().showMessage(f"Заменено значений: {len(changes)}", 6000)

    def reset_pending(self):
        if self.pending and self._confirm_discard():
            self.pending = {}
            self._rebuild_tree()

    def _pin_number(self, key, field):
        current = self.proj_settings.pin(self.project.root, key).get(field, 1)
        value, ok = QInputDialog.getInt(
            self, "Закрепить номер",
            f"Номер ({field}) для «{self.project.doc(key).name}».\n"
            "Автонумерация будет его пропускать.", current, 0, 9999)
        if ok:
            self.proj_settings.set_pin(self.project.root, key, field, value)
            self._save_settings()
            self.builder.refresh_key(key)

    def _unpin(self, key):
        self.proj_settings.set_pin(self.project.root, key, None, None)
        self._save_settings()
        self.builder.refresh_key(key)

    def _set_excluded(self, key, value):
        self.proj_settings.set_excluded(self.project.root, key, value)
        self._save_settings()
        self.builder.refresh_key(key)

    def rename(self, only=None):
        """only — множество ключей: переобозначить только эти элементы (выделенные ветки)."""
        if not self.pending or self.worker is not None:
            return
        changes = {k: v for k, v in self.pending.items() if only is None or k in only}
        if not changes:
            QMessageBox.information(self, APP_NAME, "В выделенных ветках нет изменений обозначений и наименований.")
            return
        self._renamed_keys = set(changes)
        plan = build_plan(self.project, changes)
        if not plan.ops and not plan.issues:
            QMessageBox.information(self, APP_NAME, "Изменений нет.")
            return
        if not PlanDialog(plan, self.project, self.style(), self).exec():
            return
        from kompas_manager.ui.workers import RenameWorker

        self.log.appendPlainText("\n=== Переобозначение")
        self.tabs.setCurrentWidget(self.log)
        self._plan = plan
        self.worker = RenameWorker(plan, show=self.act_show_kompas.isChecked())
        self._set_busy(True)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_rename_done)
        self.worker.start()

    def _on_rename_done(self, result):
        self.worker.wait()
        self.worker = None
        self._set_busy(False)
        plan = self._plan
        if result is not None and result.done:
            self.proj_settings.rename_paths(self.project.root, plan.mapping)
            self._save_settings()
            self.pending = {k: v for k, v in self.pending.items() if k not in self._renamed_keys}
            text = f"Переобозначение выполнено. Файлов затронуто: {len(plan.ops)}."
            if result.warnings:
                text += "\n\nЗамечания:\n" + "\n".join(result.warnings[:15])
            text += "\n\nПроект будет перечитан. Проверьте спецификации: при необходимости синхронизируйте их со сборкой в КОМПАСе."
            QMessageBox.information(self, APP_NAME, text)
        else:
            errors = result.errors if result is not None else ["см. журнал"]
            text = "Переобозначение не завершено:\n" + "\n".join(errors[:15])
            if result is not None and result.backup is not None:
                text += "\n\nСтарые файлы не удалены. Чтобы вернуть всё как было — «Обозначения → Откатить последнее переобозначение»."
            QMessageBox.warning(self, APP_NAME, text)
        for w in (result.warnings if result else []):
            self.log.appendPlainText("  замечание: " + w)
        self.scan(force=False)

    def rollback(self):
        if self.project is None or self.worker is not None:
            return
        backup = Backup.latest(self.project.root)
        if backup is None:
            QMessageBox.information(self, APP_NAME, "Резервных копий для отката нет.")
            return
        m = backup.manifest
        answer = QMessageBox.question(
            self, APP_NAME,
            f"Откатить переобозначение от {m['time']}?\n\n"
            f"Будет восстановлено файлов: {len(m['originals'])}, удалено созданных: {len(m['created'])}.\n"
            "Изменения, сделанные в этих файлах после переобозначения, будут потеряны.\n"
            "Файлы должны быть закрыты в КОМПАСе.",
        )
        if answer != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            self.log.appendPlainText(f"\n=== Откат: {backup.folder}")
            errors = backup.rollback(log=self.log.appendPlainText)
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.warning(self, APP_NAME, "Откат выполнен не полностью:\n" + "\n".join(errors[:15]))
        else:
            QMessageBox.information(self, APP_NAME, "Откат выполнен. Проект будет перечитан.")
        self.pending = {}
        self.proj_settings = ProjectSettings.load(self.project.root)
        self.scan(force=False)

    # ---------- библиотека ----------

    def _run_call(self, fn, on_done, title):
        if self.worker is not None:
            return
        from kompas_manager.ui.workers import CallWorker

        self.log.appendPlainText(f"\n=== {title}")
        self.worker = CallWorker(fn)
        self._set_busy(True)
        self.statusBar().showMessage(title + "…")
        self.worker.log.connect(self.log.appendPlainText)

        def done(result, error):
            self.worker.wait()
            self.worker = None
            self._set_busy(False)
            self.statusBar().clearMessage()
            if error:
                QMessageBox.warning(self, APP_NAME, f"{title}: ошибка.\n{error}\n\nПодробности — на вкладке «Журнал» проекта.")
                return
            on_done(result)

        self.worker.done.connect(done)
        self.worker.start()

    def _read_element(self, element, then):
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.library_ops import read_element

            session = K.Session(show, log)
            try:
                return read_element(K, session.app, element.path)
            finally:
                session.close(log)

        self._run_call(fn, then, f"Чтение переменных: {element.title}")

    def edit_passport(self, element, force_read=False):
        if element.passport and element.passport.variables and not force_read:
            self._open_passport(element, element.passport.variables, ("", ""))
        else:
            self._read_element(element, lambda r: self._open_passport(element, r[2], (r[0], r[1])))

    def _open_passport(self, element, variables, props):
        from kompas_manager.ui.library_dialogs import PassportDialog

        dlg = PassportDialog(element, variables, props, self)
        result = dlg.exec()
        if dlg.reread:
            self.edit_passport(element, force_read=True)
        elif result:
            self.library.reload()
            self.statusBar().showMessage(f"Паспорт сохранён: {element.title}", 5000)

    def insert_element(self, element):
        if self.project is None:
            QMessageBox.information(self, APP_NAME, "Сначала откройте проект: копия элемента кладётся в папку проекта.")
            return
        p = element.passport
        if p and p.variables:
            self._open_insert(element, ("", ""))
        else:
            from kompas_manager.core.library import Element, Passport

            def then(r):
                temp = Element(element.path, Passport(kind=p.kind if p else "standard",
                                                      designation_template=p.designation_template if p else "",
                                                      name_template=p.name_template if p else "",
                                                      table=p.table if p else "", variables=r[2]))
                self._open_insert(temp, (r[0], r[1]))

            self._read_element(element, then)

    def _open_insert(self, element, props):
        from kompas_manager.core.library import read_table
        from kompas_manager.ui.library_dialogs import InsertDialog

        table = None
        if element.table_path():
            try:
                table = read_table(element.table_path())
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Таблица типоразмеров не прочиталась:\n{e}")
        target = self.target_assembly()
        if target is None:
            QMessageBox.information(self, APP_NAME, "В изделии нет сборки, куда вставлять.")
            return
        target_path = self._path(target)
        td = self.project.doc(target)
        rel = os.path.relpath(os.path.dirname(target_path), self.project.root)
        from kompas_manager.core.editing import _next_numbers
        from kompas_manager.core.library import NUMBERED_KINDS
        from kompas_manager.core.structure import Node

        project_des = ""
        if element.passport and element.passport.kind in NUMBERED_KINDS and not element.passport.designation_template:
            node = Node("part", element.title)
            project_des = _next_numbers(self.project, target, [node], self.proj_settings).get(id(node), "")
        dlg = InsertDialog(element, self.project.root, table, props, self, initial_folder=rel,
                           target_title=f"{td.designation} {td.name}", project_designation=project_des)
        if not dlg.exec():
            return
        plan, count = dlg.plan, dlg.count.value()
        from kompas_manager.core.localize import Placement

        root = self.project.root
        # один типоразмер — один файл на всё изделие: сначала по происхождению, затем по имени файла
        same = self.proj_settings.find_origin(root, element.path, plan.values)
        if not same:
            by_name = Placement(root).by_name.get(os.path.basename(plan.target).lower())
            if by_name:
                o = self.proj_settings.origin(root, by_name)
                from kompas_manager.core.library import values_key

                if o and (norm(o.get("source", "")) != norm(element.path) or o.get("values") != values_key(plan.values)):
                    QMessageBox.warning(
                        self, APP_NAME,
                        f"В изделии уже есть «{os.path.basename(by_name)}», но он сделан из другого элемента или с "
                        "другими значениями. Уточните шаблон наименования в паспорте элемента, чтобы имена "
                        "разных типоразмеров не совпадали.")
                    return
                same = by_name
        if same:
            plan.target, plan.reuse = same, True
        show = self.act_show_kompas.isChecked()
        known = self._known_externals()

        def fn(K, log):
            from kompas_manager.autonomy_ops import insert_library

            return insert_library(K, root, plan, element, target_path, count, show=show, log=log, known=known)

        def done(result):
            path, sources = result
            if not plan.reuse:
                self.proj_settings.add_origin(root, path, element.path, plan.values)
                self._save_settings()
            self._record_origins(sources)
            self.statusBar().showMessage(
                ("Использован существующий файл " if plan.reuse else "Вставлено: ")
                + os.path.relpath(path, root) + f" → {td.designation} {td.name}", 10000)
            self.scan(force=False)

        self._run_call(fn, done, f"Вставка: {element.title}")

    def extract_instances(self, key):
        assembly = self._path(key)
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.library_ops import analyze_assembly

            return analyze_assembly(K, assembly, show=show, log=log)

        self._run_call(fn, lambda r: self._confirm_extract(assembly, *r), f"Анализ вхождений: {os.path.basename(assembly)}")

    def _confirm_extract(self, assembly, comps, file_values, file_props):
        from kompas_manager.core.library import load_passport, plan_extract
        from kompas_manager.ui.library_dialogs import ExtractDialog

        passports = {path: load_passport(path) for _i, path, _v in comps}
        passports = {k: v for k, v in passports.items() if v}
        groups = plan_extract(comps, file_values, file_props, os.path.dirname(assembly), passports)
        if not groups:
            QMessageBox.information(self, APP_NAME, "В сборке нет вхождений с переменными, изменёнными на уровне сборки.")
            return
        if not ExtractDialog(groups, self.project, self).exec():
            return
        root = self.project.root
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.library_ops import extract_instances

            return extract_instances(K, root, assembly, groups, passports, show=show, log=log)

        def done(_backup):
            QMessageBox.information(self, APP_NAME,
                                    f"Готово: создано файлов {sum(1 for g in groups if not g.reuse)}, "
                                    f"перепривязано вхождений {sum(len(g.instances) for g in groups)}.\n"
                                    "Откат — «Обозначения → Откатить последнее переобозначение».")
            self.scan(force=False)

        self._run_call(fn, done, "Вынос вхождений в файлы")

    # ---------- структура и перенос ----------

    def _parent_key_at(self, proxy_index):
        parent = proxy_index.parent()
        if not parent.isValid():
            return None
        key = self._key_at(parent)
        d = self.project.doc(key) if key else None
        return key if d is not None and d.kind == "assembly" and self.project.inside(key) else None

    def _templates(self):
        return {"part": self.settings.value("template_part", ""), "assembly": self.settings.value("template_asm", "")}

    def append_items(self, key):
        from kompas_manager.ui.structure_dialog import StructureDialog

        if self.pending and not self._confirm_discard():
            return
        dlg = StructureDialog(self.project.root, self, existing=(self.project, key, self.proj_settings))
        if not dlg.exec() or dlg.append_plan is None:
            return
        plan, root, templates = dlg.append_plan, self.project.root, self._templates()
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.editing_ops import append_to_assembly

            return append_to_assembly(K, root, plan, templates, show=show, log=log)

        self.pending = {}
        self._run_call(fn, lambda _r: self.scan(force=False), "Добавление в сборку")

    def delete_from_assembly(self, parent_key, key):
        from kompas_manager.core.editing import plan_delete

        p = self.project
        d, pd = p.doc(key), p.doc(parent_key)
        plan = plan_delete(p, parent_key, key)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        text = (f"Удалить «{d.designation} {d.name}» из сборки «{pd.designation} {pd.name}» "
                f"(вхождений: {plan.instances})?")
        if plan.files:
            text += ("\n\nФайлы, которые больше нигде в изделии не используются:\n"
                     + "\n".join("  " + p.display_path(norm(f))
                                  for f in plan.files))
        if plan.kept:
            text += "\n\nОстаются (используются в других сборках):\n" + "\n".join("  " + os.path.basename(f) for f in plan.kept)
        text += "\n\nПеред изменением сборка и файлы копируются в _backup; откат — «Обозначения → Откатить последнее»."
        box.setText(text)
        with_files = box.addButton("Удалить вхождения и файлы", QMessageBox.DestructiveRole) if plan.files else None
        only = box.addButton("Только из сборки", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (with_files, only) or clicked is None:
            return
        if clicked is only:
            plan.files = []
        root = p.root
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.editing_ops import delete_from_assembly

            return delete_from_assembly(K, root, plan, show=show, log=log)

        self._run_call(fn, lambda _r: self.scan(force=False), "Удаление из сборки")

    def node_versions(self, key):
        from kompas_manager.ui.versions_dialog import VersionsDialog

        dlg = VersionsDialog(self.project, key, self)
        if not dlg.exec() or dlg.restore_plan is None:
            return
        plan, project, move = dlg.restore_plan, self.project, dlg.move_orphans
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.editing_ops import restore_version

            return restore_version(K, project, plan, move_orphans=move, show=show, log=log)

        self.pending = {}
        self._run_call(fn, lambda _r: self.scan(force=False), "Восстановление версии")

    # ---------- источник, автономность, уровень выше ----------

    def target_assembly(self):
        """Сборка, куда вставлять: выделенная в дереве (для детали — её сборка), иначе головная."""
        if self.project is None:
            return None
        index = self.tree.currentIndex()
        key = self._key_at(index) if index.isValid() else None
        d = self.project.doc(key) if key else None
        if d is not None and d.kind == "assembly" and self.project.inside(key):
            return key
        if index.isValid():
            parent = self._parent_key_at(index)
            if parent:
                return parent
        roots = [k for k in self.project.roots() if self.project.inside(k)]
        return roots[0] if roots else None

    def _update_target_label(self):
        key = self.target_assembly() if self.project is not None else None
        d = self.project.doc(key) if key else None
        self.source.set_target(f"{d.designation} {d.name}".strip() if d else "")

    def load_source(self, folder):
        def fn(K, log):
            from kompas_manager.core.cache import ScanCache
            from kompas_manager.scanner import scan

            cache = ScanCache()
            try:
                docs, _complete = scan(folder, cache, show=False, log=log)
            finally:
                cache.close()
            return docs

        self._run_call(fn, lambda docs: self.source.show_project(Project(folder, docs)),
                       f"Чтение изделия-источника: {os.path.basename(folder)}")

    def paste_from_source(self, src_project, src_key):
        from kompas_manager.core.transfer import plan_paste

        if self.project is None:
            QMessageBox.information(self, APP_NAME, "Откройте изделие, в которое вставлять.")
            return
        if os.path.normcase(src_project.root) == os.path.normcase(self.project.root):
            QMessageBox.information(self, APP_NAME, "Источник и текущее изделие совпадают. Для правки состава "
                                    "используйте «Добавить детали и сборки» и «Удалить из сборки».")
            return
        target = self.target_assembly()
        if target is None:
            QMessageBox.information(self, APP_NAME, "В изделии нет сборки, куда вставлять.")
            return
        if self.pending and not self._confirm_discard():
            return
        target_path = self._path(target)
        plan = plan_paste(src_project, src_key, os.path.dirname(target_path))
        if plan.problems:
            QMessageBox.warning(self, APP_NAME, "Вставить нельзя:\n" + "\n".join(plan.problems[:15]))
            return
        sd, td = src_project.doc(src_key), self.project.doc(target)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText(
            f"Вставить «{sd.designation} {sd.name}» из изделия «{os.path.basename(src_project.root)}» "
            f"в сборку «{td.designation} {td.name}»?\n\n"
            f"Копируется файлов: {len(plan.files)} в «{os.path.relpath(plan.target_dir, self.project.root)}». "
            "Библиотечные и прочие внешние файлы узла тоже копируются в изделие — узел полностью отвязывается "
            "от исходных файлов.")
        renum = box.addButton("Вставить и пронумеровать по схеме", QMessageBox.AcceptRole)
        keep = box.addButton("Вставить без изменения обозначений", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (renum, keep):
            return
        do_renum = box.clickedButton() is renum
        root = self.project.root
        show = self.act_show_kompas.isChecked()

        known = self._known_externals()

        def fn(K, log):
            from kompas_manager.autonomy_ops import paste_node

            return paste_node(K, root, plan, target_path, show=show, log=log, known=known)

        def done(result):
            new_root, _created, missing, sources = result
            self._record_origins(sources)
            if missing:
                self.log.appendPlainText("Не найдены внешние файлы: " + "; ".join(missing))
            if do_renum:
                self._after_scan = lambda: self._renumber_pasted(target_path, new_root)
            self.scan(force=False)

        self._run_call(fn, done, f"Вставка узла: {sd.designation} {sd.name}")

    def _renumber_pasted(self, parent_path, root_path):
        from kompas_manager.core.editing import renumber_subtree

        p = self.project
        parent, node = norm(parent_path), norm(root_path)
        if p.doc(parent) is None or p.doc(node) is None:
            return
        numbers = renumber_subtree(p, parent, node, self.proj_settings)
        if not numbers:
            QMessageBox.information(self, APP_NAME, "Обозначение сборки не разбирается по схеме изделия — "
                                    "пронумеруйте узел через «Применить схему» или вручную.")
            return
        for key, des in numbers.items():
            d = p.doc(key)
            if des != d.designation:
                self.pending[key] = (des, d.name)
        self._rebuild_tree()
        QMessageBox.information(self, APP_NAME, f"Узел вставлен. Новые обозначения ({len(numbers)}) показаны синим — "
                                "проверьте и нажмите «Переобозначить».")

    def _known_externals(self):
        """Внешние файлы, копии которых в изделии уже есть (без изменённых значений)."""
        root = self.project.root
        out = {}
        for rel, o in self.proj_settings.origins.items():
            if not o.get("values"):
                out[norm(o.get("source", ""))] = os.path.join(root, rel)
        return out

    def _record_origins(self, sources):
        if not sources:
            return
        root = self.project.root
        for copy, src in sources.items():
            self.proj_settings.add_origin(root, copy, src, {})
        self._save_settings()

    def make_autonomous(self):
        if self.project is None:
            return
        from kompas_manager.core.localize import external_refs

        ext = external_refs(self.project)
        if not ext:
            QMessageBox.information(self, APP_NAME, "Изделие уже автономно: все файлы лежат в его папке.")
            return
        names = "\n".join("  " + os.path.basename(v[0]) for v in list(ext.values())[:20])
        if QMessageBox.question(
                self, APP_NAME,
                f"Внешних файлов: {len(ext)}\n{names}\n\nСкопировать их в изделие (в папки сборок, которые на них "
                "ссылаются; один файл на всё изделие) и перепривязать ссылки?") != QMessageBox.Yes:
            return
        root = self.project.root
        docs = [self._path(k) for k in {k for v in ext.values() for k in v[1]}]
        show = self.act_show_kompas.isChecked()

        known = self._known_externals()

        def fn(K, log):
            from kompas_manager.autonomy_ops import localize

            return localize(K, root, docs, show=show, log=log, known=known)

        def done(result):
            created, missing, sources = result
            self._record_origins(sources)
            msg = f"Скопировано в изделие файлов: {len(created)}."
            if missing:
                msg += "\n\nНе найдены (ссылки остались битыми):\n" + "\n".join(missing[:15])
            QMessageBox.information(self, APP_NAME, msg)
            self.scan(force=False)

        self._run_call(fn, done, "Перенос внешних файлов в изделие")

    def archive_product(self):
        if self.project is None:
            return
        from kompas_manager.core.localize import archive_product, external_refs

        if external_refs(self.project):
            answer = QMessageBox.question(
                self, APP_NAME, "Изделие ссылается на файлы вне своей папки — в архиве их не будет. "
                "Сначала сделать изделие автономным?")
            if answer == QMessageBox.Yes:
                self.make_autonomous()
                return
        root = self.project.root
        default = os.path.join(os.path.dirname(root), os.path.basename(root) + ".zip")
        path, _ = QFileDialog.getSaveFileName(self, "Архив изделия", default, "Архив zip (*.zip)")
        if not path:
            return
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            n = archive_product(root, path)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Архив не создан:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, APP_NAME, f"Архив создан: {path}\nФайлов: {n} (без _versions, _backup, _old).")

    def level_up(self, head_key):
        from kompas_manager.ui.dialogs import LevelUpDialog

        p = self.project
        dlg = LevelUpDialog(p.doc(head_key), self.proj_settings, self)
        if not dlg.exec():
            return
        des, name = dlg.values()
        folder, head = p.root, self._path(head_key)
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.autonomy_ops import level_up

            return level_up(K, folder, des, name, head, show=show, log=log)

        self._run_call(fn, lambda _p: self.scan(force=False), "Создание уровня выше")

    def group_edit(self, keys):
        from kompas_manager.ui.dialogs import GroupEditDialog

        values = {}
        for k in keys:
            d = self.project.doc(k)
            values[k] = self.pending.get(k, (d.designation, d.name))
        dlg = GroupEditDialog(values, self)
        if not dlg.exec():
            return
        changed = 0
        for k, (des, name) in dlg.result_values().items():
            d = self.project.doc(k)
            if (des, name) == (d.designation, d.name):
                self.pending.pop(k, None)
            else:
                self.pending[k] = (des, name)
                changed += 1
        self._rebuild_tree()
        self.statusBar().showMessage(f"Изменено элементов: {changed}. Проверьте и нажмите «Переобозначить».", 8000)

    def _new_product_here(self):
        folder = self.workspace.current_folder()
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, APP_NAME, "Выберите слева раздел или папку проекта.")
            return
        self.new_product(folder)

    def edit_settings(self):
        from kompas_manager.ui.dialogs import SettingsDialog

        SettingsDialog(self.settings, self).exec()

    def new_product(self, parent_folder):
        from kompas_manager.ui.structure_dialog import StructureDialog

        if self.worker is not None:
            return
        dlg = StructureDialog(parent_folder, self)
        if not dlg.exec():
            return
        folder = dlg.folder()
        items = dlg.items
        settings = dlg.project_settings()
        os.makedirs(folder, exist_ok=True)
        try:
            settings.save(folder)
        except OSError as e:
            self.log.appendPlainText(f"Настройки изделия не сохранены: {e}")
        templates = {"part": self.settings.value("template_part", ""),
                     "assembly": self.settings.value("template_asm", "")}
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.structure_ops import create_structure

            return create_structure(K, items, templates, show=show, log=log)

        def done(created):
            self.statusBar().showMessage(f"Создано файлов: {len(created)}", 8000)
            self.workspace.select(folder)
            self.proj_settings = None
            self.project_root = None
            self.open_project(folder)

        self._run_call(fn, done, f"Создание изделия: {os.path.basename(folder)}")

    def check_copied_folder(self, old, new):
        show = self.act_show_kompas.isChecked()

        def fn(K, log):
            from kompas_manager.structure_ops import relink_copied_folder

            return relink_copied_folder(K, old, new, show=show, log=log)

        def done(n):
            msg = (f"Папка скопирована. Ссылок, которые вели в оригинал, перепривязано: {n}." if n else
                   "Папка скопирована. Все ссылки копии ведут на её собственные файлы или в библиотеку.")
            QMessageBox.information(self, APP_NAME, msg + f"\n\n{new}")

        from kompas_manager.ui.workspace_panel import has_kompas_files
        from kompas_manager.scanner import list_files

        if not list_files(new) and not has_kompas_files(new):
            return  # в папке нет файлов КОМПАСа — проверять нечего
        self._run_call(fn, done, "Проверка ссылок в копии")

    # ---------- прочее ----------

    def clear_cache(self):
        from kompas_manager.core.cache import ScanCache

        cache = ScanCache()
        cache.clear()
        cache.close()
        self.statusBar().showMessage("Кэш очищен: при следующем обновлении все файлы будут прочитаны заново", 6000)

    def about(self):
        QMessageBox.about(
            self,
            APP_NAME,
            f"<b>{APP_NAME}</b><br>Версия {__version__}<br><br>"
            "Проекты, обозначения и библиотеки для КОМПАС-3D.",
        )

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        self.act_open.setEnabled(not busy)
        self.act_refresh.setEnabled(not busy and bool(self.project_root))
        self.act_rescan.setEnabled(not busy and bool(self.project_root))
        self.menu_recent.setEnabled(not busy)
        if hasattr(self, "library"):
            self.library.setEnabled(not busy)
        has_project = not busy and self.project is not None
        for act in (self.act_scheme, self.act_apply_scheme, self.act_find, self.act_rollback):
            act.setEnabled(has_project)
        self.tree.setEditTriggers(
            QAbstractItemView.NoEditTriggers if busy
            else QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self._update_pending_actions()
        if busy:
            self.progress.setMaximum(0)  # неопределённый прогресс, пока не известно число файлов

    def _update_title(self):
        if self.project_root:
            self.setWindowTitle(f"{os.path.basename(self.project_root)} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)

    def _recent(self):
        value = self.settings.value("recent", [])
        if isinstance(value, str):
            value = [value]
        return [v for v in (value or []) if v]

    def _add_recent(self, path):
        recent = [path] + [r for r in self._recent() if os.path.normcase(r) != os.path.normcase(path)]
        self.settings.setValue("recent", recent[:MAX_RECENT])
        self._fill_recent_menu()

    def _remove_recent(self, path):
        self.settings.setValue("recent", [r for r in self._recent() if r != path])
        self._fill_recent_menu()

    def _fill_recent_menu(self):
        self.menu_recent.clear()
        recent = self._recent()
        for path in recent:
            self.menu_recent.addAction(path, lambda p=path: self.open_project(p))
        self.menu_recent.setEnabled(bool(recent))

    def closeEvent(self, event):
        if self.worker is not None:
            QMessageBox.information(self, APP_NAME, "Идёт операция с КОМПАСом. Дождитесь окончания.")
            event.ignore()
            return
        if self.pending and not self._confirm_discard():
            event.ignore()
            return
        event.accept()
