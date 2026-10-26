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
