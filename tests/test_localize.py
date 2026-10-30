import os
import zipfile

from kompas_manager.core.editing import renumber_subtree
from kompas_manager.core.localize import Placement, archive_product, external_refs
from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.settings import ProjectSettings
from kompas_manager.core.transfer import plan_paste
from test_project import doc


def test_placement_and_external(tmp_path):
    root = tmp_path / "Изделие"
    (root / "Узел").mkdir(parents=True)
    lib = tmp_path / "Lib" / "Днище.m3d"
    docs = [
        doc(str(root), "А.a3d", "assembly", "Г.000.00", "А", ["Узел/У.a3d", str(lib)]),
        doc(str(root), "Узел/У.a3d", "assembly", "Г.001.00", "У", [str(lib)]),
    ]
    p = Project(str(root), docs)
    ext = external_refs(p)
    assert list(ext) == [norm(str(lib))] and len(ext[norm(str(lib))][1]) == 2
    pl = Placement(str(root), existing=[d.path for d in docs])
    t1, reuse1 = pl.target(str(lib), docs[1].path)
    t2, reuse2 = pl.target(str(lib), docs[0].path)
    assert t1 == os.path.join(str(root), "Узел", "Днище.m3d") and not reuse1
    assert t2 == t1 and reuse2  # один типоразмер — один файл на изделие


def test_archive(tmp_path):
    root = tmp_path / "Изделие"
    for rel in ("А.a3d", "Узел/У.a3d", "_backup/x.a3d", "_versions/v.zip", "~$tmp.a3d"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    out = tmp_path / "Изделие.zip"
    assert archive_product(str(root), str(out)) == 2
    names = sorted(zipfile.ZipFile(out).namelist())
    assert names == ["Изделие/А.a3d", "Изделие/Узел/У.a3d"] or names == ["Изделие\\А.a3d", "Изделие\\Узел\\У.a3d"]


def test_plan_paste_subfolder_on_conflict(tmp_path):
    src = tmp_path / "Src"
    root = str(src)
    docs = [doc(root, "Г.001.00 - Узел.a3d", "assembly", "Г.001.00", "Узел", ["Г.001.01 - Деталь.m3d"]),
            doc(root, "Г.001.01 - Деталь.m3d", "part", "Г.001.01", "Деталь")]
    p = Project(root, docs)
    dst = tmp_path / "Dst"
    dst.mkdir()
    plan = plan_paste(p, norm(docs[0].path), str(dst))
    assert os.path.dirname(plan.new_root) == str(dst)
    (dst / "Г.001.01 - Деталь.m3d").write_text("x")
    plan = plan_paste(p, norm(docs[0].path), str(dst))
    assert os.path.dirname(plan.new_root) == str(dst / "Г.001.00 - Узел") and plan.problems == []


def test_renumber_subtree(tmp_path):
    root = str(tmp_path)
    docs = [
        doc(root, "Г.000.00 - Аппарат.a3d", "assembly", "Г.000.00", "Аппарат",
            ["Г.001.00 - Корпус.a3d", "В/Х.001.00 - Узел.a3d"]),
        doc(root, "Г.001.00 - Корпус.a3d", "assembly", "Г.001.00", "Корпус", ["Г.001.01 - Обечайка.m3d"]),
        doc(root, "Г.001.01 - Обечайка.m3d", "part", "Г.001.01", "Обечайка"),
        # вставленный узел со старыми обозначениями другого изделия
        doc(root, "В/Х.001.00 - Узел.a3d", "assembly", "Х.001.00", "Узел", ["В/Х.001.01 - Патрубок.m3d"] * 2),
        doc(root, "В/Х.001.01 - Патрубок.m3d", "part", "Х.001.01", "Патрубок"),
    ]
    p = Project(root, docs)
    res = renumber_subtree(p, norm(docs[0].path), norm(docs[3].path), ProjectSettings(code="Г"))
    assert res == {norm(docs[3].path): "Г.002.00", norm(docs[4].path): "Г.002.01"}


def test_structure_files(tmp_path):
    from kompas_manager.core.localize import structure_files
    from kompas_manager.core.model import norm
    from kompas_manager.core.project import Project
    from test_project import doc

    root = str(tmp_path)
    p = Project(root, [
        doc(root, "А/Г.000.00 - Аппарат.a3d", "assembly", "Г.000.00", "Аппарат", ["Б/Б.000.00 - Насос.a3d"]),
        doc(root, "Б/Б.000.00 - Насос.a3d", "assembly", "Б.000.00", "Насос", ["Б/Б.000.01 - Вал.m3d"]),
        doc(root, "Б/Б.000.01 - Вал.m3d", "part", "Б.000.01", "Вал"),
        doc(root, "Б/Б.000.01 - Вал.cdw", "drawing", "Б.000.01", "Вал", ["Б/Б.000.01 - Вал.m3d"]),
        doc(root, "А/Г.001.00 - Старый узел.a3d", "assembly", "Г.001.00", "Старый узел", ["А/Г.001.01 - Ось.m3d"]),
        doc(root, "А/Г.001.01 - Ось.m3d", "part", "Г.001.01", "Ось"),
        doc(root, "А/Г.001.00 - Старый узел.spw", "spec", "Г.001.00", "Старый узел", ["А/Г.001.00 - Старый узел.a3d"]),
    ])
    head = norm(os.path.join(root, "А", "Г.000.00 - Аппарат.a3d"))
    keep, out = structure_files(p, [head])
    names = sorted(os.path.basename(x) for x in out)
    assert names == ["Г.001.00 - Старый узел.a3d", "Г.001.00 - Старый узел.spw", "Г.001.01 - Ось.m3d"]
    assert norm(os.path.join(root, "Б", "Б.000.01 - Вал.cdw")) in keep
