import os

from kompas_manager.core.model import norm
from kompas_manager.core.numbering import assign
from kompas_manager.core.project import Project
from kompas_manager.core.schemes import Scheme
from kompas_manager.core.settings import ProjectSettings
from test_project import doc


def tree(root):
    # Изделие: Узел1 (Втулка ×2, Ось), Плита, Узел2 (Подузел (Шайба), Ось — общая)
    return [
        doc(root, "Изделие.a3d", "assembly", "Э.0", "Изделие", ["Узел1.a3d", "Плита.m3d", "Узел2.a3d"]),
        doc(root, "Узел1.a3d", "assembly", "Э.1", "Узел1", ["Втулка.m3d", "Втулка.m3d", "Ось.m3d"]),
        doc(root, "Узел2.a3d", "assembly", "Э.2", "Узел2", ["Подузел.a3d", "Ось.m3d"]),
        doc(root, "Подузел.a3d", "assembly", "Э.3", "Подузел", ["Шайба.m3d"]),
        doc(root, "Втулка.m3d", "part", "Э.4", "Втулка"),
        doc(root, "Ось.m3d", "part", "Э.5", "Ось"),
        doc(root, "Плита.m3d", "part", "Э.6", "Плита"),
        doc(root, "Шайба.m3d", "part", "Э.7", "Шайба"),
    ]


def by_name(project, result):
    return {project.doc(k).name: v for k, v in result.items()}


def test_scheme_format_and_validate():
    s = Scheme("x", "{код}.{сборка:3}.{деталь:2}")
    assert s.format("АБВГ", 1, 1) == "АБВГ.001.01"
    assert s.validate() == []
    assert Scheme("x", "{код}.{сборка}").validate()
    assert Scheme("x", "{сборка}.{деталь}.{исп}").validate()


def test_assign_hierarchy(tmp_path):
    root = str(tmp_path)
    p = Project(root, tree(root))
    result, warnings = assign(p, ProjectSettings(code="АБВГ"))
    assert warnings == []
    assert by_name(p, result) == {
        "Изделие": "АБВГ.000.00",
        "Узел1": "АБВГ.001.00",
        "Узел2": "АБВГ.002.00",
        "Подузел": "АБВГ.003.00",
        "Втулка": "АБВГ.001.01",
        "Ось": "АБВГ.001.02",  # общая деталь нумеруется в первой сборке
        "Плита": "АБВГ.000.01",
        "Шайба": "АБВГ.003.01",
    }


def test_pins_and_exclusions(tmp_path):
    root = str(tmp_path)
    p = Project(root, tree(root))
    s = ProjectSettings(code="К")
    s.set_pin(root, norm(os.path.join(root, "Узел2.a3d")), "сборка", 1)
    s.set_pin(root, norm(os.path.join(root, "Ось.m3d")), "деталь", 5)
    s.set_excluded(root, norm(os.path.join(root, "Подузел.a3d")), True)
    result, _ = assign(p, s)
    names = by_name(p, result)
    assert names["Узел2"] == "К.001.00"
    assert names["Узел1"] == "К.002.00"
    assert names["Втулка"] == "К.002.01"
    assert names["Ось"] == "К.002.05"
    assert "Подузел" not in names and "Шайба" not in names


def test_settings_roundtrip(tmp_path):
    root = str(tmp_path)
    s = ProjectSettings(code="X")
    key = norm(os.path.join(root, "sub", "a.m3d"))
    s.set_pin(root, key, "деталь", 3)
    s.set_excluded(root, key, True)
    s.save(root)
    s2 = ProjectSettings.load(root)
    assert s2.pin(root, key) == {"деталь": 3}
    assert s2.is_excluded(root, key)
    s2.rename_paths(root, {key: os.path.join(root, "sub", "b.m3d")})
    assert s2.pins == {"sub/b.m3d": {"деталь": 3}}
    assert s2.excluded == ["sub/b.m3d"]
