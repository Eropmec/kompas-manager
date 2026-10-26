"""Прототип управления проектами.

1. copy      — копия папки проекта: куда указывают ссылки в копии (на копию или на оригинал),
               затем перепривязка всех ссылок на файлы внутри копии и повторная проверка.
2. structure — создание структуры: новая сборка и детали (пустые или из шаблонов) в тестовой папке,
               свойства, вставка деталей компонентами в сборку, проверка.

Оригинал проекта не меняется. Отчёты — в %LOCALAPPDATA%\\KompasManager\\reports.
"""
import datetime
import os
import shutil

import kompas as K
from lib_test import report_path
from naming import file_name
from report import Report


def classify(path, copy_root, orig_root):
    n, c, o = K.norm(path), K.norm(copy_root) + os.sep, K.norm(orig_root) + os.sep
    if n.startswith(c):
        return "копия"
    if n.startswith(o):
        return "ОРИГИНАЛ"
    return "вне проекта"


def refs_report(rep, app, copy_root, orig_root):
    """Ссылки всех документов копии с классификацией. Возвращает число ссылок на оригинал."""
    to_orig = 0
    for path in K.list_kompas_files(copy_root):
        with rep.step(os.path.relpath(path, copy_root)):
            doc = K.open_doc(app, path, visible=False, readonly=True)
            try:
                refs = K.references(doc, path)
            finally:
                K.close_doc(doc)
            if not refs:
                rep.line("  ссылок нет")
            for r in refs:
                kind = classify(r, copy_root, orig_root)
                to_orig += kind == "ОРИГИНАЛ"
                rep.line(f"  [{kind}] {r}")
    return to_orig


def relink_copy(rep, app, copy_root, orig_root):
    """Перепривязать ссылки на оригинал к соответствующим файлам копии."""
    def mapped(r):
        n, o = K.norm(r), K.norm(orig_root) + os.sep
        if n.startswith(o):
            target = os.path.join(copy_root, os.path.relpath(r, orig_root))
            return target if os.path.exists(target) else None
        return None

    for path in K.list_kompas_files(copy_root):
        ext = K.ext_of(path)
        if ext not in (".a3d", ".cdw", ".spw"):
            continue
        with rep.step(f"перепривязка: {os.path.relpath(path, copy_root)}"):
            doc = K.open_doc(app, path, visible=False, readonly=False)
            try:
                n = 0
                if ext == ".a3d":
                    for c in K.components(doc):
                        t = mapped(c.FileName)
                        if t:
                            c.FileName = t
                            c.Update()
                            n += 1
                elif ext == ".cdw":
                    for _v, av in K.association_views(doc):
                        t = mapped(av.SourceFileName)
                        if t:
                            av.SourceFileName = t
                            av.Update()
                            n += 1
                else:
                    links = {K.norm(r): mapped(r) for r in K.spec_attached(doc) if mapped(r)}
                    if links:
                        n = K.spec_relink(doc, links)
                if n:
                    doc.Save()
                rep.line(f"  перепривязано ссылок: {n}")
            finally:
                K.close_doc(doc)


def run_copy(project, show=False, on_line=None):
    rep = Report(report_path("copy_test"), on_line)
    orig = os.path.abspath(project)
    copy_root = f"{orig}_copytest_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(orig, copy_root, ignore=shutil.ignore_patterns("_backup", "_old"))
    rep.line(f"Оригинал: {orig}\nКопия:    {copy_root}")
    session = K.Session(show, rep.line)
    try:
        app = session.app
        rep.line("\n##### 1. Куда указывают ссылки в копии сразу после копирования")
        before = refs_report(rep, app, copy_root, orig)
        rep.check("копия сама ссылается только на свои файлы", before == 0,
                  f"ссылок на оригинал: {before}" if before else "")
        if before:
            rep.line("\n##### 2. Перепривязка ссылок на файлы копии")
            relink_copy(rep, app, copy_root, orig)
            rep.line("\n##### 3. Повторная проверка")
            after = refs_report(rep, app, copy_root, orig)
            rep.check("после перепривязки ссылок на оригинал нет", after == 0, f"осталось: {after}" if after else "")
    finally:
        session.close(rep.line)
    rep.line("\nОткрой в КОМПАСе головную сборку копии: в дереве и свойствах компонентов пути должны вести в папку копии.")
    rep.summary()
    return rep.path


def run_structure(folder, code="ТЕСТ", part_template="", asm_template="", show=False, on_line=None):
    rep = Report(report_path("structure_test"), on_line)
    target = os.path.join(folder, f"Структура_{datetime.datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(target)
    rep.line(f"Папка: {target}")
    asm_path = os.path.join(target, file_name(f"{code}.000.00", "Сборка", ".a3d"))
    parts = [(os.path.join(target, file_name(f"{code}.000.{i:02d}", name, ".m3d")), f"{code}.000.{i:02d}", name)
             for i, name in ((1, "Корпус"), (2, "Крышка"))]
    session = K.Session(show, rep.line)
    try:
        app = session.app
        for path, des, name in parts:
            with rep.step(f"деталь {os.path.basename(path)}"):
                if part_template:
                    shutil.copy2(part_template, path)
                    doc = K.open_doc(app, path, visible=show, readonly=False)
                    rep.line("  из шаблона")
                else:
                    doc = K.new_doc(app, path, visible=show)
                    rep.line("  новый пустой документ")
                try:
                    K.write_props(doc, des, name)
                    doc.Save()
                    rep.check("свойства", tuple(K.read_props(doc)) == (des, name), str(K.read_props(doc)))
                finally:
                    K.close_doc(doc)

        with rep.step(f"сборка {os.path.basename(asm_path)}"):
            if asm_template:
                shutil.copy2(asm_template, asm_path)
                doc = K.open_doc(app, asm_path, visible=show, readonly=False)
            else:
                doc = K.new_doc(app, asm_path, visible=show)
            try:
                K.write_props(doc, f"{code}.000.00", "Сборка")
                for path, _d, _n in parts:
                    how = K.add_component(doc, path, rep.line)
                    rep.line(f"  вставлен {os.path.basename(path)}: {how}")
                doc.Save()
            finally:
                K.close_doc(doc)

        with rep.step("проверка сборки"):
            doc = K.open_doc(app, asm_path, visible=False, readonly=True)
            try:
                comps = [(c.FileName, c.Marking, c.Name) for c in K.components(doc)]
            finally:
                K.close_doc(doc)
            for f, m, n in comps:
                rep.line(f"  {m} {n}: {f}")
            got = {K.norm(f) for f, _m, _n in comps}
            rep.check("все детали вставлены компонентами", all(K.norm(p) in got for p, _d, _n in parts),
                      f"компонентов: {len(comps)}")
    finally:
        session.close(rep.line)
    rep.line("\nОткрой сборку в КОМПАСе и проверь дерево и свойства компонентов.")
    rep.summary()
    return rep.path
