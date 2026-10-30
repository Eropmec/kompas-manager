"""Удаление, добавление и восстановление версий с подменённым Kompas API."""
import os

from kompas_manager import editing_ops
from kompas_manager.core.editing import plan_append, plan_delete
from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.core.structure import Node
from kompas_manager.core.versions import plan_restore, save_version
from test_project import doc
from test_structure_ops import FILES, fake


def setup(root):
    FILES.clear()
    docs = [
        doc(root, "Г.000.00 - Аппарат.a3d", "assembly", "Г.000.00", "Аппарат", ["Г.001.00 - Узел.a3d", "Г.000.01 - Корпус.m3d"]),
        doc(root, "Г.001.00 - Узел.a3d", "assembly", "Г.001.00", "Узел", ["Г.001.01 - Патрубок.m3d", "Г.001.01 - Патрубок.m3d"]),
        doc(root, "Г.001.01 - Патрубок.m3d", "part", "Г.001.01", "Патрубок"),
        doc(root, "Г.000.01 - Корпус.m3d", "part", "Г.000.01", "Корпус"),
    ]
    for d in docs:
        with open(d.path, "w", encoding="utf-8") as f:
            f.write(os.path.basename(d.path))
        FILES[norm(d.path)] = {"des": d.designation, "name": d.name, "refs": list(d.refs)}
    return Project(root, docs)


def k(root, rel):
    return norm(os.path.join(root, rel))


def K():
    api = fake()
    api.delete_component = lambda c, log=print: c.d.data["refs"].pop(c.i) and "fake"
    api.rebuild_3d = lambda d: None
    return api


def test_delete_from_assembly(tmp_path):
    root = str(tmp_path)
    p = setup(root)
    plan = plan_delete(p, k(root, "Г.000.00 - Аппарат.a3d"), k(root, "Г.001.00 - Узел.a3d"))
    editing_ops.delete_from_assembly(K(), root, plan, log=lambda *_: None)
    assert [os.path.basename(r) for r in FILES[k(root, "Г.000.00 - Аппарат.a3d")]["refs"]] == ["Г.000.01 - Корпус.m3d"]
    assert not os.path.exists(os.path.join(root, "Г.001.00 - Узел.a3d"))
    assert not os.path.exists(os.path.join(root, "Г.001.01 - Патрубок.m3d"))
    assert os.path.exists(os.path.join(root, "Г.000.01 - Корпус.m3d"))


def test_append_to_assembly(tmp_path):
    root = str(tmp_path)
    p = setup(root)
    plan = plan_append(p, k(root, "Г.001.00 - Узел.a3d"), [Node("part", "Фланец", count=2)], ProjectSettings(code="Г"))
    assert plan.problems == []
    editing_ops.append_to_assembly(K(), root, plan, log=lambda *_: None)
    refs = [os.path.basename(r) for r in FILES[k(root, "Г.001.00 - Узел.a3d")]["refs"]]
    assert refs == ["Г.001.01 - Патрубок.m3d"] * 2 + ["Г.001.02 - Фланец.m3d"] * 2
    assert FILES[k(root, "Г.001.02 - Фланец.m3d")]["des"] == "Г.001.02"


def test_restore_version(tmp_path):
    root = str(tmp_path)
    p = setup(root)
    v = save_version(p, k(root, "Г.001.00 - Узел.a3d"), "старый")
    # новая версия узла под другим именем файла, родитель ссылается на неё
    new_asm = os.path.join(root, "Г.001.00 - Узел новый.a3d")
    open(new_asm, "w").close()
    FILES[norm(new_asm)] = {"des": "Г.001.00", "name": "Узел новый", "refs": []}
    FILES[k(root, "Г.000.00 - Аппарат.a3d")]["refs"][0] = new_asm
    os.remove(os.path.join(root, "Г.001.00 - Узел.a3d"))
    docs = [
        doc(root, "Г.000.00 - Аппарат.a3d", "assembly", "Г.000.00", "Аппарат", [new_asm, "Г.000.01 - Корпус.m3d"]),
        doc(root, "Г.001.00 - Узел новый.a3d", "assembly", "Г.001.00", "Узел новый"),
        doc(root, "Г.000.01 - Корпус.m3d", "part", "Г.000.01", "Корпус"),
    ]
    p2 = Project(root, docs)
    plan = plan_restore(p2, v, norm(new_asm))
    editing_ops.restore_version(K(), p2, plan, log=lambda *_: None)
    assert os.path.exists(os.path.join(root, "Г.001.00 - Узел.a3d"))
    assert not os.path.exists(new_asm)  # убран в _old
    assert FILES[k(root, "Г.000.00 - Аппарат.a3d")]["refs"][0] == os.path.join(root, "Г.001.00 - Узел.a3d")
    assert len(os.listdir(os.path.join(root, "_versions"))) == 2  # старая + автосохранение


def test_delete_falls_back_to_api5(tmp_path):
    root = str(tmp_path)
    p = setup(root)
    api = K()

    def fail7(c, log=print):
        raise RuntimeError("API7 не умеет")

    def del5(d, path, log=print, limit=None):
        before = len(d.data["refs"])
        d.data["refs"] = [r for r in d.data["refs"] if norm(r) != norm(path)]
        return before - len(d.data["refs"])

    api.delete_component, api.delete_components5 = fail7, del5
    head = k(root, "Г.000.00 - Аппарат.a3d")
    plan = plan_delete(p, head, k(root, "Г.000.01 - Корпус.m3d"), with_files=False)
    assert editing_ops.delete_from_assembly(api, root, plan, log=lambda *_: None) == 1
    assert [os.path.basename(r) for r in FILES[head]["refs"]] == ["Г.001.00 - Узел.a3d"]


def test_delete_nothing_saved_when_kompas_refuses(tmp_path):
    import pytest

    root = str(tmp_path)
    p = setup(root)
    api = K()
    saved = []

    def fail(*a, **kw):
        raise RuntimeError("нет")

    api.delete_component = fail
    api.delete_components5 = fail
    head = k(root, "Г.000.00 - Аппарат.a3d")
    real_open = api.open_doc

    def open_doc(app, path, visible=False, readonly=True):
        d = real_open(app, path, visible, readonly)
        d.Save = lambda: saved.append(path)
        return d

    api.open_doc = open_doc
    plan = plan_delete(p, head, k(root, "Г.001.00 - Узел.a3d"))
    with pytest.raises(RuntimeError):
        editing_ops.delete_from_assembly(api, root, plan, log=lambda *_: None)
    assert saved == []
    assert os.path.exists(os.path.join(root, "Г.001.00 - Узел.a3d"))  # файлы не тронуты


def test_delete_several(tmp_path):
    root = str(tmp_path)
    p = setup(root)
    head = k(root, "Г.000.00 - Аппарат.a3d")
    plans = [plan_delete(p, head, k(root, "Г.000.01 - Корпус.m3d")),
             plan_delete(p, k(root, "Г.001.00 - Узел.a3d"), k(root, "Г.001.01 - Патрубок.m3d"))]
    editing_ops.delete_from_assemblies(K(), root, plans, log=lambda *_: None)
    assert [os.path.basename(r) for r in FILES[head]["refs"]] == ["Г.001.00 - Узел.a3d"]
    assert FILES[k(root, "Г.001.00 - Узел.a3d")]["refs"] == []
    assert not os.path.exists(os.path.join(root, "Г.000.01 - Корпус.m3d"))


def test_move_occurrence(tmp_path):
    root = str(tmp_path)
    setup(root)
    head, sub = k(root, "Г.000.00 - Аппарат.a3d"), k(root, "Г.001.00 - Узел.a3d")
    part = k(root, "Г.001.01 - Патрубок.m3d")
    editing_ops.move_occurrence(K(), root, sub, head, part, log=lambda *_: None)
    assert [os.path.basename(r) for r in FILES[sub]["refs"]] == ["Г.001.01 - Патрубок.m3d"]  # было 2
    assert norm(FILES[head]["refs"][-1]) == part


def KM():
    """Фейк с положениями: у ссылки есть матрица (храним рядом со ссылками)."""
    from kompas_manager.core.geometry import IDENTITY

    api = K()
    mats = {}

    def get_matrix(c):
        return mats.get((norm(c.d.path), c.i), IDENTITY)

    def insert_part(d, path, m=None, log=print):
        d.data["refs"].append(path)
        if m is not None:
            mats[(norm(d.path), len(d.data["refs"]) - 1)] = tuple(m)
        return True

    api.get_matrix, api.insert_part, api.mats = get_matrix, insert_part, mats
    return api


def test_combine_and_destroy(tmp_path):
    from kompas_manager.core.geometry import IDENTITY

    root = str(tmp_path)
    setup(root)
    head = k(root, "Г.000.00 - Аппарат.a3d")
    body = os.path.join(root, "Г.000.01 - Корпус.m3d")
    api = KM()
    moved = IDENTITY[:12] + (50.0, 0.0, 0.0, 1.0)
    api.mats[(head, 1)] = moved  # корпус сдвинут на 50 по X
    new = os.path.join(root, "Г.002.00 - Обечайка.a3d")
    editing_ops.combine_to_subassembly(api, root, head, [body], new, "Г.002.00", "Обечайка", log=lambda *_: None)
    assert [os.path.basename(r) for r in FILES[head]["refs"]] == ["Г.001.00 - Узел.a3d", "Г.002.00 - Обечайка.a3d"]
    assert FILES[norm(new)]["refs"] == [body] and FILES[norm(new)]["des"] == "Г.002.00"
    assert api.mats[(norm(new), 0)] == moved  # положение сохранено внутри подсборки
    api.mats.clear()
    api.mats[(norm(new), 0)] = moved
    editing_ops.destroy_subassembly(api, root, head, new, log=lambda *_: None)
    assert [os.path.basename(r) for r in FILES[head]["refs"]] == ["Г.001.00 - Узел.a3d", "Г.000.01 - Корпус.m3d"]
    assert api.mats[(head, 2)] == moved  # вставлен третьим (до удаления подсборки) в своём положении
