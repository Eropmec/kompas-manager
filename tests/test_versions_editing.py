import os

from kompas_manager.core.editing import plan_append, plan_delete
from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.core.structure import Node
from kompas_manager.core.versions import extract_version, list_versions, move_to_old, plan_restore, related, save_version
from test_project import doc


def make(root, files=True):
    docs = [
        doc(root, "Г.000.00 - Аппарат.a3d", "assembly", "Г.000.00", "Аппарат",
            ["Узел/Г.001.00 - Узел ввода.a3d", "Г.000.01 - Корпус.m3d"]),
        doc(root, "Узел/Г.001.00 - Узел ввода.a3d", "assembly", "Г.001.00", "Узел ввода",
            ["Узел/Г.001.01 - Патрубок.m3d", "Г.000.01 - Корпус.m3d"]),
        doc(root, "Узел/Г.001.01 - Патрубок.m3d", "part", "Г.001.01", "Патрубок"),
        doc(root, "Узел/Г.001.01 - Патрубок.cdw", "drawing", "Г.001.01", "Патрубок", ["Узел/Г.001.01 - Патрубок.m3d"]),
        doc(root, "Г.000.01 - Корпус.m3d", "part", "Г.000.01", "Корпус"),
    ]
    if files:
        for d in docs:
            os.makedirs(os.path.dirname(d.path), exist_ok=True)
            with open(d.path, "w", encoding="utf-8") as f:
                f.write("v1 " + os.path.basename(d.path))
    return Project(root, docs), docs


def k(root, rel):
    return norm(os.path.join(root, rel))


def test_save_and_restore_version(tmp_path):
    root = str(tmp_path)
    p, docs = make(root)
    node = k(root, "Узел/Г.001.00 - Узел ввода.a3d")
    v = save_version(p, node, "до переделки")
    assert sorted(v.files) == ["Г.000.01 - Корпус.m3d", "Узел/Г.001.00 - Узел ввода.a3d",
                               "Узел/Г.001.01 - Патрубок.cdw", "Узел/Г.001.01 - Патрубок.m3d"]
    assert [x.comment for x in list_versions(root)] == ["до переделки"]
    assert related(v, p, node)

    # «Новая конструкция»: другой файл узла, другая деталь
    new_docs = [d for d in docs if "Узел" not in d.path and "Аппарат" not in d.path] + [
        doc(root, "Г.000.00 - Аппарат.a3d", "assembly", "Г.000.00", "Аппарат",
            ["Узел/Г.001.00 - Узел ввода новый.a3d", "Г.000.01 - Корпус.m3d"]),
        doc(root, "Узел/Г.001.00 - Узел ввода новый.a3d", "assembly", "Г.001.00", "Узел ввода новый",
            ["Узел/Г.001.03 - Штуцер.m3d"]),
        doc(root, "Узел/Г.001.03 - Штуцер.m3d", "part", "Г.001.03", "Штуцер"),
    ]
    for f in ("Узел/Г.001.00 - Узел ввода новый.a3d", "Узел/Г.001.03 - Штуцер.m3d"):
        open(os.path.join(root, f), "w").close()
    with open(os.path.join(root, "Узел/Г.001.01 - Патрубок.m3d"), "w") as f:
        f.write("v2")
    p2 = Project(root, new_docs)
    cur = k(root, "Узел/Г.001.00 - Узел ввода новый.a3d")
    assert related(v, p2, cur)  # то же обозначение
    plan = plan_restore(p2, v, cur)
    assert [os.path.basename(x) for x in plan.orphans] == ["Г.001.00 - Узел ввода новый.a3d", "Г.001.03 - Штуцер.m3d"]
    assert [os.path.basename(x) for x in plan.parents] == ["Г.000.00 - Аппарат.a3d"]
    assert plan.relink == {cur: os.path.join(root, "Узел", "Г.001.00 - Узел ввода.a3d")}
    extract_version(v, root)
    assert open(os.path.join(root, "Узел/Г.001.01 - Патрубок.m3d"), encoding="utf-8").read().startswith("v1")
    moved = move_to_old(root, plan.orphans)
    assert len(moved) == 2 and not os.path.exists(os.path.join(root, "Узел/Г.001.03 - Штуцер.m3d"))


def test_plan_delete(tmp_path):
    root = str(tmp_path)
    p, _ = make(root, files=False)
    plan = plan_delete(p, k(root, "Г.000.00 - Аппарат.a3d"), k(root, "Узел/Г.001.00 - Узел ввода.a3d"))
    assert plan.instances == 1
    assert sorted(os.path.basename(f) for f in plan.files) == [
        "Г.001.00 - Узел ввода.a3d", "Г.001.01 - Патрубок.cdw", "Г.001.01 - Патрубок.m3d"]
    assert [os.path.basename(f) for f in plan.kept] == ["Г.000.01 - Корпус.m3d"]  # корпус есть и в аппарате
    plan = plan_delete(p, k(root, "Узел/Г.001.00 - Узел ввода.a3d"), k(root, "Г.000.01 - Корпус.m3d"))
    assert plan.files == [] and len(plan.kept) == 1


def test_plan_append(tmp_path):
    root = str(tmp_path)
    p, _ = make(root, files=False)
    asm = k(root, "Узел/Г.001.00 - Узел ввода.a3d")
    new = [Node("part", "Фланец", count=2), Node("assembly", "Опора", [Node("part", "Лапа")])]
    plan = plan_append(p, asm, new, ProjectSettings(code="Г"))
    names = [os.path.basename(i.path) for i in plan.items]
    assert names == ["Г.001.02 - Фланец.m3d", "Г.002.01 - Лапа.m3d", "Г.002.00 - Опора.a3d"]
    assert [(os.path.basename(x), c) for x, c in plan.direct] == [("Г.001.02 - Фланец.m3d", 2), ("Г.002.00 - Опора.a3d", 1)]
    assert plan.problems == []
