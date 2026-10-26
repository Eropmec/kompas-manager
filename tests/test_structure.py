import os

from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.core.structure import Node, plan_files
from kompas_manager.core.transfer import folder_relink_map, plan_transfer
from test_project import doc


def test_plan_files(tmp_path):
    root = Node("assembly", "Аппарат", [
        Node("part", "Корпус"),
        Node("assembly", "Пучок труб", [Node("part", "Трубка", count=12), Node("part", "Решётка", count=2)]),
        Node("part", "Крышка"),
    ])
    items, problems = plan_files(root, str(tmp_path), ProjectSettings(code="ГГЕ"))
    assert problems == []
    names = [os.path.basename(i.path) for i in items]
    assert names == [
        "ГГЕ.000.01 - Корпус.m3d",
        "ГГЕ.001.01 - Трубка.m3d",
        "ГГЕ.001.02 - Решётка.m3d",
        "ГГЕ.000.02 - Крышка.m3d",
        "ГГЕ.001.00 - Пучок труб.a3d",
        "ГГЕ.000.00 - Аппарат.a3d",
    ]
    bundle = items[4]
    assert [(os.path.basename(p), c) for p, c in bundle.components] == [
        ("ГГЕ.001.01 - Трубка.m3d", 12), ("ГГЕ.001.02 - Решётка.m3d", 2)]
    open(items[0].path, "w").close()
    _items, problems = plan_files(root, str(tmp_path), ProjectSettings(code="ГГЕ"))
    assert any("уже существует" in p for p in problems)


def test_manual_designation(tmp_path):
    root = Node("assembly", "А", [Node("part", "Б", designation="ОСОБОЕ.1")])
    items, _ = plan_files(root, str(tmp_path), ProjectSettings(code="К"))
    assert os.path.basename(items[0].path) == "ОСОБОЕ.1 - Б.m3d"


def test_plan_transfer(tmp_path):
    src = tmp_path / "Проект А"
    lib = tmp_path / "Lib"
    root = str(src)
    docs = [
        doc(root, "А.000.00 - Изделие.a3d", "assembly", "А.000.00", "Изделие", ["Пучок/А.001.00 - Пучок.a3d"]),
        doc(root, "Пучок/А.001.00 - Пучок.a3d", "assembly", "А.001.00", "Пучок",
            ["Пучок/А.001.01 - Трубка.m3d", str(lib / "Днище.m3d")]),
        doc(root, "Пучок/А.001.01 - Трубка.m3d", "part", "А.001.01", "Трубка"),
        doc(root, "Пучок/А.001.01 - Трубка.cdw", "drawing", "А.001.01", "Трубка", ["Пучок/А.001.01 - Трубка.m3d"]),
    ]
    p = Project(root, docs)
    target = tmp_path / "Проект Б" / "Узлы"
    plan = plan_transfer(p, norm(os.path.join(root, "Пучок/А.001.00 - Пучок.a3d")), str(target))
    rel = sorted(os.path.relpath(v, target) for v in plan.files.values())
    assert rel == ["А.001.00 - Пучок.a3d", "А.001.01 - Трубка.cdw", "А.001.01 - Трубка.m3d"]
    assert plan.problems == []
    assert os.path.basename(plan.new_root) == "А.001.00 - Пучок.a3d"


def test_folder_relink_map(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    (new / "sub").mkdir(parents=True)
    (new / "sub" / "a.m3d").write_text("x")
    refs = [str(old / "sub" / "a.m3d"), str(old / "missing.m3d"), str(tmp_path / "lib.m3d")]
    m = folder_relink_map(str(old), str(new), refs)
    assert m == {norm(refs[0]): str(new / "sub" / "a.m3d")}
