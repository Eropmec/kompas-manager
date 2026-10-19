"""Операции библиотеки с подменённым Kompas API."""
import os
import shutil
import types

from kompas_manager import library_ops
from kompas_manager.core.library import Element, plan_extract, plan_insert
from kompas_manager.core.model import norm
from test_library import dnishe_passport

STORE = {}  # путь -> {"des", "name", "vars": {имя: значение}, "comps": [[файл, {перем.}]]}


class Doc:
    def __init__(self, path):
        self.path = path
        src = STORE[norm(path)]
        self.data = {"des": src["des"], "name": src["name"], "vars": dict(src["vars"]),
                     "comps": [[f, dict(v)] for f, v in src.get("comps", [])]}

    def Save(self):
        STORE[norm(self.path)] = self.data


class Comp:
    def __init__(self, doc, i):
        self.doc, self.i = doc, i

    @property
    def FileName(self):
        return self.doc.data["comps"][self.i][0]

    @FileName.setter
    def FileName(self, v):
        self.doc.data["comps"][self.i][0] = v

    def Update(self):
        pass


def var_list(values):
    return [{"name": n, "value": v, "expression": str(v), "external": True, "info": n == "YES", "note": ""}
            for n, v in values.items()]


def fake_api():
    K = types.SimpleNamespace()

    class Session:
        def __init__(self, show=False, log=print):
            self.app = object()

        def close(self, log=print):
            pass

    K.Session = Session
    K.open_doc = lambda app, path, visible=False, readonly=True: Doc(path)
    K.close_doc = lambda d: None
    K.read_props = lambda d: (d.data["des"], d.data["name"])

    def write_props(d, des, name):
        d.data["des"], d.data["name"] = des, name

    K.write_props = write_props
    K.top_part = lambda d: ("top", d)
    K.components = lambda d: [Comp(d, i) for i in range(len(d.data["comps"]))]

    def variables(part, external=True, in_source=True):
        if isinstance(part, tuple):
            return var_list(part[1].data["vars"])
        return var_list(part.doc.data["comps"][part.i][1])  # компонент: значения в сборке

    K.variables = variables

    def set_variables(d, values, log=print):
        d.data["vars"].update(values)
        d.data["vars"]["YES"] = 1.0 if d.data["vars"].get("ISP", 0) > 1 else 0.0
        return "fake"

    K.set_variables = set_variables
    K.rebuild_3d = lambda d: None
    return K


def setup(tmp_path, monkeypatch):
    STORE.clear()
    lib = tmp_path / "Lib"
    proj = tmp_path / "Проект"
    lib.mkdir()
    proj.mkdir()
    model = str(lib / "Днище.m3d")
    open(model, "w").write("m")
    STORE[norm(model)] = {"des": "BTEL.D1000S10", "name": "Днище эллиптическое 2-1000-10",
                          "vars": {"D": 1000.0, "s": 10.0, "ISP": 2.0, "h": 50.0, "YES": 1.0}}
    real = shutil.copy2

    def copy2(src, dst, *a, **kw):
        out = real(src, dst, *a, **kw)
        if norm(src) in STORE:
            s = STORE[norm(src)]
            STORE[norm(dst)] = {"des": s["des"], "name": s["name"], "vars": dict(s["vars"]),
                                "comps": [[f, dict(v)] for f, v in s.get("comps", [])]}
        return out

    monkeypatch.setattr(library_ops.shutil, "copy2", copy2)
    real_replace = os.replace

    def replace(src, dst):
        real_replace(src, dst)
        if norm(src) in STORE:
            STORE[norm(dst)] = STORE.pop(norm(src))

    monkeypatch.setattr(library_ops.os, "replace", replace)
    return model, str(proj)


def test_insert_copy(tmp_path, monkeypatch):
    model, proj = setup(tmp_path, monkeypatch)
    element = Element(model, dnishe_passport())
    plan = plan_insert(element, {"D": "800", "s": "8"}, proj)
    path = library_ops.insert_copy(fake_api(), plan, element, log=lambda *_: None)
    assert os.path.basename(path) == "BTEL.D800S8 - Днище эллиптическое 2-800-8.m3d"
    data = STORE[norm(path)]
    assert data["vars"]["D"] == 800.0 and data["vars"]["h"] == 50.0
    assert (data["des"], data["name"]) == ("BTEL.D800S8", "Днище эллиптическое 2-800-8")
    assert STORE[norm(model)]["vars"]["D"] == 1000.0  # оригинал не изменился
    assert [f for f in os.listdir(proj) if f.startswith("_tmp_")] == []


def test_extract_instances(tmp_path, monkeypatch):
    model, proj = setup(tmp_path, monkeypatch)
    asm = os.path.join(proj, "Сборка.a3d")
    open(asm, "w").write("a")
    base = STORE[norm(model)]["vars"]
    STORE[norm(asm)] = {"des": "А.0", "name": "Сборка", "vars": {}, "comps": [
        [model, dict(base, D=800.0, s=8.0)],
        [model, dict(base)],
        [model, dict(base, D=800.0, s=8.0)],
    ]}
    K = fake_api()
    comps, fvals, fprops = library_ops.analyze_assembly(K, asm, log=lambda *_: None)
    passports = {model: dnishe_passport()}
    groups = plan_extract(comps, fvals, fprops, proj, passports)
    assert len(groups) == 1 and groups[0].instances == [0, 2]
    library_ops.extract_instances(K, proj, asm, groups, passports, log=lambda *_: None)
    new = groups[0].target
    comps_after = STORE[norm(asm)]["comps"]
    assert [os.path.basename(c[0]) for c in comps_after] == [
        os.path.basename(new), "Днище.m3d", os.path.basename(new)]
    assert STORE[norm(new)]["vars"]["D"] == 800.0
    assert STORE[norm(new)]["des"] == "BTEL.D800S8"
    assert os.path.isdir(os.path.join(proj, "_backup"))
