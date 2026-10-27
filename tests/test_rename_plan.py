import os

from kompas_manager.core.backup import Backup
from kompas_manager.core.model import ERROR, norm
from kompas_manager.core.project import Project
from kompas_manager.core.rename_plan import build_plan
from test_project import doc


def proj(root):
    return Project(root, [
        doc(root, "ЭСК.0 - Изделие.a3d", "assembly", "ЭСК.0", "Изделие", ["sub/ЭСК.1 - Втулка.m3d"]),
        doc(root, "sub/ЭСК.1 - Втулка.m3d", "part", "ЭСК.1", "Втулка"),
        doc(root, "sub/ЭСК.1 - Втулка.cdw", "drawing", "ЭСК.1", "Втулка", ["sub/ЭСК.1 - Втулка.m3d"]),
        doc(root, "ЭСК.0 СБ - Изделие.cdw", "drawing", "ЭСК.0 СБ", "Изделие", ["ЭСК.0 - Изделие.a3d"]),
        doc(root, "ЭСК.0 - Изделие.spw", "spec", "ЭСК.0", "Изделие",
            ["ЭСК.0 - Изделие.a3d", "ЭСК.0 СБ - Изделие.cdw"]),
    ])


def key(root, rel):
    return norm(os.path.join(root, rel))


def test_plan_follows_links(tmp_path):
    root = str(tmp_path)
    p = proj(root)
    plan = build_plan(p, {key(root, "sub/ЭСК.1 - Втулка.m3d"): ("АБВГ.000.01", "Втулка")})
    assert plan.errors == []
    ops = {os.path.basename(o.old_path): o for o in plan.ops}
    part = ops["ЭСК.1 - Втулка.m3d"]
    assert os.path.basename(part.new_path) == "АБВГ.000.01 - Втулка.m3d"
    drw = ops["ЭСК.1 - Втулка.cdw"]
    assert drw.retitle and os.path.basename(drw.new_path) == "АБВГ.000.01 - Втулка.cdw"
    assert drw.relink == [(part.key, part.new_path)]
    asm = ops["ЭСК.0 - Изделие.a3d"]
    assert not asm.renamed and not asm.retitle and asm.relink == [(part.key, part.new_path)]
    assert "ЭСК.0 - Изделие.spw" not in ops  # спецификация ссылается только на сборку и СБ


def test_assembly_rename_keeps_document_code(tmp_path):
    root = str(tmp_path)
    p = proj(root)
    plan = build_plan(p, {key(root, "ЭСК.0 - Изделие.a3d"): ("АБВГ.000.00", "Насос")})
    ops = {os.path.basename(o.old_path): o for o in plan.ops}
    assert ops["ЭСК.0 СБ - Изделие.cdw"].new_designation == "АБВГ.000.00 СБ"
    assert os.path.basename(ops["ЭСК.0 СБ - Изделие.cdw"].new_path) == "АБВГ.000.00 СБ - Насос.cdw"
    spec = ops["ЭСК.0 - Изделие.spw"]
    assert spec.new_designation == "АБВГ.000.00"
    assert os.path.basename(spec.new_path) == "АБВГ.000.00 - Насос.spw"
    assert len(spec.relink) == 2  # сборка и сборочный чертёж
    assert [o.kind for o in plan.ops] == ["assembly", "drawing", "spec"]


def test_conflicts(tmp_path):
    root = str(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "Б - Втулка.m3d").write_text("x")
    p = proj(root)
    plan = build_plan(p, {key(root, "sub/ЭСК.1 - Втулка.m3d"): ("Б", "Втулка")})
    assert any("уже существует" in i.message for i in plan.errors)
    plan = build_plan(p, {key(root, "sub/ЭСК.1 - Втулка.m3d"): ("ЭСК.0", "Втулка")})
    assert any(i.severity == ERROR and "будет у 2" in i.message for i in plan.issues)
    plan = build_plan(p, {key(root, "sub/ЭСК.1 - Втулка.m3d"): ("", "Втулка")})
    assert plan.errors and not plan.ops


def test_no_changes(tmp_path):
    root = str(tmp_path)
    p = proj(root)
    plan = build_plan(p, {key(root, "sub/ЭСК.1 - Втулка.m3d"): ("ЭСК.1", "Втулка")})
    assert plan.ops == [] and plan.issues == []


def test_backup_and_rollback(tmp_path):
    root = str(tmp_path)
    a = tmp_path / "a.m3d"
    b = tmp_path / "sub" / "b.a3d"
    b.parent.mkdir()
    a.write_text("A")
    b.write_text("B")
    bk = Backup.create(root, [str(a), str(b)])
    new = tmp_path / "new.m3d"
    new.write_text("A2")
    bk.created(str(new))
    bk.remove_original(str(a))
    b.write_text("B-changed")
    assert Backup.latest(root).folder == bk.folder
    assert bk.rollback(log=lambda *_: None) == []
    assert a.read_text() == "A" and b.read_text() == "B" and not new.exists()
    assert Backup.latest(root) is None


def test_bulk_replace():
    from kompas_manager.core.bulk import bulk_replace

    values = {"a": ("ЭСК.1", "Втулка опорная"), "b": ("ЭСК.2", "Ось")}
    assert bulk_replace(values, "name", "втулка", "Гильза") == {"a": ("ЭСК.1", "Гильза опорная")}
    assert bulk_replace(values, "name", "втулка", "Гильза", case_sensitive=True) == {}
    assert bulk_replace(values, "designation", "ЭСК", "АБВГ") == {"a": ("АБВГ.1", "Втулка опорная"), "b": ("АБВГ.2", "Ось")}


def test_group_edit():
    from kompas_manager.core.bulk import group_edit

    v = {"a": ("Г.001.01", "Патрубок"), "b": ("Г.001.02", "Патрубок входа")}
    assert group_edit(v, "suffix", " Ду50")["a"] == ("Г.001.01", "Патрубок Ду50")
    assert group_edit(v, "prefix", "Узел. ")["b"] == ("Г.001.02", "Узел. Патрубок входа")
    assert group_edit(v, "set", "Штуцер")["b"][1] == "Штуцер"
    assert group_edit(v, "replace", "Штуцер", name_find="патрубок")["b"][1] == "Штуцер входа"
    assert group_edit(v, des_find="Г.001", des_repl="Г.002")["a"][0] == "Г.002.01"
