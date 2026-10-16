"""Главное окно: дерево проекта, проверки и журнал."""
import os
import subprocess
import sys

from PySide6.QtCore import QSettings, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHeaderView,
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
from kompas_manager.core.project import Project
from kompas_manager.ui.project_tree import KEY_ROLE, ProjectTreeBuilder, severity_icon

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

        self.act_clear_cache = QAction("Очистить кэш сканирования", self)
        self.act_clear_cache.triggered.connect(self.clear_cache)

        self.act_exit = QAction("Выход", self)
        self.act_exit.triggered.connect(self.close)

        self.act_about = QAction("О программе", self)
        self.act_about.triggered.connect(self.about)

        menu = self.menuBar()
        m_file = menu.addMenu("Файл")
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

        m_tools = menu.addMenu("Сервис")
        m_tools.addAction(self.act_show_kompas)
        m_tools.addAction(self.act_clear_cache)

        m_help = menu.addMenu("Справка")
        m_help.addAction(self.act_about)

        toolbar = QToolBar("Основная")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.addAction(self.act_open)
        toolbar.addAction(self.act_refresh)
        toolbar.addSeparator()
        toolbar.addAction(self.act_expand)
        toolbar.addAction(self.act_collapse)
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
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.doubleClicked.connect(self._tree_double_clicked)
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
        self.setCentralWidget(central)

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
        self.project_root = path
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

    def show_project(self, project):
        """Показать проект в дереве и на вкладке проверок."""
        self.project = project
        self.project_root = project.root
        builder = ProjectTreeBuilder(project, self.style())
        model = builder.build()
        self.items_by_key = builder.items_by_key
        self.proxy.setSourceModel(model)
        self.tree.expandToDepth(1)
        header = self.tree.header()
        for col in range(model.columnCount()):
            self.tree.resizeColumnToContents(col)
        header.setStretchLastSection(True)
        self._fill_issues()
        self._update_counts()
        self._update_title()
        self._apply_filter(self.filter_edit.text())

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
        key = self._key_at(index)
        if key:
            self.open_in_kompas(key)

    def _tree_menu(self, pos):
        key = self._key_at(self.tree.indexAt(pos))
        if not key or self.project is None:
            return
        p = self.project
        d = p.doc(key)
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
            QMessageBox.information(self, APP_NAME, "Идёт сканирование. Остановите его и дождитесь окончания.")
            event.ignore()
            return
        event.accept()
