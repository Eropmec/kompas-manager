"""Фоновые операции с КОМПАСом, чтобы окно не зависало."""
import gc
import traceback

from PySide6.QtCore import QThread, Signal


class CallWorker(QThread):
    """Выполняет функцию fn(K, log) с КОМПАСом в отдельном потоке."""

    log = Signal(str)
    done = Signal(object, str)  # результат, текст ошибки (пусто при успехе)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        result, error = None, ""
        com = None
        try:
            import pythoncom as com

            com.CoInitialize()
        except ImportError:
            com = None
        try:
            from kompas_manager import kompas_api as K

            result = self.fn(K, self.log.emit)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            self.log.emit("Ошибка:\n" + traceback.format_exc())
        finally:
            gc.collect()
            if com is not None:
                com.CoUninitialize()
        self.done.emit(result, error)


class RenameWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int, str)
    done = Signal(object)  # RenameResult или None при критической ошибке

    def __init__(self, plan, show=False):
        super().__init__()
        self.plan = plan
        self.show = show

    def run(self):
        result = None
        com = None
        try:
            import pythoncom as com

            com.CoInitialize()
        except ImportError:
            com = None
        try:
            from kompas_manager import kompas_api as K
            from kompas_manager.renamer import execute

            result = execute(self.plan, K, show=self.show, log=self.log.emit, progress=self.progress.emit)
        except Exception:
            self.log.emit("Ошибка переобозначения:\n" + traceback.format_exc())
        finally:
            gc.collect()
            if com is not None:
                com.CoUninitialize()
        self.done.emit(result)


class ScanWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int, str)
    done = Signal(object, bool)  # список DocInfo, завершено полностью

    def __init__(self, root, show=False, force=False):
        super().__init__()
        self.root = root
        self.show = show
        self.force = force
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        docs, complete = [], False
        com = None
        try:
            import pythoncom as com

            com.CoInitialize()
        except ImportError:
            com = None
        try:
            from kompas_manager.core.cache import ScanCache
            from kompas_manager.scanner import scan

            cache = ScanCache()
            try:
                docs, complete = scan(
                    self.root,
                    cache,
                    show=self.show,
                    force=self.force,
                    log=self.log.emit,
                    progress=self.progress.emit,
                    cancelled=lambda: self._cancel,
                )
            finally:
                cache.close()
        except Exception:
            self.log.emit("Ошибка сканирования:\n" + traceback.format_exc())
        finally:
            gc.collect()  # освободить COM-объекты до CoUninitialize
            if com is not None:
                com.CoUninitialize()
        self.done.emit(docs, complete)
