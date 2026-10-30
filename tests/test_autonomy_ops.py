"""Автономность, вставка узла, уровень выше — с подменённым Kompas API."""
import os

from kompas_manager import autonomy_ops, structure_ops
from kompas_manager.core.model import norm
from kompas_manager.core.project import Project
from kompas_manager.core.transfer import plan_paste
from test_project import doc
from test_structure_ops import FILES, fake


def put(path, des="", name="", refs=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(os.path.basename(path))
    FILES[norm(path)] = {"des": des, "name": name, "refs": list(refs)}


def patch_copy(monkeypatch):
    real = structure_ops.shutil.copy2

    def copy2(a, b, *x, **k):
        real(a, b, *x, **k)
        if norm(a) in FILES:
            FILES[norm(b)] = {kk: (list(v) if isinstance(v, list) else v) for kk, v in FILES[norm(a)].items()}

    monkeypatch.setattr(structure_ops.shutil, "copy2", copy2)
    monkeypatch.setattr(autonomy_ops.shutil, "copy2", copy2)


def test_localize_chain(tmp_path, monkeypatch):
    FILES.clear()
    patch_copy(monkeypatch)
    root = tmp_path / "Изделие"
    lib = tmp_path / "Lib"
    lib_part = str(lib / "Фланец.m3d")
    lib_asm = str(lib / "Соединение.a3d")
    put(lib_part, "Ф", "Фланец")
    put(str(lib / "Прокладка.m3d"), "П", "Прокладка")
    put(lib_asm, "С", "Соединение", [lib_part, str(lib / "Прокладка.m3d")])
    head = str(root / "А.a3d")
    sub = str(root / "Узел" / "У.a3d")
    put(sub, "У", "У", [lib_part])
    put(head, "А", "А", [sub, lib_asm, lib_part])
    created, missing, _src = autonomy_ops.localize(fake(), str(root), [head, sub], log=lambda *_: None)
    names = sorted(os.path.relpath(p, root) for p in created)
    # фланец — один файл на изделие (в папке первого ссылающегося), состав библиотечной сборки — рядом с ней
    assert names == sorted(["Соединение.a3d", "Прокладка.m3d", os.path.join("Узел", "Фланец.m3d")]) or \
        names == sorted(["Соединение.a3d", "Прокладка.m3d", "Фланец.m3d"])
    flange = [p for p in created if p.endswith("Фланец.m3d")][0]
    for path in (head, sub):
        refs = FILES[norm(path)]["refs"]
        assert all(str(root) in r for r in refs)
        assert lib_part not in refs
    new_asm = os.path.join(str(root), "Соединение.a3d")
    assert FILES[norm(new_asm)]["refs"] == [flange, os.path.join(str(root), "Прокладка.m3d")]
    assert missing == []


def test_paste_and_level_up(tmp_path, monkeypatch):
    FILES.clear()
    patch_copy(monkeypatch)
    lib_part = str(tmp_path / "Lib" / "Днище.m3d")
    put(lib_part, "Д", "Днище")
    src = tmp_path / "Src"
    s_asm, s_part = str(src / "Х.001.00 - Узел.a3d"), str(src / "Х.001.01 - Патрубок.m3d")
    put(s_part, "Х.001.01", "Патрубок")
    put(s_asm, "Х.001.00", "Узел", [s_part, lib_part])
    sp = Project(str(src), [doc(str(src), os.path.basename(s_asm), "assembly", "Х.001.00", "Узел", [s_part, lib_part]),
                            doc(str(src), os.path.basename(s_part), "part", "Х.001.01", "Патрубок")])
    dst = tmp_path / "Dst"
    head = str(dst / "Г.000.00 - Аппарат.a3d")
    put(head, "Г.000.00", "Аппарат", [])
    plan = plan_paste(sp, norm(s_asm), str(dst))
    new_root, created, missing, _src = autonomy_ops.paste_node(fake(), str(dst), plan, head, log=lambda *_: None)
    assert FILES[norm(head)]["refs"] == [new_root]
    refs = FILES[norm(new_root)]["refs"]
    assert all(r.startswith(str(dst)) for r in refs)  # и деталь, и днище — уже внутри изделия
    assert os.path.exists(os.path.join(str(dst), "Днище.m3d"))
    assert FILES[norm(s_asm)]["refs"] == [s_part, lib_part]  # источник не изменился

    top = autonomy_ops.level_up(fake(), str(dst), "Г.100.00", "Установка", head, log=lambda *_: None)
    assert os.path.basename(top) == "Г.100.00 - Установка.a3d"
    assert FILES[norm(top)]["refs"] == [head] and FILES[norm(head)]["des"] == "Г.000.00"


def test_add_occurrence(tmp_path, monkeypatch):
    FILES.clear()
    root = tmp_path / "Изделие"
    part = str(root / "Деталь.m3d")
    head = str(root / "А.a3d")
    put(part, "Д", "Деталь")
    put(head, "А", "А", [part])
    autonomy_ops.add_occurrence(fake(), str(root), head, part, count=2, log=lambda *_: None)
    assert FILES[norm(head)]["refs"] == [part, part, part]
    assert os.path.isdir(root / "_backup")
    import pytest
    with pytest.raises(RuntimeError):
        autonomy_ops.add_occurrence(fake(), str(root), head, head, log=lambda *_: None)
