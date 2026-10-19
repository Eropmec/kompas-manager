"""Операции библиотеки через Kompas API (проверены на прототипе).

- read_element: обозначение, наименование и внешние переменные модели;
- insert_copy: копия модели в папку проекта с новыми значениями переменных и свойствами;
- analyze_assembly / extract_instances: вынос вхождений, у которых переменные изменены
  в сборке, в отдельные файлы с перепривязкой компонентов.
"""
import datetime
import os
import shutil

from kompas_manager.core.backup import Backup
from kompas_manager.core.library import Element, Variable, resolve_names


def ext_values(vars_):
    return {v["name"]: v["value"] for v in vars_ if v["external"]}


def read_element(K, app, path):
    doc = K.open_doc(app, path, visible=False, readonly=True)
    try:
        des, name = K.read_props(doc)
        vars_ = K.variables(K.top_part(doc), True, True)
    finally:
        K.close_doc(doc)
    variables = [Variable(v["name"], v["value"], v["note"] or "", bool(v["info"]))
                 for v in vars_ if v["external"]]
    return (des or "").strip(), (name or "").strip(), variables


def _copy_with_values(K, app, source, target, values, element=None, props=None, show=False, log=print):
    """Копия source -> target с записью значений переменных и свойств. Возвращает (обозначение, наименование)."""
    ext = os.path.splitext(source)[1]
    tmp = os.path.join(os.path.dirname(target), f"_tmp_{datetime.datetime.now():%H%M%S%f}{ext}")
    shutil.copy2(source, tmp)
    try:
        doc = K.open_doc(app, tmp, visible=show, readonly=False)
        try:
            if values:
                how = K.set_variables(doc, values, log)
                log(f"  перестроено: {how}")
            after = {v["name"]: v["value"] for v in K.variables(K.top_part(doc), True, True)}
            for n, v in values.items():
                got = after.get(n)
                if isinstance(v, float) and (got is None or abs(float(got) - v) > 1e-9):
                    raise RuntimeError(f"переменная {n}: записано {v}, прочитано {got}")
            des, name = K.read_props(doc)
            if props is not None:
                des, name = props
            if element is not None:
                des, name, problems = resolve_names(element, after, des, name)
                for p in problems:
                    log("  " + p)
            K.write_props(doc, des, name)
            doc.Save()
        finally:
            K.close_doc(doc)
        if os.path.exists(target):
            raise RuntimeError(f"файл уже существует: {os.path.basename(target)}")
        os.replace(tmp, target)
        return des, name
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def insert_copy(K, plan, element, show=False, log=print):
    """Выполнить InsertPlan. Возвращает путь к файлу в проекте."""
    if plan.reuse:
        log(f"Такой файл уже есть в проекте, используется он: {os.path.basename(plan.target)}")
        return plan.target
    session = K.Session(show, log)
    try:
        des, name = _copy_with_values(K, session.app, plan.source, plan.target, plan.values,
                                      element=element, show=show, log=log)
        log(f"Создан: {os.path.basename(plan.target)} ({des} {name})")
        return plan.target
    finally:
        session.close(log)


def analyze_assembly(K, assembly, show=False, log=print):
    """Компоненты сборки и значения переменных в сборке и в файлах."""
    session = K.Session(show, log)
    try:
        app = session.app
        doc = K.open_doc(app, assembly, visible=False, readonly=True)
        try:
            comps = []
            for i, c in enumerate(K.components(doc)):
                comps.append((i, c.FileName, ext_values(K.variables(c, True, False))))
        finally:
            K.close_doc(doc)
        file_values, file_props = {}, {}
        for _i, path, in_asm in comps:
            if in_asm and path not in file_values and os.path.exists(path):
                d = K.open_doc(app, path, visible=False, readonly=True)
                try:
                    file_values[path] = ext_values(K.variables(K.top_part(d), True, True))
                    des, name = K.read_props(d)
                    file_props[path] = ((des or "").strip(), (name or "").strip())
                finally:
                    K.close_doc(d)
        return comps, file_values, file_props
    finally:
        session.close(log)


def extract_instances(K, root, assembly, groups, passports, show=False, log=print):
    """Создать файлы для групп ExtractGroup и перепривязать компоненты сборки.
    Перед изменением сборка копируется в _backup (откат — как у переобозначения)."""
    backup = Backup.create(root, [assembly], "Вынос вхождений в файлы")
    log(f"Резервная копия: {backup.folder}")
    session = K.Session(show, log)
    try:
        app = session.app
        for g in groups:
            if g.reuse:
                log(f"  используется существующий файл: {os.path.basename(g.target)}")
                continue
            p = passports.get(g.source)
            element = Element(g.source, p) if p and (p.designation_template or p.name_template) else None
            des, name = _copy_with_values(K, app, g.source, g.target, g.values, element=element,
                                          props=(g.designation, g.name), show=show, log=log)
            backup.created(g.target)
            log(f"  создан: {os.path.basename(g.target)} ({des} {name})")
        target_of = {i: g.target for g in groups for i in g.instances}
        doc = K.open_doc(app, assembly, visible=show, readonly=False)
        try:
            n = 0
            for i, c in enumerate(K.components(doc)):
                if i in target_of:
                    c.FileName = target_of[i]
                    c.Update()
                    n += 1
            try:
                K.rebuild_3d(doc)
            except Exception as e:
                log(f"  перестроение сборки: {e}")
            doc.Save()
        finally:
            K.close_doc(doc)
        log(f"Перепривязано вхождений: {n}")
        return backup
    finally:
        session.close(log)
