"""Выполнение переобозначения с подменённым Kompas API: файлы на диске, ссылки, штампы, откат."""
import os
import shutil
import types

from kompas_manager import renamer
from kompas_manager.core.backup import Backup
from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.rename_plan import build_plan
from test_project import doc

# «Содержимое» файлов в фейковом КОМПАСе: путь -> словарь свойств и ссылок
STORE = {}


class FakeComp:
    def __init__(self, store, i):
        self.store, self.i = store, i

    @property
    def FileName(self):
        return self.store["refs"][self.i]

    @FileName.setter
    def FileName(self, v):
        self.store["refs"][self.i] = v

    def Update(self):
        pass


class FakeDoc:
    def __init__(self, path):
        self.path = path
        self.data = {k: (list(v) if isinstance(v, list) else v) for k, v in STORE[norm(path)].items()}

    def Save(self):
        STORE[norm(self.path)] = self.data
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("+")

    def SaveAs(self, path):
        shutil.copy2(self.path, path)
        STORE[norm(path)] = self.data
        return True


def fake_api(calls):
    K = types.SimpleNamespace()

    class Session:
        def __init__(self, show=False, log=print):
            self.app = object()

        def close(self, log=print):
            pass

    def open_doc(app, path, visible=False, readonly=True):
        calls.append(("open", os.path.basename(path)))
        if norm(path) not in STORE:  # скопированный shutil'ом файл: свойства как у оригинала
            raise RuntimeError("нет данных")
        return FakeDoc(path)

    K.Session = Session
    K.find_open = lambda app, path: None
    K.open_doc = open_doc
    K.close_doc = lambda d: None
    K.read_props = lambda d: (d.data["des"], d.data["name"])

    def write_props(d, des, name):
        d.data["des"], d.data["name"] = des, name

    K.write_props = write_props
    K.components = lambda d: [FakeComp(d.data, i) for i in range(len(d.data["refs"]))]
    K.rebuild_3d = lambda d: None
    K.rebuild_2d = lambda d: None

    class View:
        def __init__(self, d, i):
            self.d, self.i = d, i

        @property
        def SourceFileName(self):
            return self.d.data["refs"][self.i]

        @SourceFileName.setter
        def SourceFileName(self, v):
            self.d.data["refs"][self.i] = v

        def Update(self):
            pass

    K.association_views = lambda d: [(None, View(d, i)) for i in range(len(d.data["refs"]))]

    def spec_relink(d, links):
        n = 0
        for i, r in enumerate(d.data["refs"]):
            if norm(r) in links:
                d.data["refs"][i] = links[norm(r)]
                n += 1
        return n

    K.spec_relink = spec_relink
    K.stamp_values = lambda d: (d.data["des"], d.data["name"])
    K.write_stamp = write_props
    return K


def setup(tmp_path):
    root = str(tmp_path)
    docs = [
        doc(root, "Э.0 - Изделие.a3d", "assembly", "Э.0", "Изделие", ["Э.1 - Втулка.m3d"]),
        doc(root, "Э.1 - Втулка.m3d", "part", "Э.1", "Втулка"),
        doc(root, "Э.1 - Втулка.cdw", "drawing", "Э.1", "Втулка", ["Э.1 - Втулка.m3d"]),
        doc(root, "Э.0 - Изделие.spw", "spec", "Э.0", "Изделие", ["Э.0 - Изделие.a3d"]),
    ]
    STORE.clear()
    for d in docs:
        with open(d.path, "w", encoding="utf-8") as f:
            f.write(os.path.basename(d.path))
        STORE[norm(d.path)] = {"des": d.designation, "name": d.name, "refs": list(d.refs)}
    return root, Project(root, docs)


def copy_store_on_copy(monkeypatch):
    real = shutil.copy2

    def copy2(src, dst, *a, **kw):
        out = real(src, dst, *a, **kw)
        if norm(src) in STORE and norm(dst) not in STORE:
            STORE[norm(dst)] = {k: (list(v) if isinstance(v, list) else v) for k, v in STORE[norm(src)].items()}
        return out

    monkeypatch.setattr(renamer.shutil, "copy2", copy2)


def test_execute_and_rollback(tmp_path, monkeypatch):
    root, p = setup(tmp_path)
    copy_store_on_copy(monkeypatch)
    plan = build_plan(p, {
        norm(os.path.join(root, "Э.1 - Втулка.m3d")): ("АБВГ.000.01", "Втулка"),
        norm(os.path.join(root, "Э.0 - Изделие.a3d")): ("АБВГ.000.00", "Насос"),
    })
    assert plan.errors == []
    calls = []
    res = renamer.execute(plan, fake_api(calls), log=lambda *_: None)
    assert res.errors == [] and res.done

    files = sorted(f for f in os.listdir(root) if not f.startswith("_"))
    assert files == [
        "АБВГ.000.00 - Насос.a3d",
        "АБВГ.000.00 - Насос.spw",
        "АБВГ.000.01 - Втулка.cdw",
        "АБВГ.000.01 - Втулка.m3d",
    ]
    new_part = os.path.join(root, "АБВГ.000.01 - Втулка.m3d")
    new_asm = os.path.join(root, "АБВГ.000.00 - Насос.a3d")
    assert STORE[norm(new_asm)]["refs"] == [new_part]
    assert STORE[norm(new_asm)]["des"] == "АБВГ.000.00"
    assert STORE[norm(os.path.join(root, "АБВГ.000.01 - Втулка.cdw"))]["refs"] == [new_part]
    spec = STORE[norm(os.path.join(root, "АБВГ.000.00 - Насос.spw"))]
    assert spec["refs"] == [new_asm] and spec["name"] == "Насос"

    errors = Backup.latest(root).rollback(log=lambda *_: None)
    assert errors == []
    files = sorted(f for f in os.listdir(root) if not f.startswith("_"))
    assert files == ["Э.0 - Изделие.a3d", "Э.0 - Изделие.spw", "Э.1 - Втулка.cdw", "Э.1 - Втулка.m3d"]


def test_open_files_block(tmp_path):
    root, p = setup(tmp_path)
    plan = build_plan(p, {norm(os.path.join(root, "Э.1 - Втулка.m3d")): ("А.1", "Втулка")})
    K = fake_api([])
    K.find_open = lambda app, path: object() if path.endswith(".m3d") else None
    res = renamer.execute(plan, K, log=lambda *_: None)
    assert res.errors and "Закройте" in res.errors[0]
    assert not os.path.isdir(os.path.join(root, "_backup"))
