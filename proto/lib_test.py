"""Прототип библиотеки: проверка работы с внешними переменными через Kompas API.

1. scan      — список моделей папки библиотеки с внешними переменными (только чтение).
2. insert    — копия библиотечной модели в папку проекта, запись значений переменных в копию,
               перестроение, обозначение и наименование по шаблонам. Оригинал не меняется.
3. instances — для сборки: значения переменных, заданные на уровне вхождения, против значений в файле.

Отчёты пишутся в %LOCALAPPDATA%\\KompasManager\\reports, а не в папку библиотеки.
"""
import datetime
import os
import shutil
import tempfile

import kompas as K
from naming import file_name, format_number, format_template, parse_values
from report import Report


def report_path(prefix):
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    folder = os.path.join(base, "KompasManager", "reports")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{prefix}_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")


def show_vars(rep, title, vars_):
    rep.line(f"  {title}: {len(vars_)}")
    for v in vars_:
        flags = []
        if v["info"]:
            flags.append("информационная")
        if not v["external"]:
            flags.append("внутренняя")
        note = f"  // {v['note']}" if v["note"] else ""
        rep.line(f"    {v['name']:<10} = {str(v['expression']):<14} -> {format_number(v['value'])}"
                 + (f"  [{', '.join(flags)}]" if flags else "") + note)


def ext_values(vars_):
    return {v["name"]: v["value"] for v in vars_ if v["external"]}


# ---------- 1. Список моделей с переменными ----------

def run_scan(folder, verbose=False, show=False, on_line=None):
    rep = Report(report_path("lib_scan"), on_line)
    rep.line(f"Папка библиотеки: {folder}")
    files = [p for p in K.list_kompas_files(folder) if K.ext_of(p) in (".m3d", ".a3d")]
    rep.line(f"Моделей: {len(files)}")
    session = K.Session(show, rep.line)
    props_shown = False
    try:
        for path in files:
            with rep.step(os.path.relpath(path, folder)):
                doc = K.open_doc(session.app, path, visible=False, readonly=True)
                try:
                    des, name = K.read_props(doc)
                    rep.line(f"  Обозначение: {des!r}; Наименование: {name!r}")
                    part = K.top_part(doc)
                    show_vars(rep, "внешние переменные", K.variables(part, True, True))
                    if verbose or not props_shown:  # для разведки API: один раз всегда
                        props_shown = True
                        objs = K.variable_objects(part, True, True)
                        if objs:
                            rep.line(f"  свойства IVariable7: {K.public_props(objs[0])}")
                        rep.line(f"  свойства IFeature7: {K.public_props(K.feature(part))}")
                finally:
                    K.close_doc(doc)
    finally:
        session.close(rep.line)
    rep.summary()
    return rep.path


# ---------- 2. Вставка копии с новыми значениями ----------

def run_insert(model, target_dir, values_text, des_template="", name_template="", show=False, on_line=None):
    rep = Report(report_path("lib_insert"), on_line)
    values = parse_values(values_text)
    rep.line(f"Библиотечная модель: {model}")
    rep.line(f"Папка проекта: {target_dir}")
    rep.line(f"Новые значения: {values}")
    orig_mtime = os.path.getmtime(model)
    ext = os.path.splitext(model)[1]
    tmp = os.path.join(target_dir, f"_tmp_{datetime.datetime.now():%H%M%S}{ext}")

    session = K.Session(show, rep.line)
    final = None
    try:
        app = session.app
        before = []
        with rep.step("Переменные библиотечной модели"):
            doc = K.open_doc(app, model, visible=False, readonly=True)
            try:
                before = K.variables(K.top_part(doc), True, True)
                show_vars(rep, "внешние переменные", before)
            finally:
                K.close_doc(doc)
        unknown = set(values) - {v["name"] for v in before if v["external"]}
        if unknown:
            rep.check("все переменные есть в модели", False, "нет: " + ", ".join(sorted(unknown)))
            rep.summary()
            return rep.path

        with rep.step("Копия в папку проекта, запись значений, перестроение"):
            shutil.copy2(model, tmp)
            doc = K.open_doc(app, tmp, visible=show, readonly=False)
            try:
                how = K.set_variables(doc, values, rep.line)
                rep.line(f"  перестроено: {how}")
                after = K.variables(K.top_part(doc), True, True)
                show_vars(rep, "переменные копии после записи", after)
                got = ext_values(after)
                ok = all(abs(float(got.get(n, "nan")) - float(v)) < 1e-9 for n, v in values.items())
                rep.check("значения переменных записались в копию", ok)

                des, name = K.read_props(doc)
                if des_template or name_template:
                    all_values = {v["name"]: v["value"] for v in after}
                    if des_template:
                        des, miss = format_template(des_template, all_values)
                        if miss:
                            rep.line(f"  в шаблоне обозначения неизвестные переменные: {miss}")
                    if name_template:
                        name, miss = format_template(name_template, all_values)
                        if miss:
                            rep.line(f"  в шаблоне наименования неизвестные переменные: {miss}")
                    K.write_props(doc, des, name)
                    rep.line(f"  Обозначение: {des!r}; Наименование: {name!r}")
                doc.Save()
                rep.check("свойства копии", tuple(K.read_props(doc)) == (des, name), str(K.read_props(doc)))
            finally:
                K.close_doc(doc)
            final = os.path.join(target_dir, file_name(des, name, ext)) if des and name else \
                os.path.join(target_dir, os.path.splitext(os.path.basename(model))[0] + " (копия)" + ext)
            if os.path.exists(final):
                rep.check("имя файла свободно", False, f"уже есть {os.path.basename(final)}; копия оставлена как {os.path.basename(tmp)}")
                final = tmp
            else:
                os.replace(tmp, final)
                rep.line(f"  файл: {os.path.basename(final)}")

        with rep.step("Проверка: копия открывается с новыми значениями, оригинал не изменился"):
            doc = K.open_doc(app, final, visible=False, readonly=True)
            try:
                reread = ext_values(K.variables(K.top_part(doc), True, True))
            finally:
                K.close_doc(doc)
            rep.check("после повторного открытия значения сохранились",
                      all(abs(float(reread.get(n, "nan")) - float(v)) < 1e-9 for n, v in values.items()),
                      str({n: format_number(reread.get(n)) for n in values}))
            doc = K.open_doc(app, model, visible=False, readonly=True)
            try:
                orig = ext_values(K.variables(K.top_part(doc), True, True))
            finally:
                K.close_doc(doc)
            rep.check("файл оригинала не менялся", os.path.getmtime(model) == orig_mtime)
            rep.check("переменные оригинала прежние", orig == ext_values(before))
    finally:
        session.close(rep.line)
        if os.path.exists(tmp) and final != tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    rep.line("\nОткрой копию в КОМПАСе, проверь геометрию и сделай по ней чертёж: размеры должны быть новыми.")
    rep.summary()
    return rep.path


# ---------- 3. Переменные вхождений в сборке ----------

def run_instances(assembly, show=False, on_line=None):
    rep = Report(report_path("lib_instances"), on_line)
    rep.line(f"Сборка: {assembly}")
    session = K.Session(show, rep.line)
    file_vars = {}  # файл компонента -> значения внешних переменных в самом файле

    def vars_in_file(app, path):
        key = K.norm(path)
        if key not in file_vars:
            doc = K.open_doc(app, path, visible=False, readonly=True)
            try:
                file_vars[key] = ext_values(K.variables(K.top_part(doc), True, True))
            finally:
                K.close_doc(doc)
        return file_vars[key]

    changed = 0
    try:
        app = session.app
        doc = K.open_doc(app, assembly, visible=False, readonly=True)
        try:
            comps = [(c.FileName, c.Marking, c.Name, ext_values(K.variables(c, True, False))) for c in K.components(doc)]
        finally:
            K.close_doc(doc)
        rep.line(f"Компонентов: {len(comps)}")
        for path, marking, name, in_asm in comps:
            with rep.step(f"{os.path.basename(path)} ({marking} {name})"):
                if not in_asm:
                    rep.line("  внешних переменных нет")
                    continue
                in_file = vars_in_file(app, path)
                rep.line("  в сборке: " + ", ".join(f"{n}={format_number(v)}" for n, v in in_asm.items()))
                rep.line("  в файле:  " + ", ".join(f"{n}={format_number(v)}" for n, v in in_file.items()))
                diff = {n: (in_file.get(n), v) for n, v in in_asm.items() if in_file.get(n) != v}
                if diff:
                    changed += 1
                    rep.line("  ИЗМЕНЕНЫ В СБОРКЕ: " + ", ".join(
                        f"{n}: {format_number(old)} -> {format_number(new)}" for n, (old, new) in diff.items()))
                else:
                    rep.line("  отличий нет")
        rep.check("найдены вхождения с переменными, изменёнными в сборке", changed > 0, f"вхождений: {changed}")
    finally:
        session.close(rep.line)
    rep.summary()
    return rep.path
