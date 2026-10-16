"""Тесты ядра: связи, структура и проверки проекта на синтетических данных (без КОМПАСа)."""
import os

from kompas_manager.core.cache import ScanCache
from kompas_manager.core.model import ERROR, INFO, WARNING, DocInfo, norm
from kompas_manager.core.naming import file_name
from kompas_manager.core.project import Project


def doc(root, rel, kind, des="", name="", refs=()):
    return DocInfo(path=os.path.join(root, rel), kind=kind, designation=des, name=name,
                   refs=[os.path.join(root, r) if not os.path.isabs(r) else r for r in refs])


def sample(root):
    return [
        doc(root, "АБВГ.000.00 - Изделие.a3d", "assembly", "АБВГ.000.00", "Изделие",
            ["sub/АБВГ.001.00 - Узел.a3d", "АБВГ.000.01 - Плита.m3d"]),
        doc(root, "sub/АБВГ.001.00 - Узел.a3d", "assembly", "АБВГ.001.00", "Узел",
            ["sub/АБВГ.001.01 - Втулка.m3d", "sub/АБВГ.001.01 - Втулка.m3d", "sub/АБВГ.001.02 - Ось.m3d"]),
        doc(root, "АБВГ.000.01 - Плита.m3d", "part", "АБВГ.000.01", "Плита"),
        doc(root, "sub/АБВГ.001.01 - Втулка.m3d", "part", "АБВГ.001.01", "Втулка"),
        doc(root, "sub/АБВГ.001.02 - Ось.m3d", "part", "АБВГ.001.02", "Ось"),
        doc(root, "sub/АБВГ.001.01 - Втулка.cdw", "drawing", "АБВГ.001.01", "Втулка",
            ["sub/АБВГ.001.01 - Втулка.m3d"]),
        doc(root, "АБВГ.000.00 - Изделие.cdw", "drawing", "АБВГ.000.00 СБ", "Изделие",
            ["АБВГ.000.00 - Изделие.a3d"]),
        doc(root, "АБВГ.000.00 - Изделие.spw", "spec", "АБВГ.000.00", "Изделие",
            ["АБВГ.000.00 - Изделие.a3d"]),
    ]


def messages(project, rel, root):
    return [(i.severity, i.message) for i in project.issues_by_key.get(norm(os.path.join(root, rel)), [])]


def test_file_name_template():
    assert file_name("АБВГ.000.00", "Втулка", ".m3d") == "АБВГ.000.00 - Втулка.m3d"
    assert file_name("A/B", "x:y", ".m3d") == "A_B - x_y.m3d"


def test_structure(tmp_path):
    root = str(tmp_path)
    p = Project(root, sample(root))
    assert p.roots() == [norm(os.path.join(root, "АБВГ.000.00 - Изделие.a3d"))]
    sub = norm(os.path.join(root, "sub/АБВГ.001.00 - Узел.a3d"))
    comps = dict(p.components[sub])
    assert comps[norm(os.path.join(root, "sub/АБВГ.001.01 - Втулка.m3d"))] == 2
    assert p.loose_parts() == []
    assert p.unlinked_documents() == []
    part = norm(os.path.join(root, "sub/АБВГ.001.01 - Втулка.m3d"))
    assert len(p.drawings_of[part]) == 1


def test_clean_project_has_only_infos(tmp_path):
    root = str(tmp_path)
    p = Project(root, sample(root))
    # Плита и Ось без чертежей, подсборка без спецификации — это замечания, не ошибки
    assert {i.severity for i in p.issues} == {INFO}
    assert (INFO, "Нет чертежа") in messages(p, "АБВГ.000.01 - Плита.m3d", root)
    assert (INFO, "Нет спецификации") in messages(p, "sub/АБВГ.001.00 - Узел.a3d", root)


def test_broken_and_outside_refs(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "other.m3d"
    outside.write_text("x")
    docs = [doc(str(root), "A - Сборка.a3d", "assembly", "A", "Сборка", ["missing.m3d", str(outside)])]
    p = Project(str(root), docs)
    msgs = messages(p, "A - Сборка.a3d", str(root))
    assert any(s == ERROR and "Битая ссылка" in m for s, m in msgs)
    assert any(s == WARNING and "за пределы папки" in m for s, m in msgs)


def test_duplicate_designation_and_template(tmp_path):
    root = str(tmp_path)
    docs = [
        doc(root, "Втулка.m3d", "part", "АБВГ.001.01", "Втулка"),
        doc(root, "Втулка2.m3d", "part", "АБВГ.001.01", "Втулка"),
    ]
    p = Project(root, docs)
    msgs = messages(p, "Втулка.m3d", root)
    assert any(s == ERROR and "повторяется" in m for s, m in msgs)
    assert any(s == WARNING and "АБВГ.001.01 - Втулка.m3d" in m for s, m in msgs)


def test_stamp_mismatch(tmp_path):
    root = str(tmp_path)
    docs = [
        doc(root, "A - Деталь.m3d", "part", "A", "Деталь"),
        doc(root, "A - Деталь.cdw", "drawing", "Б", "Деталь", ["A - Деталь.m3d"]),
    ]
    p = Project(root, docs)
    msgs = messages(p, "A - Деталь.cdw", root)
    assert any(s == WARNING and "в штампе" in m for s, m in msgs)


def test_cache_roundtrip(tmp_path):
    cache = ScanCache(str(tmp_path / "c.sqlite3"))
    info = DocInfo(path=str(tmp_path / "x.m3d"), kind="part", designation="A", name="Б", mtime=1.5, size=10)
    cache.put(info)
    assert cache.get(info.path, 1.5, 10).designation == "A"
    assert cache.get(info.path, 2.0, 10) is None
    cache.clear()
    assert cache.get(info.path, 1.5, 10) is None
    cache.close()
