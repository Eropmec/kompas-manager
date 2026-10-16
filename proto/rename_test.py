"""Шаг 2. Переобозначение одной детали на КОПИИ тестового проекта.

Оригинал проекта не меняется: копия папки создаётся рядом, «<папка>_proto_<дата>»,
и вся работа идёт в ней. Каждый шаг пишется в отчёт с результатом.

Проверяется:
  1. запись «Обозначение» и «Наименование» в модель детали;
  2. переименование файла детали и перепривязка компонента в сборках;
  3. перепривязка ассоциативных видов чертежа, перестроение, штамп,
     переименование файла чертежа;
  4. что видят спецификации после изменений;
  5. итоговая проверка: нет ли ссылок на несуществующие файлы.

Запуск из командной строки:
    python rename_test.py "D:\\Тест\\Проект" "Втулка.m3d" "АБВГ.001.01" "Втулка"
"""
import argparse
import datetime
import os
import shutil

import kompas as K
from report import Report


def run(project, part, designation, name, on_line=None):
    """Тест переобозначения. part — путь к детали внутри проекта (абсолютный или относительный).
    Возвращает путь к отчёту."""
    src = os.path.abspath(project)
    part_abs = part if os.path.isabs(part) else os.path.join(src, part)
    rel = os.path.relpath(os.path.abspath(part_abs), src)
    if rel.startswith(".."):
        raise ValueError(f"Деталь должна лежать внутри папки проекта: {part_abs}")

    work = f"{src}_proto_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(src, work)
    rep = Report(os.path.join(work, "rename_report.txt"), on_line)
    rep.line(f"Рабочая копия: {work}")

    old_part = os.path.join(work, rel)
    old_dir = os.path.join(work, "_old")
    if not os.path.isfile(old_part):
        rep.line(f"Файл детали не найден: {old_part}")
        rep.summary()
        return rep.path
    new_part = os.path.join(os.path.dirname(old_part), K.file_name(designation, name, ".m3d"))
    rep.line(f"Деталь: {os.path.basename(old_part)} -> {os.path.basename(new_part)}")
    target = (designation, name)

    app = K.connect(visible=True)
    app5 = None
    old_drawings = []

    # --- 0. Граф ссылок до изменений
    graph = {}
    with rep.step("Сканирование ссылок проекта"):
        graph = K.scan(app, work, log=rep.line)
        for path, refs in graph.items():
            rep.line(f"  {os.path.relpath(path, work)}: {len(refs)} ссылок")
    users = {p: refs for p, refs in graph.items() if K.norm(old_part) in {K.norm(r) for r in refs}}
    rep.line("  ссылаются на деталь: " + (", ".join(os.path.basename(p) for p in users) or "никто"))

    # --- 1. Копия детали под новым именем + свойства
    with rep.step("Деталь: копия под новым именем и запись свойств"):
        shutil.copy2(old_part, new_part)
        doc = K.open_doc(app, new_part, visible=True, readonly=False)
        try:
            rep.line(f"  было: {K.read_props(doc)}")
            K.write_props(doc, designation, name)
            doc.Save()
            after = K.read_props(doc)
            rep.line(f"  стало: {after}")
        finally:
            K.close_doc(doc)
        rep.check("свойства детали записаны", after == target, str(after))

    # --- 2. Сборки: перепривязка компонента
    for asm in [p for p in users if K.ext_of(p) == ".a3d"]:
        with rep.step(f"Сборка {os.path.basename(asm)}: замена компонента"):
            doc = K.open_doc(app, asm, visible=True, readonly=False)
            try:
                replaced = 0
                for c in K.components(doc):
                    if K.norm(c.FileName) == K.norm(old_part):
                        c.FileName = new_part
                        c.Update()
                        replaced += 1
                rep.line(f"  заменено вхождений: {replaced}")
                try:
                    K.rebuild_3d(doc)
                except Exception as e:
                    rep.line(f"  перестроение сборки не удалось: {e}")
                doc.Save()
            finally:
                K.close_doc(doc)
            doc = K.open_doc(app, asm, visible=False, readonly=True)
            try:
                refs = {K.norm(r) for r in K.references(doc, asm)}
            finally:
                K.close_doc(doc)
            rep.check("сборка ссылается на новый файл", K.norm(new_part) in refs)
            rep.check("ссылок на старый файл не осталось", K.norm(old_part) not in refs)

    # --- 3. Чертежи: виды, перестроение, штамп, новое имя
    for drw in [p for p in users if K.ext_of(p) == ".cdw"]:
        new_drw = os.path.join(os.path.dirname(drw), K.file_name(designation, name, ".cdw"))
        with rep.step(f"Чертёж {os.path.basename(drw)} -> {os.path.basename(new_drw)}"):
            doc = K.open_doc(app, drw, visible=True, readonly=False)
            try:
                rep.line(f"  штамп до: {K.stamp_values(doc)}")
                switched = 0
                for _v, av in K.association_views(doc):
                    if K.norm(av.SourceFileName) == K.norm(old_part):
                        av.SourceFileName = new_part
                        av.Update()
                        switched += 1
                rep.line(f"  перепривязано видов: {switched}")

                try:
                    how = K.rebuild_2d(doc, app5)
                    rep.line(f"  перестроен: {how}")
                except Exception as e:
                    rep.line(f"  перестроение не удалось: {e}")

                auto = K.stamp_values(doc)
                rep.line(f"  штамп после перестроения: {auto}")
                rep.check("штамп обновился сам из модели", auto == target, str(auto))
                if auto != target:
                    K.write_stamp(doc, designation, name)
                    forced = K.stamp_values(doc)
                    rep.check("штамп записан напрямую", forced == target, str(forced))

                ok = doc.SaveAs(new_drw)
                rep.check("чертёж сохранён под новым именем", bool(ok) and os.path.exists(new_drw))
            finally:
                K.close_doc(doc)
            old_drawings.append(drw)

    # --- 4. Спецификации: что они видят после изменений
    for spw in [p for p in graph if K.ext_of(p) == ".spw"]:
        with rep.step(f"Спецификация {os.path.basename(spw)}"):
            doc = K.open_doc(app, spw, visible=False, readonly=True)
            try:
                for r in K.spec_attached(doc):
                    rep.line(f"    -> {r}  [{'есть' if os.path.exists(r) else 'ФАЙЛА НЕТ'}]")
                rep.line("  Синхронизацию со сборкой проверь вручную в КОМПАСе (см. README).")
            finally:
                K.close_doc(doc)

    # --- 5. Старые файлы — в подпапку _old (не удаляем)
    with rep.step("Перенос старых файлов в _old"):
        os.makedirs(old_dir, exist_ok=True)
        for path in [old_part] + old_drawings:
            shutil.move(path, os.path.join(old_dir, os.path.basename(path)))
            rep.line(f"  перенесён: {os.path.basename(path)}")

    # --- 6. Итоговая проверка ссылок
    def in_old(p):
        return K.norm(p).startswith(K.norm(old_dir) + os.sep)

    with rep.step("Итоговая проверка ссылок"):
        final = K.scan(app, work, log=rep.line)
        live = {p: refs for p, refs in final.items() if not in_old(p)}
        broken = [(p, r) for p, refs in live.items() for r in refs if not os.path.exists(r)]
        for p, r in broken:
            rep.line(f"  битая ссылка: {os.path.basename(p)} -> {r}")
        rep.check("битых ссылок нет", not broken, f"найдено: {len(broken)}" if broken else "")
        stale = [(p, r) for p, refs in live.items() for r in refs if in_old(r)]
        rep.check("никто не ссылается на файлы из _old", not stale, f"найдено: {len(stale)}" if stale else "")

    rep.summary()
    return rep.path


def main():
    ap = argparse.ArgumentParser(description="Тест переобозначения детали на копии проекта")
    ap.add_argument("project", help="папка тестового проекта (не меняется)")
    ap.add_argument("part", help="файл детали относительно папки проекта, например Втулка.m3d")
    ap.add_argument("designation", help="новое обозначение, например АБВГ.001.01")
    ap.add_argument("name", help="новое наименование, например Втулка")
    args = ap.parse_args()
    run(args.project, args.part, args.designation, args.name)


if __name__ == "__main__":
    main()
