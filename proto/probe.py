"""Шаг 1. Разведка, только чтение.

Открывает файлы проекта без права записи и показывает, что видит API:
обозначения и наименования, ссылки сборок, чертежей и спецификаций, штампы.

Запуск:
    python probe.py "D:\\Тест\\Проект"
    python probe.py "D:\\Тест\\Проект" --verbose
"""
import argparse
import os

import kompas as K
from report import Report


def show_refs(rep, refs):
    for r in refs:
        mark = "есть" if os.path.exists(r) else "ФАЙЛА НЕТ"
        rep.line(f"    -> {r}  [{mark}]")


def probe_file(app, path, rep, verbose):
    ext = K.ext_of(path)
    rep.line(f"\n=== {os.path.basename(path)}  ({K.EXT_TYPES[ext]})")
    doc = K.open_doc(app, path, visible=False, readonly=True)
    try:
        if verbose:
            rep.line(f"  свойства документа: {K.public_props(doc)}")

        if ext in (".m3d", ".a3d"):
            with rep.step(f"{os.path.basename(path)}: свойства модели"):
                marking, name = K.read_props(doc)
                rep.line(f"  Обозначение: {marking!r}")
                rep.line(f"  Наименование: {name!r}")
                if verbose:
                    rep.line(f"  свойства TopPart: {K.public_props(K.top_part(doc))}")

        if ext == ".a3d":
            with rep.step(f"{os.path.basename(path)}: компоненты сборки"):
                comps = K.components(doc)
                rep.line(f"  компонентов: {len(comps)}")
                for c in comps:
                    rep.line(f"    {c.Marking!r} / {c.Name!r}")
                show_refs(rep, [c.FileName for c in comps])
                if verbose and comps:
                    rep.line(f"  свойства компонента: {K.public_props(comps[0])}")

        if ext == ".cdw":
            with rep.step(f"{os.path.basename(path)}: ассоциативные виды"):
                views = K.association_views(doc)
                rep.line(f"  ассоциативных видов: {len(views)}")
                show_refs(rep, [av.SourceFileName for _v, av in views])
                if verbose and views:
                    rep.line(f"  свойства IAssociationView: {K.public_props(views[0][1])}")

        if ext in (".cdw", ".spw"):
            with rep.step(f"{os.path.basename(path)}: основная надпись"):
                designation, name = K.stamp_values(doc)
                rep.line(f"  Штамп, обозначение: {designation!r}")
                rep.line(f"  Штамп, наименование: {name!r}")

        if ext == ".spw":
            with rep.step(f"{os.path.basename(path)}: связанные документы спецификации"):
                show_refs(rep, K.spec_attached(doc))
    finally:
        K.close_doc(doc)


def run(target, verbose=False, on_line=None):
    """Разведка папки проекта или файла. Возвращает путь к отчёту."""
    target = os.path.abspath(target)
    folder = target if os.path.isdir(target) else os.path.dirname(target)
    rep = Report(os.path.join(folder, "probe_report.txt"), on_line)

    app = None
    with rep.step("Подключение к КОМПАС-3D"):
        app = K.connect(visible=True)
        rep.line(f"  подключено: {app}")

    if app is not None:
        files = K.list_kompas_files(target)
        rep.line(f"\nФайлов КОМПАС: {len(files)}")
        for path in files:
            with rep.step(f"Открытие {os.path.basename(path)}"):
                probe_file(app, path, rep, verbose)

    rep.summary()
    return rep.path


def main():
    ap = argparse.ArgumentParser(description="Разведка Kompas API на тестовом проекте (только чтение)")
    ap.add_argument("path", help="папка проекта или отдельный файл КОМПАС")
    ap.add_argument("--verbose", action="store_true", help="выводить списки свойств интерфейсов")
    args = ap.parse_args()
    run(args.path, args.verbose)


if __name__ == "__main__":
    main()
