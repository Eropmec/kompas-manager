"""Тест сканера с подменённым Kompas API: кэш и запуск КОМПАСа только при необходимости."""
import os
import sys
import types

from kompas_manager import scanner
from kompas_manager.core.cache import ScanCache


def make_fake_api(sessions, reads):
    K = types.ModuleType("kompas_manager.kompas_api")

    class Session:
        def __init__(self, show=False, log=print):
            sessions.append(self)
            self.app = object()

        def close(self, log=print):
            pass

    K.Session = Session
    K.open_for_reading = lambda app, path: (path, True)
    K.close_doc = lambda doc: None

    def read_props(doc):
        reads.append(doc)
        return "АБВГ.000.01", "Плита"

    K.read_props = read_props
    K.stamp_values = lambda doc: ("АБВГ.000.01", "Плита")
    K.references = lambda doc, path: [path.replace(".a3d", ".m3d")] if path.endswith(".a3d") else []
    return K


def test_scan_uses_cache(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "_old").mkdir(parents=True)
    (root / "a.m3d").write_text("1")
    (root / "a.a3d").write_text("2")
    (root / "_old" / "ignored.m3d").write_text("3")
    (root / "notes.txt").write_text("4")

    sessions, reads = [], []
    monkeypatch.setitem(sys.modules, "kompas_manager.kompas_api", make_fake_api(sessions, reads))
    import kompas_manager

    monkeypatch.setattr(kompas_manager, "kompas_api", sys.modules["kompas_manager.kompas_api"], raising=False)
    cache = ScanCache(str(tmp_path / "cache.sqlite3"))

    docs, complete = scanner.scan(str(root), cache, log=lambda *_: None)
    assert complete
    assert sorted(os.path.basename(d.path) for d in docs) == ["a.a3d", "a.m3d"]
    assert len(sessions) == 1

    # Повторное сканирование без изменений: КОМПАС не нужен
    docs2, _ = scanner.scan(str(root), cache, log=lambda *_: None)
    assert len(sessions) == 1
    assert {d.designation for d in docs2} == {"АБВГ.000.01"}

    # Изменённый файл перечитывается
    (root / "a.m3d").write_text("changed content")
    reads.clear()
    scanner.scan(str(root), cache, log=lambda *_: None)
    assert len(sessions) == 2
    assert [os.path.basename(r) for r in reads] == ["a.m3d"]
    cache.close()
