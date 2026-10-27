import os

from kompas_manager.core.library import (
    Element,
    Passport,
    Variable,
    load_passport,
    plan_extract,
    plan_insert,
    read_table,
    save_passport,
    scan_library,
)
from kompas_manager.core.naming import format_template


def dnishe_passport():
    return Passport(
        kind="standard",
        designation_template="BTEL.D{D}S{s}",
        name_template="Днище эллиптическое {ISP}-{D}-{s}",
        variables=[Variable("D", 1000.0), Variable("s", 10.0), Variable("ISP", 2.0),
                   Variable("h", 50.0), Variable("YES", 1.0, info=True)],
    )


def test_template():
    assert format_template("BTEL.D{D}S{s}", {"D": 1000.0, "s": 10}) == ("BTEL.D1000S10", [])
    assert format_template("X{q}", {}) == ("X{q}", ["q"])


def test_scan_and_passport(tmp_path):
    lib = tmp_path / "Lib"
    (lib / "Днища").mkdir(parents=True)
    (lib / "Пустая").mkdir()
    (lib / "_old").mkdir()
    model = lib / "Днища" / "Днище.m3d"
    model.write_text("x")
    (lib / "_old" / "Старое.m3d").write_text("x")
    save_passport(str(model), dnishe_passport())
    root = scan_library(str(lib))
    assert [f.title for f in root.folders] == ["Днища"]
    el = root.folders[0].elements[0]
    assert el.passport.name_template.startswith("Днище")
    assert [v.name for v in el.passport.editable_variables()] == ["D", "s", "ISP", "h"]
    assert load_passport(str(model)).variables[4].info


def test_plan_insert(tmp_path):
    el = Element(str(tmp_path / "Lib" / "Днище.m3d"), dnishe_passport())
    plan = plan_insert(el, {"D": "800", "s": "8"}, str(tmp_path))
    assert plan.problems == []
    assert plan.values == {"D": 800.0, "s": 8.0}
    assert (plan.designation, plan.name) == ("BTEL.D800S8", "Днище эллиптическое 2-800-8")
    assert os.path.basename(plan.target) == "BTEL.D800S8 - Днище эллиптическое 2-800-8.m3d"
    assert not plan.reuse
    open(plan.target, "w").close()
    assert plan_insert(el, {"D": "800", "s": "8"}, str(tmp_path)).reuse
    assert plan_insert(el, {"Q": "1"}, str(tmp_path)).problems


def test_read_table(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["D", "s", "h", "Масса"])
    ws.append([800, 8, 40, "12,5"])
    ws.append([None, None, None, None])
    ws.append([1000, "10", 50, 20])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    header, rows = read_table(str(path))
    assert header == ["D", "s", "h", "Масса"]
    assert rows == [{"D": 800, "s": 8, "h": 40, "Масса": 12.5}, {"D": 1000, "s": 10.0, "h": 50, "Масса": 20}]


def test_plan_extract(tmp_path):
    src = str(tmp_path / "Lib" / "Днище.m3d")
    comps = [
        (0, src, {"D": 800.0, "s": 8.0, "ISP": 2.0}),
        (1, src, {"D": 800.0, "s": 8.0, "ISP": 2.0}),
        (2, src, {"D": 1000.0, "s": 10.0, "ISP": 2.0}),  # без изменений
        (3, src, {"D": 600.0, "s": 6.0, "ISP": 2.0}),
    ]
    groups = plan_extract(
        comps,
        {src: {"D": 1000.0, "s": 10.0, "ISP": 2.0}},
        {src: ("BTEL.D1000S10", "Днище эллиптическое 2-1000-10")},
        str(tmp_path),
        {src: dnishe_passport()},
    )
    assert len(groups) == 2
    g = groups[0]
    assert g.instances == [0, 1] and g.values == {"D": 800.0, "s": 8.0}
    assert os.path.basename(g.target) == "BTEL.D800S8 - Днище эллиптическое 2-800-8.m3d"
    # без паспорта: имя по исходному файлу и изменённым значениям
    groups = plan_extract(comps[:1], {src: {"D": 1000.0, "s": 10.0, "ISP": 2.0}}, {src: ("X", "Днище")}, str(tmp_path))
    assert os.path.basename(groups[0].target) == "Днище [D800 s8].m3d"


def test_copy_naming_by_kind(tmp_path):
    from kompas_manager.core.library import copy_file_name

    assert copy_file_name("А.1", "Втулка", ".m3d", "x", {}) == "А.1 - Втулка.m3d"
    assert copy_file_name("", "Фланец 1-50-16 ГОСТ 33259", ".m3d", "x", {}) == "Фланец 1-50-16 ГОСТ 33259.m3d"
    assert copy_file_name("", "", ".m3d", "Фланец", {"Dn": 50.0}) == "Фланец Dn50.m3d"
    flange = Element(str(tmp_path / "Lib" / "Фланец.m3d"), Passport(
        kind="standard", name_template="Фланец 1-{Dn}-{Pn} ГОСТ 33259",
        variables=[Variable("Dn", 50.0), Variable("Pn", 16.0)]))
    plan = plan_insert(flange, {"Dn": "80"}, str(tmp_path), project_designation="Г.001.05")
    assert os.path.basename(plan.target) == "Фланец 1-80-16 ГОСТ 33259.m3d" and plan.designation == ""
    nozzle = Element(str(tmp_path / "Lib" / "Патрубок.m3d"), Passport(
        kind="like_standard", name_template="Патрубок {D}x{s}", variables=[Variable("D", 57.0), Variable("s", 4.0)]))
    plan = plan_insert(nozzle, {}, str(tmp_path), project_designation="Г.001.05")
    assert os.path.basename(plan.target) == "Г.001.05 - Патрубок 57x4.m3d"


def test_origins(tmp_path):
    from kompas_manager.core.settings import ProjectSettings

    root = str(tmp_path)
    copy = tmp_path / "Узел" / "Фланец 1-80-16.m3d"
    copy.parent.mkdir()
    copy.write_text("x")
    s = ProjectSettings()
    s.add_origin(root, str(copy), "D:/Lib/Фланец.m3d", {"Dn": 80.0})
    s.save(root)
    s2 = ProjectSettings.load(root)
    assert s2.find_origin(root, "D:/Lib/Фланец.m3d", {"Dn": "80"}) == str(copy)
    assert s2.find_origin(root, "D:/Lib/Фланец.m3d", {"Dn": "100"}) is None
