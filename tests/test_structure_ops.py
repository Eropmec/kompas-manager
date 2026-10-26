"""Операции со структурой с подменённым Kompas API."""
import os
import types

from kompas_manager import structure_ops
from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.core.structure import Node, plan_files
from kompas_manager.core.transfer import plan_transfer
from test_project import doc

FILES = {}  # путь -> {"des","name","refs"}


class Doc:
    def __init__(self, path):
        self.path = path
        d = FILES.setdefault(norm(path), {"des": "", "name": "", "refs": []})
        self.data = {"des": d["des"], "name": d["name"], "refs": list(d["refs"])}

    def Save(self):
        FILES[norm(self.path)] = self.data
        if not os.path.exists(self.path):
            open(self.path, "w").close()

    def SaveAs(self, path):
        self.path = path
        self.Save()


class Ref:
    def __init__(self, d, i):
        self.d, self.i = d, i

    def _get(self):
        return self.d.data["refs"][self.i]

    def _set(self, v):
        self.d.data["refs"][self.i] = v

    FileName = property(_get, _set)
    SourceFileName = property(_get, _set)

    def Update(self):
        pass


def fake():
    K = types.SimpleNamespace()

    class Session:
        def __init__(self, show=False, log=print):
            self.app = object()

        def close(self, log=print):
            pass

    K.Session = Session

    def new_doc(app, path, visible=False):
        d = Doc(path)
        d.Save()
        return d

    K.new_doc = new_doc
    K.open_doc = lambda app, path, visible=False, readonly=True: Doc(path)
    K.close_doc = lambda d: None

    def write_props(d, des, name):
        d.data["des"], d.data["name"] = des, name

    K.write_props = write_props
    K.add_component = lambda d, path, log=print: d.data["refs"].append(path) or "fake"
    K.components = lambda d: [Ref(d, i) for i in range(len(d.data["refs"]))]
    K.association_views = lambda d: [(None, Ref(d, i)) for i in range(len(d.data["refs"]))]
    K.rebuild_2d = lambda d: None
    K.spec_attached = lambda d: list(d.data["refs"])

    def spec_relink(d, links):
        d.data["refs"] = [links.get(norm(r), r) for r in d.data["refs"]]
        return len(links)

    K.spec_relink = spec_relink
    K.references = lambda d, path: list(d.data["refs"])
    return K


def test_create_structure(tmp_path):
    FILES.clear()
    root = Node("assembly", "Аппарат", [Node("part", "Корпус"), Node("part", "Трубка", count=3)])
    items, problems = plan_files(root, str(tmp_path), ProjectSettings(code="ГГЕ"))
    assert problems == []
    created = structure_ops.create_structure(fake(), items, log=lambda *_: None)
    assert len(created) == 3 and all(os.path.exists(p) for p in created)
    asm = FILES[norm(str(tmp_path / "ГГЕ.000.00 - Аппарат.a3d"))]
    assert asm["des"] == "ГГЕ.000.00"
    assert [os.path.basename(r) for r in asm["refs"]] == ["ГГЕ.000.01 - Корпус.m3d"] + ["ГГЕ.000.02 - Трубка.m3d"] * 3


def test_transfer(tmp_path, monkeypatch):
    FILES.clear()
    real = structure_ops.shutil.copy2

    def copy2(a, b, *x, **k):
        real(a, b, *x, **k)
        if norm(a) in FILES:
            FILES[norm(b)] = {kk: (list(v) if isinstance(v, list) else v) for kk, v in FILES[norm(a)].items()}

    monkeypatch.setattr(structure_ops.shutil, "copy2", copy2)
    src = tmp_path / "А"
    (src / "Пучок").mkdir(parents=True)
    root = str(src)
    docs = [
        doc(root, "Пучок/А.001.00 - Пучок.a3d", "assembly", "А.001.00", "Пучок", ["Пучок/А.001.01 - Трубка.m3d"]),
        doc(root, "Пучок/А.001.01 - Трубка.m3d", "part", "А.001.01", "Трубка"),
        doc(root, "Пучок/А.001.01 - Трубка.cdw", "drawing", "А.001.01", "Трубка", ["Пучок/А.001.01 - Трубка.m3d"]),
    ]
    for d in docs:
        open(d.path, "w").close()
        FILES[norm(d.path)] = {"des": d.designation, "name": d.name, "refs": list(d.refs)}
    dst = tmp_path / "Б"
    dst.mkdir()
    target_asm = dst / "Б.000.00 - Изделие.a3d"
    open(target_asm, "w").close()
    FILES[norm(str(target_asm))] = {"des": "Б.000.00", "name": "Изделие", "refs": []}
    plan = plan_transfer(Project(root, docs), norm(docs[0].path), str(dst / "Узлы"))
    structure_ops.transfer(fake(), plan, str(dst), str(target_asm), log=lambda *_: None)
    new_asm = dst / "Узлы" / "А.001.00 - Пучок.a3d"
    new_part = str(dst / "Узлы" / "А.001.01 - Трубка.m3d")
    assert FILES[norm(str(new_asm))]["refs"] == [new_part]
    assert FILES[norm(str(dst / "Узлы" / "А.001.01 - Трубка.cdw"))]["refs"] == [new_part]
    assert FILES[norm(str(target_asm))]["refs"] == [str(new_asm)]
    assert FILES[norm(docs[0].path)]["refs"] == [docs[1].path]  # исходник не изменился


def test_relink_copied_folder(tmp_path):
    FILES.clear()
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        root.mkdir()
        open(root / "a.m3d", "w").close()
        open(root / "s.a3d", "w").close()
    FILES[norm(str(new / "s.a3d"))] = {"des": "", "name": "", "refs": [str(old / "a.m3d")]}
    n = structure_ops.relink_copied_folder(fake(), str(old), str(new), log=lambda *_: None)
    assert n == 1 and FILES[norm(str(new / "s.a3d"))]["refs"] == [str(new / "a.m3d")]
